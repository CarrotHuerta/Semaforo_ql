import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton, QSizePolicy

import main as main_module
from main import AdminMenuView, CarbonDetailView, FinOpsView, HardwareCatalogView, HomeView, LoginWindow, ProjectsView, ResponsivePageScrollArea, ResponsiveStackedWidget, SettingsView


class FakeMainWindow:
    current_semaphore_level = "Amarillo"

    @staticmethod
    def get_active_project_metrics():
        return {
            "project_name": "TEST", "count": 3, "cost": 0.0,
            "kwh": 0.0012, "carbon": 0.3,
        }


class UiFunctionalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_alert_starts_hidden_and_snooze_restores(self):
        view = HomeView(main_window=FakeMainWindow())
        view.show()
        self.assertFalse(view.alert_bar.isVisible())
        view.set_semaforo_level("moderado", 70.0, 80.0)
        self.assertTrue(view.alert_bar.isVisible())
        view._snooze_alert()
        self.assertFalse(view.alert_bar.isVisible())
        view._restore_alert()
        self.assertTrue(view.alert_bar.isVisible())
        view.deleteLater()

    def test_component_breakdown_recalculates_visible_values(self):
        view = HardwareCatalogView()
        view._handle_assign({"Tipo_Componente": "CPU", "TDP_Max_Watts": "100", "Modelo": "CPU"})
        view._handle_assign({"Tipo_Componente": "GPU", "TDP_Max_Watts": "300", "Modelo": "GPU"})
        self.assertEqual(view.breakdown_bars["CPU"].value(), 25)
        self.assertEqual(view.breakdown_bars["GPU"].value(), 75)
        view.breakdown_checks["GPU"].setChecked(False)
        self.assertEqual(view.breakdown_bars["CPU"].value(), 100)
        self.assertEqual(view.breakdown_bars["GPU"].value(), 0)
        view.deleteLater()

    def test_finops_cards_remain_compact(self):
        with patch.object(FinOpsView, "_refresh_exchange_rates"):
            view = FinOpsView(main_window=FakeMainWindow())
        for card in (view.card_actual, view.card_presupuesto, view.card_ahorro):
            self.assertLessEqual(card.maximumHeight(), 158)
            self.assertEqual(card.sizePolicy().verticalPolicy(), QSizePolicy.Fixed)
        self.assertEqual(view.project_summary_panel.objectName(), "finopsSummaryPanel")
        self.assertEqual(view.budget_bar.height(), 18)
        self.assertTrue(hasattr(view, "circuit_status_label"))
        view.deleteLater()

    def test_finops_shows_circuit_breaker_reason(self):
        class FakeStore:
            def list_models(self, project_id):
                return [{"id": 7}]

            def circuit_breaker_status(self, model_id):
                return {"allowed": False, "reasons": ["Se superaria la cuota financiera."]}

            def close(self):
                pass

        with patch.object(FinOpsView, "_refresh_exchange_rates"), patch.object(
            main_module, "load_config", return_value={"current_project_id": 3}
        ), patch.object(main_module, "bootstrap_store", return_value=FakeStore()):
            view = FinOpsView(main_window=FakeMainWindow())
        self.assertIn("cuota financiera", view.circuit_status_label.text().lower())
        view.deleteLater()

    def test_carbon_shifting_requires_24_factors(self):
        view = CarbonDetailView()
        view.shifting_input.setText("0.5, 0.4")
        view.shifting_result.setText("")
        view.shifting_button.click()
        self.assertIn("24", view.shifting_result.text())
        view.deleteLater()

    def test_software_efficiency_panel_reports_normal_usage(self):
        view = CarbonDetailView()
        view.efficiency_button.click()
        self.assertIn("No se detectaron", view.efficiency_result.text())
        view.deleteLater()

    def test_home_cards_are_compact_and_settings_scroll(self):
        home = HomeView(main_window=FakeMainWindow())
        for card in home.status_cards.values():
            self.assertLessEqual(card.maximumHeight(), 190)
            self.assertEqual(card.sizePolicy().verticalPolicy(), QSizePolicy.Fixed)
        home.deleteLater()

        settings = SettingsView()
        settings.resize(1024, 420)
        settings.show()
        self.app.processEvents()
        self.assertGreater(settings.settings_scroll.verticalScrollBar().maximum(), 0)
        settings.deleteLater()

    def test_admin_is_responsive_and_stack_does_not_force_large_window(self):
        stack = ResponsiveStackedWidget()
        self.assertEqual((stack.minimumSizeHint().width(), stack.minimumSizeHint().height()), (600, 420))
        stack.deleteLater()

        comparison_scroll = ResponsivePageScrollArea(CarbonDetailView())
        comparison_scroll.resize(800, 420)
        comparison_scroll.show()
        self.app.processEvents()
        self.assertGreater(comparison_scroll.verticalScrollBar().maximum(), 0)
        comparison_scroll.deleteLater()

        admin = AdminMenuView({"display_name": "Nacha", "role": "Administrador", "username": "nacha"})
        admin.resize(800, 480)
        admin.show()
        self.app.processEvents()
        self.assertGreater(admin.admin_scroll.verticalScrollBar().maximum(), 0)
        admin_buttons = {
            button.text(): button for button in admin.findChildren(QPushButton)
        }
        for label in (
            "Resetear contrasena", "Editar roles", "Roles y permisos", "Grupos",
            "Accesos temporales", "Registro de Actividad", "Alertas",
            "Backup y restauracion", "Integraciones", "Parametros globales",
        ):
            self.assertIn(label, admin_buttons)
            self.assertTrue(admin_buttons[label].isEnabled(), label)
        admin.deleteLater()

    def test_hardware_toolbar_keeps_button_labels_visible(self):
        view = HardwareCatalogView()
        page_scroll = ResponsivePageScrollArea(view)
        page_scroll.resize(800, 600)
        page_scroll.show()
        self.app.processEvents()
        buttons = (
            view.autoselect_btn, view.rightsize_btn, view.add_hardware_btn,
            view.edit_hardware_btn, view.delete_hardware_btn,
            view.refresh_catalog_btn, view.template_btn,
        )
        self.assertTrue(all(button.width() >= button.sizeHint().width() for button in buttons))
        page_scroll.deleteLater()

    def test_models_view_pagination_controls(self):
        from main import ModelsView

        view = ModelsView()
        total = len(view.models_data)
        if total == 0:
            self.assertTrue(view.table_empty_label.isVisibleTo(view))
        else:
            expected_pages = max(1, -(-total // view.page_size))
            self.assertIn(f"{expected_pages}", view.page_label.text())
            self.assertFalse(view.prev_page_btn.isEnabled())
            if expected_pages > 1:
                self.assertTrue(view.next_page_btn.isEnabled())
                view.next_page_btn.click()
                self.assertEqual(view.current_page, 2)
                self.assertTrue(view.prev_page_btn.isEnabled())
                view.prev_page_btn.click()
                self.assertEqual(view.current_page, 1)
        view.deleteLater()

    def test_cloud_view_low_carbon_filter_and_lock_signal(self):
        from main import CloudView

        events = []

        def capture(**kwargs):
            events.append(kwargs)

        view = CloudView(on_selection=capture)
        self.assertFalse(view.cloud_mode_checkbox.isChecked())
        view.cloud_mode_checkbox.setChecked(True)
        self.assertTrue(any(event.get("cloud_enabled") for event in events))
        view.renewable_checkbox.setChecked(True)
        remaining = [view.region_combo.itemText(i) for i in range(view.region_combo.count())]
        for region in remaining:
            intensity = view.region_intensity_map.get(region)
            if intensity is not None:
                self.assertLess(intensity, 100)
        view.deleteLater()

    def test_finops_budget_can_be_saved_and_validated(self):
        import json as json_module
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text("{}", encoding="utf-8")
            saved = {}

            def fake_writable(*parts):
                return str(Path(directory, *parts))

            with patch.object(FinOpsView, "_refresh_exchange_rates"), patch.object(
                main_module, "writable_path", side_effect=fake_writable
            ):
                view = FinOpsView(main_window=FakeMainWindow())
                # invalido: negativo -> feedback y sin persistencia
                view.budget_input.setText("-5")
                view._save_budget()
                self.assertIn("positivo", view.budget_feedback_label.text())
                self.assertNotIn("budget_usd", json_module.loads(config_path.read_text(encoding="utf-8")))
                # valido: persiste y refresca la tarjeta
                view.budget_input.setText("250.5")
                view._save_budget()
                saved = json_module.loads(config_path.read_text(encoding="utf-8"))
                self.assertEqual(saved.get("budget_usd"), 250.5)
                # vacio: elimina el limite
                view.budget_input.setText("")
                view._save_budget()
                saved = json_module.loads(config_path.read_text(encoding="utf-8"))
                self.assertNotIn("budget_usd", saved)
                view.deleteLater()

    def test_settings_local_factors_lock_and_energy_source(self):
        settings = SettingsView()
        settings.set_local_factors_locked(True)
        for widget in settings._local_factor_inputs:
            self.assertFalse(widget.isEnabled())
        self.assertTrue(settings.local_lock_label.isVisibleTo(settings))
        settings.set_local_factors_locked(False)
        for widget in settings._local_factor_inputs:
            self.assertTrue(widget.isEnabled())
        self.assertIn("Fuente Primaria Operante", settings.energy_source_label.text())
        settings.deleteLater()

    def test_projects_defers_mlflow_during_dashboard_construction(self):
        with patch.object(ProjectsView, "_mlflow_run_items") as load_mlflow:
            view = ProjectsView(profile={"username": "nacha", "role": "Administrador"})
        load_mlflow.assert_not_called()
        view.deleteLater()

    def test_remote_login_uses_a_bounded_network_timeout(self):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = (
            b'{"user":{"username":"nacha","role":"Administrador"},"token":"token"}'
        )
        with patch("urllib.request.urlopen", return_value=response) as urlopen, patch.object(
            main_module, "DashboardWindow"
        ):
            window = LoginWindow()
            window.connection_combo.setCurrentIndex(1)
            window.username_input.setText("nacha")
            window.password_input.setText("ClaveSegura1@")
            window.handle_login()
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 5)
        window.deleteLater()


if __name__ == "__main__":
    unittest.main()
