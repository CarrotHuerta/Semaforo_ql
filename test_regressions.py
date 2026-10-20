"""Startup, navigation, integration lifecycle and real report regressions."""

import concurrent.futures
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import shutil
import sysconfig
import venv
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QThread, QTimer
from PySide6.QtCore import SIGNAL
from PySide6.QtGui import QCloseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

import check_dependencies
import functional_core as core
import i18n
import main


class StartupRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.config = {"users": [], "language": "es", "notifications_os": False}
        self.patches = [
            patch.object(main, "writable_path", side_effect=lambda *parts: str(self.root.joinpath(*parts))),
            patch.object(main, "load_config", side_effect=lambda: dict(self.config)),
            patch.object(i18n, "_CONFIG_PATH", str(self.root / "config.json")),
            patch.object(main.FinOpsView, "_refresh_exchange_rates"),
            patch.object(main.ProjectsView, "_mlflow_run_items", return_value=["Sin conexión de prueba"]),
            patch.object(main, "get_hardware_info", return_value={"cpu": "CPU de prueba"}),
        ]
        for item in self.patches:
            item.start()
        self.previous_lang = i18n.get_language()
        i18n.set_language("es")
        self.windows = []

    def tearDown(self):
        for window in self.windows:
            for thread in window.findChildren(QThread):
                thread.requestInterruption()
                self.assertTrue(thread.wait(3000), "A test worker did not finish")
            window.close()
            window.deleteLater()
        self.app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        for item in reversed(self.patches):
            item.stop()
        i18n.set_language(self.previous_lang)
        self.directory.cleanup()

    def dashboard(self):
        window = main.DashboardWindow({"username": "test", "role": "Administrador"})
        self.windows.append(window)
        return window

    def wait_until(self, predicate, timeout=3000):
        deadline = time.monotonic() + timeout / 1000
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertTrue(predicate())

    def test_dashboard_opens_without_initializing_hidden_views_or_database(self):
        with patch.object(main, "bootstrap_store", side_effect=AssertionError("Startup accessed SQLite")):
            window = self.dashboard()
            window.show()
            self.app.processEvents()
            self.assertEqual(window._loaded_views, {})
            self.assertEqual(window.stack.count(), 11)
            window.refresh_projects_view()
            window._handle_cloud_selection(cloud_enabled=True)
            self.assertFalse(window.is_simulation_running())
            self.assertEqual(window._loaded_views, {})

    def test_every_navigation_button_loads_and_reuses_its_screen(self):
        window = self.dashboard()
        window.show()
        names = [None, "models_view", "projects_view", "environmental_view", "finops_view",
                 "comparisons_view", "hardware_view", "cloud_view", "history_view", "settings_view", "admin_view"]
        for index, (button, name) in enumerate(zip(window.sidebar.button_group.buttons(), names)):
            with self.subTest(screen=name):
                button.click()
                self.app.processEvents()
                self.assertEqual(window.stack.currentIndex(), index)
                if name:
                    self.assertIs(window.stack.currentWidget().widget(), window._loaded_views[name])
                    original = window._loaded_views[name]
                    button.click()
                    self.assertIs(window._loaded_views[name], original)

    def test_cloud_lock_is_applied_when_settings_are_first_opened(self):
        window = self.dashboard()
        window._handle_cloud_selection(cloud_enabled=True)
        self.assertNotIn("settings_view", window._loaded_views)
        settings = window.settings_view
        self.assertTrue(all(not field.isEnabled() for field in settings._local_factor_inputs))
        window._handle_cloud_selection(cloud_enabled=False)
        self.assertTrue(all(field.isEnabled() for field in settings._local_factor_inputs))

    def test_language_change_does_not_build_hidden_views(self):
        window = self.dashboard()
        window.set_language("en")
        self.assertEqual(window._loaded_views, {})
        self.assertEqual(window.models_view.findChild(main.QLabel, "pageTitle").text(), i18n.t("Modelos", "en"))

    def test_project_mlflow_query_keeps_event_loop_responsive(self):
        entered, release = threading.Event(), threading.Event()
        def blocked_query(_name):
            entered.set()
            release.wait(3)
            return ["Resultado remoto"]
        window = self.dashboard()
        view = window.projects_view
        with patch.object(view, "_mlflow_run_items", side_effect=blocked_query):
            view.project_combo.addItem("Proyecto", 1)
            view._request_mlflow_runs("Proyecto")
            try:
                self.assertTrue(entered.wait(1))
                ticks = []
                QTimer.singleShot(0, lambda: ticks.append(True))
                self.wait_until(lambda: bool(ticks))
                self.assertTrue(view._mlflow_thread.isRunning())
            finally:
                release.set()
                self.wait_until(lambda: not view._mlflow_thread.isRunning())
                self.app.processEvents()
        self.assertEqual(view._mlflow_items_by_project["Proyecto"], ["Resultado remoto"])

    def test_close_waits_asynchronously_for_hardware_worker(self):
        release = threading.Event()
        window = self.dashboard()
        window.show()
        with patch.object(main, "get_hardware_info", side_effect=lambda: release.wait(3) or {}):
            view = window.hardware_view
            view._load_hardware()
            try:
                event = QCloseEvent()
                window.closeEvent(event)
                self.assertFalse(event.isAccepted())
                ticks = []
                QTimer.singleShot(0, lambda: ticks.append(True))
                self.wait_until(lambda: bool(ticks))
                self.assertTrue(window.isVisible())
            finally:
                release.set()
                self.wait_until(lambda: not window.isVisible())

    def test_active_chat_counts_as_running_simulation(self):
        window = self.dashboard()
        window.home_view._chat_window = SimpleNamespace(_worker=object(), _thread=SimpleNamespace(isRunning=lambda: True))
        self.assertTrue(window.is_simulation_running())
        window.home_view._chat_window = None

    def test_leaving_hardware_cancels_detection_that_has_not_started(self):
        window = self.dashboard()
        window.show()
        buttons = window.sidebar.button_group.buttons()
        buttons[6].click()
        view = window.hardware_view
        buttons[7].click()
        QTest.qWait(100)
        self.assertFalse(view._hardware_load_timer.isActive())
        main.get_hardware_info.assert_not_called()

    def test_local_login_handles_corrupt_database_without_losing_attempts(self):
        self.config["users"] = [{"username": "test"}]
        window = main.LoginWindow()
        self.windows.append(window)
        window.username_input.setText("test")
        with patch.object(main, "bootstrap_store", side_effect=sqlite3.DatabaseError("corrupt")):
            window.handle_login()
        self.assertIn("corrupt", window.error_label.text())
        self.assertEqual(window.failed_attempts, 0)

    def test_remote_login_accepts_full_https_url(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"user":{"username":"test"},"token":"token"}'
        window = main.LoginWindow()
        self.windows.append(window)
        window.connection_combo.setCurrentIndex(1)
        window.server_ip_input.setText("https://server.example:8443/")
        window.username_input.setText("test")
        with patch("urllib.request.urlopen", return_value=response) as request, patch.object(main, "DashboardWindow"):
            window.handle_login()
        self.assertEqual(request.call_args.args[0].full_url, "https://server.example:8443/login")

    def test_number_parser_preserves_signs_units_and_rejects_corruption(self):
        for value, expected in [("-5", -5), ("4,500 W", 4500), ("0.40 J", .4), ("~23.70", 23.7), ("16 GB", 16), ("1e3", 1000)]:
            with self.subTest(value=value):
                self.assertEqual(main.parse_number(value), expected)
        for value in ("1.2.3", "1,2", "", "nan", "inf", "1e999", None):
            with self.subTest(value=value):
                self.assertIsNone(main.parse_number(value))

    def test_shutdown_does_not_import_an_unused_integration(self):
        with patch.dict(sys.modules, {"mlflow_integration": None, "ollama_integration": None}):
            main._shutdown_mlflow_autostart()
            main._shutdown_ollama_autostart()
        main._background_stop_event.clear()

    def test_account_menu_actions_are_connected_or_explicitly_disabled(self):
        window = self.dashboard()
        unavailable = {"Dispositivos vinculados", "Verificacion en dos pasos", "Cerrar sesion en otros equipos"}
        for action in window.sidebar.user_menu.actions():
            if action.isSeparator():
                continue
            with self.subTest(action=action.text()):
                if action.isEnabled():
                    self.assertGreater(action.receivers(SIGNAL("triggered(bool)")), 0)
                if action.data() in unavailable:
                    self.assertFalse(action.isEnabled())
        action = next(action for action in window.sidebar.user_menu.actions() if action.data() == "Notificaciones")
        action.trigger()
        self.assertIs(window.stack.currentWidget().widget(), window.settings_view)

    def test_account_admin_actions_call_existing_implementations(self):
        window = self.dashboard()
        with patch.object(main.AdminMenuView, "manage_integrations") as manage:
            next(action for action in window.sidebar.user_menu.actions() if action.data() == "Integraciones").trigger()
        manage.assert_called_once()
        self.assertIs(window.stack.currentWidget().widget(), window._loaded_views["admin_view"])

    def test_profile_edit_updates_persistence_and_visible_name(self):
        self.config["users"] = [{"username": "test", "display_name": "Anterior"}]
        window = self.dashboard()
        with patch.object(main.QInputDialog, "getText", return_value=("Nombre nuevo", True)), patch.object(main, "save_users_to_config") as save:
            window._handle_account_action("Editar perfil")
        self.assertEqual(save.call_args.args[0][0]["display_name"], "Nombre nuevo")
        self.assertEqual(window.sidebar.findChild(main.QLabel, "userName").text(), "Nombre nuevo")

    def test_password_change_rolls_back_database_when_config_cannot_be_saved(self):
        old_password = "Anterior1@"
        self.config["users"] = [{"username": "test", "password_hash": core.hash_password(old_password)}]
        window = self.dashboard()
        with patch.object(main.QInputDialog, "getText", side_effect=[(old_password, True), ("NuevaClave2@", True), ("NuevaClave2@", True)]), patch.object(
            main, "save_users_to_config", side_effect=OSError("disk full")
        ), patch.object(QMessageBox, "warning") as warning:
            window._handle_account_action("Cambiar contrasena")
        warning.assert_called_once()
        store = core.LocalStore(self.root / "semaforo.sqlite3")
        try:
            self.assertIsNotNone(store.authenticate("test", old_password))
        finally:
            store.close()

    def test_password_change_persists_matching_hashes(self):
        old_password, new_password = "Anterior1@", "NuevaClave2@"
        self.config["users"] = [{"username": "test", "password_hash": core.hash_password(old_password)}]
        window = self.dashboard()
        with patch.object(main.QInputDialog, "getText", side_effect=[(old_password, True), (new_password, True), (new_password, True)]), patch.object(
            main, "save_users_to_config"
        ) as save, patch.object(QMessageBox, "information"):
            window._handle_account_action("Cambiar contrasena")
        store = core.LocalStore(self.root / "semaforo.sqlite3")
        try:
            self.assertIsNotNone(store.authenticate("test", new_password))
            stored_hash = store.connection.execute("SELECT password_hash FROM users WHERE username = 'test'").fetchone()[0]
            self.assertEqual(save.call_args.args[0][0]["password_hash"], stored_hash)
        finally:
            store.close()

    def test_failed_mlflow_upload_keeps_one_local_execution_and_responsive_ui(self):
        self.config["users"] = [{"username": "test", "password_hash": core.hash_password("PruebaClave1@"), "role": "Administrador"}]
        store = core.LocalStore(self.root / "semaforo.sqlite3")
        project_id = store.add_project("Proyecto de prueba")
        store.close()
        self.config["current_project_id"] = project_id
        window = self.dashboard()
        window.selection_state.update(provider="Local", region="Chile", model="Modelo", hardware="CPU", hardware_tdp=10)
        window.current_evaluation = {"cost": 1, "carbon": 10, "kwh": .1, "water": .1, "duration_ms": 100, "semaphore": "Verde"}
        entered, release = threading.Event(), threading.Event()
        def upload(**_data):
            entered.set()
            release.wait(3)
            raise ConnectionError("offline")
        with patch.object(window.home_view, "_log_execution_to_mlflow", side_effect=upload), patch.object(QMessageBox, "warning") as warning, patch.object(QMessageBox, "critical") as critical:
            window.home_view.register_execution_btn.click()
            try:
                self.assertTrue(entered.wait(1))
                window.home_view.register_execution_btn.click()
                ticks = []
                QTimer.singleShot(0, lambda: ticks.append(True))
                self.wait_until(lambda: bool(ticks))
                self.assertFalse(window.home_view.register_execution_btn.isEnabled())
            finally:
                release.set()
                self.wait_until(lambda: window.home_view.register_execution_btn.isEnabled())
            warning.assert_called_once()
            critical.assert_not_called()
        store = core.LocalStore(self.root / "semaforo.sqlite3")
        try:
            self.assertEqual(len(store.list_history(project_id=project_id)), 1)
        finally:
            store.close()


class DataAndReportRegressionTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows batch launcher")
    def test_windows_launcher_reuses_dependencies_and_preserves_app_exit_code(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            venv.EnvBuilder(with_pip=False).create(root / ".venv")
            site_packages = root / ".venv" / "Lib" / "site-packages"
            (site_packages / "test-dependencies.pth").write_text(sysconfig.get_path("purelib"), encoding="utf-8")
            for name in ("run_venv.bat", "check_dependencies.py", "requirements.txt"):
                shutil.copyfile(Path(__file__).with_name(name), root / name)
            (root / "main.py").write_text("print('APP_OPENED_WITHOUT_PIP')\nraise SystemExit(7)\n", encoding="utf-8")
            result = subprocess.run(["cmd.exe", "/d", "/c", str(root / "run_venv.bat")], cwd=root,
                                    capture_output=True, text=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
            self.assertIn("APP_OPENED_WITHOUT_PIP", result.stdout)
            self.assertNotIn("Installing", result.stdout)

    def test_entrypoint_paints_login_before_optional_services_start(self):
        source = '''
from unittest.mock import MagicMock, patch
import main
events = []
OriginalApp = main.QApplication
OriginalLogin = main.LoginWindow
class App(OriginalApp):
    def __init__(self, args):
        super().__init__(args)
        main.QTimer.singleShot(450, self.quit)
def service(name):
    events.append((name, any(isinstance(w, OriginalLogin) and w.isVisible() for w in OriginalApp.topLevelWidgets())))
lock = MagicMock()
lock.tryLock.return_value = True
with patch.object(main, 'QApplication', App), patch.object(main, 'QLockFile', return_value=lock), patch.object(main, '_bootstrap_mlflow_autostart', new=lambda: service('mlflow')), patch.object(main, '_bootstrap_ollama_autostart', new=lambda: service('ollama')), patch.object(main, 'install_global_exception_handler'):
    try:
        main.main()
    except SystemExit as exc:
        assert exc.code == 0
assert sorted(events) == [('mlflow', True), ('ollama', True)], events
lock.unlock.assert_called_once()
'''
        result = subprocess.run([sys.executable, "-c", source], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_dependency_check_checks_versions_and_environment_markers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "requirements.txt"
            path.write_text('requests>=2\nabsent==1\nignored; python_version < "2"\n', encoding="utf-8")
            def version(name):
                if name == "absent":
                    raise check_dependencies.metadata.PackageNotFoundError(name)
                return "1.0"
            with patch.object(check_dependencies.metadata, "version", side_effect=version):
                self.assertEqual(check_dependencies.missing_requirements(path), ["requests>=2", "absent==1"])

    def test_mlflow_service_discovery_import_does_not_load_the_sdk(self):
        result = subprocess.run([sys.executable, "-c", "import sys, mlflow_integration; assert 'mlflow' not in sys.modules"], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cancelled_service_start_does_not_spawn_a_process(self):
        import mlflow_integration
        import ollama_integration
        cancelled = threading.Event()
        cancelled.set()
        for module in (mlflow_integration, ollama_integration):
            with self.subTest(module=module.__name__), patch.object(module.subprocess, "Popen") as spawn:
                if module is mlflow_integration:
                    module.start_local_server_if_needed({}, cancel_event=cancelled)
                else:
                    module.start_local_server_if_needed(cancel_event=cancelled)
                spawn.assert_not_called()

    def test_unavailable_remote_ollama_never_starts_a_local_server(self):
        import ollama_integration
        with patch.object(ollama_integration, "is_reachable", return_value=False), patch.object(ollama_integration.subprocess, "Popen") as spawn:
            self.assertFalse(ollama_integration.start_local_server_if_needed("https://ollama.example"))
        spawn.assert_not_called()

    def test_mlflow_checks_the_actual_uri_host_before_starting_locally(self):
        import mlflow_integration
        self.assertTrue(mlflow_integration._is_local_uri("http://[::1]:5000"))
        self.assertFalse(mlflow_integration._is_local_uri("https://localhost.example.com"))

    def test_report_scripts_run_from_another_working_directory(self):
        root = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as directory:
            for report in ("eco", "economia", "inicio"):
                result = subprocess.run([sys.executable, str(root / "export handler" / f"{report}.py"), "--format", "json"],
                                        cwd=directory, capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(list(Path(directory).glob("*.json"))), 3)

    def test_non_finite_exchange_rates_and_amounts_are_rejected(self):
        rates = {currency: 1 for currency in core.SUPPORTED_CURRENCIES}
        for invalid in (float("nan"), float("inf"), -1, 0):
            with self.subTest(invalid=invalid):
                with self.assertRaises(core.DataIntegrityError):
                    core.fetch_exchange_rates_from_mapping({**rates, "USD": invalid})
                with self.assertRaises(core.ValidationError):
                    core.convert_clp(100, "USD", {"USD": invalid})
        for invalid in (float("nan"), float("inf"), -1):
            with self.assertRaises(core.ValidationError):
                core.convert_clp(invalid, "USD", rates)

    def test_invalid_config_and_translation_shapes_have_a_safe_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            for payload in ([], None, {"bad": 42, "key": {"es": [], "en": "Valid"}}):
                path.write_text(json.dumps(payload), encoding="utf-8")
                translator = i18n.Translator(path)
                self.assertEqual(translator.t("untranslated"), "untranslated")
                with patch.object(main, "writable_path", return_value=str(path)):
                    self.assertIsInstance(main.load_config(), dict)

    def test_hardware_detection_handles_a_non_object_powershell_response(self):
        import hardware_info
        with patch.object(hardware_info.sys, "platform", "win32"), patch.object(hardware_info, "_run_powershell", return_value="[]"):
            self.assertEqual(hardware_info._detect_hardware()["cpu"], "No detectado")

    def test_server_rejects_non_ascii_session_tokens_without_crashing(self):
        import server
        for token in ("á.signature", "abc.ñ", "not-a-token", None):
            with self.subTest(token=token):
                self.assertFalse(server.validate_session_token(token))

    def test_all_reports_and_formats_handle_zero_data_and_unicode(self):
        from export_handler import _apply_report_data
        with tempfile.TemporaryDirectory() as directory:
            for report in ("inicio", "economia", "eco", "proyecto"):
                for fmt in ("pdf", "json", "csv", "xlsx", "both"):
                    with self.subTest(report=report, format=fmt):
                        target = Path(directory) / f'{report}-{fmt}.{"pdf" if fmt == "both" else fmt}'
                        _apply_report_data(report, {
                            "exported_by": "José → prueba €",
                            "chart_values": [0, 0], "chart_labels": ["CPU", "GPU"],
                            "details": [["Proyecto", "Evaluación → GPU", "gray_800"]],
                        }, str(target), fmt, "es")
                        self.assertTrue(target.is_file())
                        if fmt in ("pdf", "both"):
                            self.assertTrue(target.read_bytes().startswith(b"%PDF"))
                        if fmt in ("json", "both"):
                            self.assertEqual(json.loads(target.with_suffix(".json").read_text(encoding="utf-8"))["exported_by"], "José → prueba €")

    def test_concurrent_reports_keep_each_users_data_separate(self):
        from export_handler import _apply_report_data
        with tempfile.TemporaryDirectory() as directory:
            def generate(index):
                target = Path(directory) / f"report-{index}.json"
                _apply_report_data("inicio", {"exported_by": f"user-{index}"}, str(target), "json", "es")
                return json.loads(target.read_text(encoding="utf-8"))["exported_by"]
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                self.assertEqual(list(executor.map(generate, range(8))), [f"user-{index}" for index in range(8)])


if __name__ == "__main__":
    unittest.main()
