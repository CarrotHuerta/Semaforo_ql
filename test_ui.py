import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QPushButton, QSizePolicy

import main as main_module
from main import AdminMenuView, BudgetAlertsDialog, CarbonDetailView, DashboardWindow, EnvironmentalPerformanceView, FinOpsView, HardwareCatalogView, HeadlessExportDialog, HistoryView, HomeView, LoginWindow, ModelsView, ProjectsView, ResponsivePageScrollArea, ResponsiveStackedWidget, SettingsView
from functional_core import Execution, LocalStore


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

    def test_metric_units_scale_with_values(self):
        self.assertEqual(main_module.format_duration_value(250), "250 ms")
        self.assertEqual(main_module.format_energy_value(0.999), "999.00 Wh")
        self.assertEqual(main_module.format_energy_value(1), "1.00 kWh")
        self.assertEqual(main_module.format_carbon(999), "999.00 gCO2eq")
        self.assertEqual(main_module.format_carbon(16_176), "16.18 kgCO2eq")
        self.assertEqual(main_module.format_duration_value(59_000), "59.00 s")
        self.assertEqual(main_module.format_duration_value(60_000), "1.00 min")
        self.assertEqual(main_module.format_duration_value(195_120_000), "54.20 h")

    def test_guided_error_diagnostic_fallback_writes_plain_text(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = main_module.save_diagnostic_fallback("code: ERR_IO\ndetail: disk", directory)
            self.assertTrue(destination.endswith(".txt"))
            with open(destination, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "code: ERR_IO\ndetail: disk")

    def test_diagnostic_report_copies_large_metadata_to_clipboard(self):
        class Clipboard:
            text = None

            def setText(self, value):
                self.text = value

        detail = "trace-line\n" * 5000
        report = main_module.build_diagnostic_report({
            "code": "ERR_IO", "cause": "Disk unavailable",
            "action": "Verify permissions", "detail": detail,
        })
        clipboard = Clipboard()
        result = main_module.deliver_diagnostic_report(report, clipboard=clipboard)
        self.assertEqual(result, {"channel": "clipboard", "path": None})
        self.assertEqual(clipboard.text, report)
        self.assertIn("incident_id:", report)
        self.assertIn("timestamp_utc:", report)
        self.assertIn("platform:", report)
        self.assertGreater(len(report), 50_000)

    def test_diagnostic_report_falls_back_to_complete_text_file(self):
        class BlockedClipboard:
            def setText(self, _value):
                raise RuntimeError("clipboard denied")

        with tempfile.TemporaryDirectory() as directory:
            report = main_module.build_diagnostic_report({
                "code": "ERR_DB", "detail": "database trace\n" * 1000,
            })
            result = main_module.deliver_diagnostic_report(
                report, clipboard=BlockedClipboard(), fallback_directory=directory,
            )
            self.assertEqual(result["channel"], "file")
            self.assertTrue(result["path"].endswith(".txt"))
            with open(result["path"], encoding="utf-8") as handle:
                self.assertEqual(handle.read(), report)

    def test_global_exception_policy_guides_io_and_delegates_fatal_errors(self):
        guided = []
        delegated = []
        io_error = OSError("disk unavailable")
        result = main_module.handle_uncaught_exception(
            OSError, io_error, io_error.__traceback__,
            native_hook=lambda *args: delegated.append(args),
            dialog_handler=lambda parent, code, detail: guided.append((code, detail)),
        )
        self.assertEqual(result, "guided")
        self.assertEqual(guided[0][0], "ERR_IO")
        self.assertIn("disk unavailable", guided[0][1])
        fatal = MemoryError("critical memory failure")
        result = main_module.handle_uncaught_exception(
            MemoryError, fatal, fatal.__traceback__,
            native_hook=lambda *args: delegated.append(args),
            dialog_handler=lambda *args: guided.append(args),
        )
        self.assertEqual(result, "delegated")
        self.assertEqual(delegated[0][0], MemoryError)

    def test_budget_alert_center_classifies_thresholds(self):
        rows = [
            {"timestamp": "2026-09-13 10:00:00", "action": "quota_threshold_crossed", "details": "Tu proyecto cruzó 50% del presupuesto financiero.", "project_name": "Proyecto A"},
            {"timestamp": "2026-09-13 11:00:00", "action": "quota_threshold_crossed", "details": "Tu proyecto cruzó 75% del presupuesto ambiental.", "project_name": "Proyecto A"},
        ]
        dialog = BudgetAlertsDialog(rows)
        self.assertEqual(dialog.alerts_table.rowCount(), 2)
        self.assertEqual(dialog.alerts_table.item(0, 0).text(), "PREVENTIVA")
        self.assertEqual(dialog.alerts_table.item(1, 0).text(), "ALTA")
        self.assertEqual(dialog.alerts_table.item(1, 3).text(), "75%")
        self.assertIn("proyección mensual", dialog.alerts_table.item(1, 4).text())
        self.assertNotIn("Tu proyecto", dialog.alerts_table.item(1, 4).text())
        dialog.deleteLater()

    def test_headless_export_dialog_generates_command_and_pure_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            database = os.path.join(directory, "headless.sqlite3")
            output = os.path.join(directory, "project.csv")
            store = LocalStore(database)
            project = store.add_project("Proyecto automatizado")
            model = store.add_model(project, "Modelo CLI")
            store.add_execution(Execution(model, "2026-09-13 12:00:00", 2, 3, 4, 5, 6, "Verde"))
            store.close()

            dialog = HeadlessExportDialog(project, "Proyecto automatizado", database)
            dialog.output_input.setText(output)
            self.assertIn("cli.py", dialog.command_input.text())
            self.assertIn(f"--project-id {project}", dialog.command_input.text())
            dialog.run_export()
            with open(output, encoding="utf-8", newline="") as handle:
                rows = list(__import__("csv").DictReader(handle))
            self.assertEqual(rows[0]["model_name"], "Modelo CLI")
            self.assertIn("1 registros", dialog.status_label.text())
            dialog.deleteLater()

            with patch.object(main_module.sys, "frozen", True, create=True), patch.object(
                main_module.sys, "executable", os.path.join(directory, "SemaforoIA.exe")
            ):
                packaged_command = main_module.build_headless_export_command(database, project, output)
            self.assertIn("SemaforoCLI.exe", packaged_command)
            self.assertNotIn("cli.py", packaged_command)

    def test_projects_view_reassigns_model_and_shows_consolidated_result(self):
        with tempfile.TemporaryDirectory() as directory:
            database = os.path.join(directory, "projects.sqlite3")
            store = LocalStore(database)
            source = store.add_project("Origen")
            target = store.add_project("Destino")
            model = store.add_model(source, "Modelo móvil")
            store.add_execution(Execution(model, "2026-09-13 12:00:00", 10, 20, 1, 2, 3, "Verde"))
            store.close()

            with patch.object(main_module, "load_config", return_value={"current_project_id": source}), patch.object(
                main_module, "save_current_project_id"
            ), patch.object(ProjectsView, "_open_store", side_effect=lambda: LocalStore(database)):
                view = ProjectsView(profile={"username": "admin", "role": "Administrador"})
                view.project_combo.setCurrentIndex(view.project_combo.findData(source))
                view.reassignment_model_combo.setCurrentIndex(0)
                view.reassignment_target_combo.setCurrentIndex(view.reassignment_target_combo.findData(target))
                view._reassign_selected_model()
                self.assertIn("Transferencia completada", view.reassignment_result_label.text())
                self.assertIn("10.00 → 0.00 USD", view.reassignment_result_label.text())
                view.deleteLater()

            store = LocalStore(database)
            self.assertEqual(store.project_totals(source)["cost"], 0)
            self.assertEqual(store.project_totals(target)["cost"], 10)
            store.close()

    def test_projects_capacity_forecast_and_safe_invalidation(self):
        with tempfile.TemporaryDirectory() as directory:
            database = os.path.join(directory, "capacity.sqlite3")
            store = LocalStore(database)
            project = store.add_project("Capacidad")
            model = store.add_model(project, "Modelo histórico")
            orphan = store.add_model(project, "Modelo nuevo")
            for index, duration in enumerate((1000, 1200, 1400), start=1):
                store.add_execution(Execution(model, f"2026-09-1{index} 12:00:00", 1, 1, 1, 1, duration, "Verde"))
            store.close()

            class Controller:
                running = False

                def is_simulation_running(self):
                    return self.running

            controller = Controller()
            with patch.object(main_module, "load_config", return_value={"current_project_id": project}), patch.object(
                main_module, "save_current_project_id"
            ), patch.object(ProjectsView, "_open_store", side_effect=lambda: LocalStore(database)):
                view = ProjectsView(profile={"role": "Administrador"}, main_window=controller)
                view.capacity_model_combo.setCurrentIndex(view.capacity_model_combo.findData(model))
                view._calculate_capacity_forecast()
                self.assertIn("Duración estimada", view.capacity_forecast_label.text())
                previous = view.capacity_forecast_label.text()
                controller.running = True
                view._invalidate_capacity_forecast()
                self.assertIn("Invalidación rechazada", view.capacity_forecast_label.text())
                self.assertIn(model, view._capacity_forecast_cache)
                controller.running = False
                view.capacity_model_combo.setCurrentIndex(view.capacity_model_combo.findData(orphan))
                view._calculate_capacity_forecast()
                self.assertIn("3 sesiones", view.capacity_forecast_label.text())
                self.assertNotEqual(previous, view.capacity_forecast_label.text())
                view.deleteLater()

    def test_settings_adds_experimental_emission_factor(self):
        with tempfile.TemporaryDirectory() as directory:
            def temporary_writable(*parts):
                return os.path.join(directory, *parts)

            with patch.object(main_module, "writable_path", side_effect=temporary_writable), patch.object(
                main_module, "load_config", return_value={}
            ):
                settings = SettingsView()
                settings.emission_factor_name_input.setText("Gas Sintético")
                settings.emission_factor_value_input.setText("123.45")
                settings._add_emission_factor()
                names = [
                    settings.emission_factor_table.item(row, 0).text()
                    for row in range(settings.emission_factor_table.rowCount())
                ]
                self.assertIn("Gas Sintético", names)
                self.assertIn("Factor experimental guardado", settings.emission_factor_status_label.text())
                settings.emission_factor_table.selectRow(names.index("Gas Sintético"))
                settings._apply_selected_emission_factor()
                with open(os.path.join(directory, "config.json"), encoding="utf-8") as handle:
                    saved_config = json.load(handle)
                self.assertEqual(saved_config["local_metrics"]["grid_factor"], 123.45)
                self.assertEqual(saved_config["local_metrics"]["grid_factor_name"], "Gas Sintético")
                self.assertIn("Factor activo", settings.emission_factor_status_label.text())
                settings.deleteLater()

    def test_environmental_view_scales_demo1_units(self):
        class DemoMainWindow:
            @staticmethod
            def get_active_project_metrics():
                return {
                    "project_name": "demo1", "count": 48, "cost": 26.93,
                    "kwh": 128.22, "carbon": 16_176, "duration_ms": 195_120_000,
                    "latest_timestamp": "2026-09-13 16:14:36", "carbon_limit": 16_176,
                }

        view = EnvironmentalPerformanceView(main_window=DemoMainWindow())
        self.assertEqual(view.emisiones_ejecucion_card.get_value(), "16.18 kgCO2eq")
        self.assertEqual(view.consumo_energetico_card.get_value(), "128.22 kWh")
        self.assertEqual(view.tiempo_proceso_card.get_value(), "54.20 h")
        self.assertEqual(view.eco_bar.value(), 100)
        self.assertEqual(view.eco_status_label.text(), "Límite ecológico excedido")
        view.deleteLater()

    def test_environmental_export_rejects_corrupt_metric(self):
        class MetricsMainWindow:
            current_evaluation = {}

            @staticmethod
            def get_active_project_metrics():
                return {
                    "project_name": "corrupto", "count": 1, "cost": 1,
                    "kwh": 1, "carbon": 1, "water": 1, "duration_ms": 1_000,
                    "latest_timestamp": "2026-09-13 20:00:00", "carbon_limit": 10,
                }

        view = EnvironmentalPerformanceView(main_window=MetricsMainWindow())
        view.emisiones_ejecucion_card.findChild(main_module.QLabel, "performanceValue").setText("dato corrupto")
        with patch.object(main_module, "show_guided_error") as guided, patch(
            "export_handler.generate_and_save_report"
        ) as generate:
            view.export_eco_report("csv")
        guided.assert_called_once()
        self.assertEqual(guided.call_args.args[1], "ERR_DATA")
        generate.assert_not_called()
        view.deleteLater()

    def test_ecological_limit_is_exceeded_from_ninety_percent(self):
        class MetricsMainWindow:
            carbon = 89

            def get_active_project_metrics(self):
                return {
                    "project_name": "umbral", "count": 2, "cost": 0,
                    "kwh": 1, "carbon": self.carbon, "duration_ms": 1_000,
                    "latest_timestamp": "2026-09-13 20:00:00", "carbon_limit": 100,
                }

        main_window = MetricsMainWindow()
        view = EnvironmentalPerformanceView(main_window=main_window)
        self.assertEqual(view.eco_status_label.text(), "Límite ecológico en advertencia")

        main_window.carbon = 90
        view.refresh_project_data()
        self.assertEqual(view.eco_bar.value(), 90)
        self.assertEqual(view.eco_status_label.text(), "Límite ecológico excedido")
        view.deleteLater()

    def test_ecological_limit_is_hidden_without_a_quota(self):
        class MetricsMainWindow:
            @staticmethod
            def get_active_project_metrics():
                return {
                    "project_name": "sin limite", "count": 1, "cost": 0,
                    "kwh": 1, "carbon": 400, "duration_ms": 1_000,
                    "latest_timestamp": "2026-09-13 20:00:00", "carbon_limit": None,
                }

        view = EnvironmentalPerformanceView(main_window=MetricsMainWindow())
        self.assertTrue(view.eco_panel.isHidden())
        view.deleteLater()

    def test_alert_starts_hidden_and_snooze_restores(self):
        view = HomeView(main_window=FakeMainWindow())
        view.show()
        self.assertFalse(view.alert_bar.isVisible())
        view.set_semaforo_level("moderado", 70.0, 80.0)
        self.assertTrue(view.alert_bar.isVisible())
        view._snooze_alert()
        self.assertFalse(view.alert_bar.isVisible())
        self.assertTrue(view.alert_snooze_indicator.isVisible())
        self.assertIn("#f59e0b", view.alert_snooze_indicator.styleSheet())
        view.set_semaforo_level("alto", 90.0, 20.0)
        self.assertFalse(view.alert_bar.isVisible())
        self.assertTrue(view.alert_snooze_indicator.isVisible())
        self.assertIn("#ef4444", view.alert_snooze_indicator.styleSheet())
        view._restore_alert()
        self.assertTrue(view.alert_bar.isVisible())
        self.assertFalse(view.alert_snooze_indicator.isVisible())
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
        for check in view.breakdown_checks.values():
            check.setChecked(False)
        self.assertTrue(all(check.isChecked() for check in view.breakdown_checks.values()))
        view.deleteLater()

    def test_hardware_autoselect_handles_missing_tdp_in_one_batch(self):
        assignments = []
        view = HardwareCatalogView(on_assign=lambda **values: assignments.append(values))
        gpu = {"Tipo_Componente": "GPU", "Fabricante": "GPU", "Modelo": "Detected", "TDP_Max_Watts": "300"}
        ram = {"Tipo_Componente": "RAM", "Fabricante": "RAM", "Modelo": "Memory", "Capacidad_GB": "32", "TDP_Max_Watts": ""}
        view.hardware_rows = [gpu, ram]
        view.detected_info = {"gpu": "GPU Detected", "ram": "32 GB"}

        view._auto_select_detected()

        self.assertIs(view.selected_by_type["GPU"], gpu)
        self.assertIs(view.selected_by_type["RAM"], ram)
        self.assertEqual(view.breakdown_bars["GPU"].value(), 100)
        self.assertEqual(view.breakdown_bars["RAM"].value(), 0)
        self.assertEqual(len(assignments), 1)
        self.assertEqual(assignments[0]["hardware_tdp"], 300)
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
        self.assertEqual(len(view.component_cost_panel.value_labels), len(view.finops_services))
        view.deleteLater()

    def test_finops_component_costs_use_selected_currency(self):
        with patch.object(FinOpsView, "_refresh_exchange_rates"):
            view = FinOpsView(main_window=FakeMainWindow())
        view.base_cost_actual_usd = 100
        view.exchange_rates = {"CLP": 1.0, "USD": 0.001, "EUR": 0.0009}
        view.currency_combo.setCurrentText("EUR - Euro (€)")
        values = [label.text() for label in view.component_cost_panel.value_labels]
        self.assertEqual(values[0], "€ 43.20 (48%)")
        self.assertIn("EUR", view.exchange_rate_label.text())
        view.deleteLater()

    def test_finops_export_rejects_unavailable_currency(self):
        with patch.object(FinOpsView, "_refresh_exchange_rates"):
            view = FinOpsView(main_window=FakeMainWindow())
        view.exchange_rates = {"CLP": 1.0}
        with patch.object(QMessageBox, "warning") as warning, patch(
            "export_handler.generate_and_save_report"
        ) as generate:
            view.export_finops_report("csv")
        warning.assert_called_once()
        self.assertIn("Seleccione otra moneda", warning.call_args.args[2])
        generate.assert_not_called()
        view.deleteLater()

    def test_environmental_history_has_explicit_empty_state(self):
        class EmptyStore:
            def list_history(self):
                return []

            def close(self):
                pass

        with patch.object(main_module, "bootstrap_store", return_value=EmptyStore()):
            view = HistoryView()
        labels = [label.text() for label in view.audit_list_panel.findChildren(main_module.QLabel)]
        self.assertTrue(any("No hay auditorías ambientales" in text for text in labels))
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

    def test_finops_budget_forecast_displays_date_with_enough_history(self):
        now = datetime.now(timezone.utc)

        class FakeStore:
            def list_history(self, project_id):
                return [
                    {"timestamp": (now - timedelta(days=10)).isoformat(), "cost": 20},
                    {"timestamp": (now - timedelta(days=5)).isoformat(), "cost": 20},
                ]

            def list_models(self, project_id):
                return [{"id": 7}]

            def circuit_breaker_status(self, model_id):
                return {"allowed": True, "reasons": []}

            def close(self):
                pass

        config = {"current_project_id": 3, "budget_usd": 100}
        with patch.object(FinOpsView, "_refresh_exchange_rates"), patch.object(
            main_module, "load_config", return_value=config
        ), patch.object(main_module, "bootstrap_store", side_effect=lambda *args: FakeStore()):
            view = FinOpsView(main_window=FakeMainWindow())

        self.assertIn("Fondo estimado a agotarse en", view.budget_forecast_label.text())
        self.assertNotIn("insuficientes", view.budget_forecast_label.text())
        self.assertRegex(view.budget_forecast_label.text(), r"\d{4}-\d{2}-\d{2}")
        view.deleteLater()

    def test_finops_budget_forecast_omits_unsafe_extrapolation(self):
        class FakeStore:
            def list_history(self, project_id):
                return [{"timestamp": "2026-09-01T00:00:00+00:00", "cost": 20}]

            def list_models(self, project_id):
                return [{"id": 7}]

            def circuit_breaker_status(self, model_id):
                return {"allowed": True, "reasons": []}

            def close(self):
                pass

        config = {"current_project_id": 3, "budget_usd": 100}
        with patch.object(FinOpsView, "_refresh_exchange_rates"), patch.object(
            main_module, "load_config", return_value=config
        ), patch.object(main_module, "bootstrap_store", side_effect=lambda *args: FakeStore()):
            view = FinOpsView(main_window=FakeMainWindow())

        self.assertIn("Sin datos históricos suficientes", view.budget_forecast_label.text())
        view.deleteLater()

    def test_carbon_shifting_requires_24_factors(self):
        view = CarbonDetailView()
        view.shifting_input.setText("0.5, 0.4")
        view.shifting_result.setText("")
        view.shifting_button.click()
        self.assertIn("24", view.shifting_result.text())
        view.deleteLater()

    def test_carbon_shifting_shows_savings_and_hides_flat_comparison(self):
        view = CarbonDetailView()
        current_hour = datetime.now(timezone.utc).hour
        factors = [10.0] * 24
        factors[(current_hour + 1) % 24] = 4.0
        view.shifting_input.setText(",".join(str(value) for value in factors))
        view.shifting_button.click()
        self.assertIn("Ahorro estimado", view.shifting_result.text())
        self.assertFalse(view.shifting_comparison.isHidden())
        view.shifting_input.setText(",".join(["5"] * 24))
        view.shifting_button.click()
        self.assertIn("Matriz estable", view.shifting_result.text())
        self.assertTrue(view.shifting_comparison.isHidden())
        view.deleteLater()

    def test_markdown_editor_blocks_overflow_and_renders_saved_text(self):
        rows = [{"Nombre_Modelo": "Demo", "Consumo_Energetico_Base": "10"}]
        with tempfile.TemporaryDirectory() as directory, patch.object(
            main_module, "load_model_records", return_value=rows,
        ), patch.object(main_module, "writable_path", side_effect=lambda name: os.path.join(directory, name)):
            view = ModelsView()
            view.description_editor.setPlainText("x" * 5001)
            self.assertFalse(view.save_description_button.isEnabled())
            view.description_editor.setPlainText("# Título\n\n- **GPU**")
            with patch.object(QMessageBox, "information"):
                view._save_model_description()
            self.assertEqual(view.description_view.toPlainText(), "Título\nGPU")
            with open(os.path.join(directory, "models.json"), encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)[0]["description_markdown"], "# Título\n\n- **GPU**")
            view.deleteLater()

    def test_recommendation_manual_has_corruption_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "rules.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{bad")
            rules, fallback = main_module.load_recommendation_rules(path)
        self.assertTrue(fallback)
        self.assertIn("documentación técnica externa", rules["moderate"]["recommendations"][0])

    def test_yellow_recommendation_uses_local_rule_catalog(self):
        rules, fallback = main_module.load_recommendation_rules()
        self.assertFalse(fallback)
        self.assertGreaterEqual(len(rules["moderate"]["recommendations"]), 3)

    def test_efficiency_finding_opens_local_manual(self):
        view = CarbonDetailView()
        view.efficiency_runtime_input.setText("130000")
        view.efficiency_cpu_input.setText("35")
        view.efficiency_memory_input.setText("60")
        view.efficiency_batch_input.setText("8")
        view.efficiency_button.click()
        self.assertTrue(view.efficiency_manual_button.isEnabled())
        view.efficiency_manual_button.click()
        self.assertIn("CPU", view.efficiency_manual_view.toPlainText())
        view.deleteLater()

    def test_sparse_history_uses_textual_fallback(self):
        chart = main_module.TimeSeriesChart([{"cost": 1, "carbon": 2}])
        self.assertIn("insuficientes", chart.fallback_message)
        chart.deleteLater()

    def test_snmp_telemetry_passes_protected_community(self):
        readings = []

        class FakeClient:
            def __init__(self, host, identifier, community):
                self.values = (host, identifier, community)

            def read_watts(self):
                self_outer.assertEqual(self.values, ("sensor.local", "1.2.3", "private"))
                return 42.0

        self_outer = self
        with patch.object(main_module, "SnmpTelemetryClient", FakeClient):
            thread = main_module.TelemetryThread("SNMP", "sensor.local", "1.2.3", "private")
            thread.completed.connect(readings.append)
            thread.run()
        self.assertEqual(readings, [42.0])

    def test_circuit_breaker_notification_failure_is_audited(self):
        class FakeStore:
            def __init__(self):
                self.connection = self
                self.actions = []

            def _audit(self, actor, action, project_id, details):
                self.actions.append((actor, action, project_id, details))

            def commit(self):
                pass

        store = FakeStore()
        with patch.object(main_module, "show_guided_error", side_effect=RuntimeError("UI caída")), patch.object(
            QApplication, "beep"
        ) as beep:
            reported = main_module.report_circuit_breaker(None, store, 7, "admin", "ERR_QUOTA_FIN", "agotado")
        self.assertFalse(reported)
        beep.assert_called_once()
        self.assertEqual(store.actions[0][1], "circuit_notification_failed")

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

    def test_template_propagation_requires_consent_only_with_dependencies(self):
        view = HardwareCatalogView()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.No) as question:
            self.assertFalse(view._confirm_template_propagation(["Proyecto A", "Proyecto B"]))
            self.assertIn("2 proyecto", question.call_args.args[2])
            self.assertIn("Proyecto A", question.call_args.args[2])

        with patch.object(QMessageBox, "question") as question:
            self.assertTrue(view._confirm_template_propagation([]))
            question.assert_not_called()
        view.deleteLater()

    def test_missing_hardware_master_uses_visible_zero_value_fallback(self):
        with patch.object(main_module, "load_csv_rows", return_value=[]):
            view = HardwareCatalogView()

        fallback = [row for row in view.hardware_rows if row.get("_fallback")]
        self.assertEqual(len(fallback), 3)
        self.assertTrue(all(row["TDP_Max_Watts"] == "0" for row in fallback))
        self.assertIn("ALERTA", view.catalog_contingency_label.text())
        self.assertFalse(view.catalog_contingency_label.isHidden())
        view.deleteLater()

    def test_hardware_master_memory_error_is_not_swallowed(self):
        with patch.object(main_module, "load_csv_rows", side_effect=MemoryError("RAM agotada")):
            with self.assertRaises(MemoryError):
                HardwareCatalogView()

    def test_energy_source_label_is_traceable_clickable_and_handles_lost_snapshot(self):
        config = {"local_metrics": {"green_energy_percent": 78}}
        with patch.object(main_module, "load_config", return_value=config):
            view = SettingsView()
        self.assertIn("Renovable", view.energy_source_label.text())
        self.assertIn("78.0%", view.energy_source_label.text())

        with patch.object(QDialog, "exec", return_value=QDialog.Accepted):
            view.energy_source_label.click()

        config["local_metrics"]["green_energy_percent"] = 50
        with patch.object(main_module, "load_config", return_value=config):
            view._refresh_energy_source_label()
        self.assertIn("Mix Equilibrado", view.energy_source_label.text())

        view._energy_mix_snapshot = None
        with patch.object(QMessageBox, "warning") as warning:
            view._show_energy_breakdown()
        self.assertIn("memoria temporal", warning.call_args.args[2])
        view.deleteLater()

    def test_recommendations_use_scroll_book_and_can_be_minimized(self):
        view = CarbonDetailView()
        self.assertEqual(view.recommendations_scroll.maximumHeight(), 260)
        self.assertFalse(view._recommendations_minimized)

        view.recommendations_minimize_btn.click()
        self.assertTrue(view._recommendations_minimized)
        self.assertTrue(view.recommendations_scroll.isHidden())
        self.assertIn("Maximizar", view.recommendations_minimize_btn.text())

        view.recommendations_minimize_btn.click()
        self.assertFalse(view._recommendations_minimized)
        self.assertFalse(view.recommendations_scroll.isHidden())
        view.deleteLater()

    def test_applied_hardware_recommendation_is_visible_and_reversible(self):
        gpu_original = {"Fabricante": "GPU", "Modelo": "Original", "Tipo_Componente": "GPU", "TDP_Max_Watts": "300"}
        gpu_efficient = {"Fabricante": "GPU", "Modelo": "Eficiente", "Tipo_Componente": "GPU", "TDP_Max_Watts": "100"}
        cpu_original = {"Fabricante": "CPU", "Modelo": "Original", "Tipo_Componente": "CPU", "TDP_Max_Watts": "120"}
        cpu_efficient = {"Fabricante": "CPU", "Modelo": "Eficiente", "Tipo_Componente": "CPU", "TDP_Max_Watts": "60"}

        class Controller:
            def __init__(self):
                self.selection_state = {"cloud_locked": False, "hardware": "", "hardware_tdp": None}
                self.hardware_view = HardwareCatalogView(on_assign=self._handle_hardware_assign)
                self.hardware_view.hardware_rows = [gpu_original, gpu_efficient, cpu_original, cpu_efficient]

            def _handle_hardware_assign(self, hardware=None, hardware_tdp=None):
                self.selection_state["hardware"] = hardware
                self.selection_state["hardware_tdp"] = hardware_tdp

        controller = Controller()
        controller.hardware_view._handle_assign(gpu_original)
        controller.hardware_view._handle_assign(cpu_original)
        with patch.object(QMessageBox, "information"), patch.object(QMessageBox, "warning"):
            DashboardWindow._apply_recommendation(controller)

        self.assertIs(controller.hardware_view.selected_by_type["GPU"], gpu_efficient)
        self.assertIs(controller.hardware_view.selected_by_type["CPU"], cpu_original)
        self.assertIn("GPU Eficiente", controller.hardware_view.selection_summary.text())

        controller.hardware_view._handle_assign(gpu_original)
        self.assertIs(controller.hardware_view.selected_by_type["GPU"], gpu_original)
        self.assertIn("GPU Original", controller.selection_state["hardware"])
        controller.hardware_view.deleteLater()

    def test_hardware_recommendation_respects_license_restriction(self):
        original = {"Fabricante": "GPU", "Modelo": "Original", "Tipo_Componente": "GPU", "TDP_Max_Watts": "300"}
        restricted = {
            "Fabricante": "GPU", "Modelo": "Restringida", "Tipo_Componente": "GPU", "TDP_Max_Watts": "100",
            "_metadata": {"license_status": "restricted", "license_reason": "Contrato no habilitado"},
        }

        class Controller:
            selection_state = {"cloud_locked": False}

            def __init__(self):
                self.hardware_view = HardwareCatalogView()
                self.hardware_view.hardware_rows = [original, restricted]

        controller = Controller()
        controller.hardware_view._handle_assign(original)
        with patch.object(QMessageBox, "warning") as warning:
            DashboardWindow._apply_recommendation(controller)
        self.assertIs(controller.hardware_view.selected_by_type["GPU"], original)
        self.assertIn("licencia", warning.call_args.args[2].lower())
        controller.hardware_view.deleteLater()

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

    def test_models_view_hard_delete_accepts_optional_columns(self):
        from main import ModelsView

        with tempfile.TemporaryDirectory() as directory:
            model_file = os.path.join(directory, "models.json")
            with open(model_file, "w", encoding="utf-8") as handle:
                json.dump([
                    {"Nombre_Modelo": "Eliminar", "is_active": True},
                    {"Nombre_Modelo": "Conservar"},
                ], handle)
            with patch.object(
                main_module,
                "load_model_records",
                return_value=[{"Nombre_Modelo": "Eliminar"}, {"Nombre_Modelo": "Conservar"}],
            ), patch.object(
                main_module, "writable_path", return_value=model_file
            ), patch.object(
                QMessageBox, "question", return_value=QMessageBox.Yes
            ), patch.object(QMessageBox, "information"), patch.object(
                QMessageBox, "critical"
            ) as critical:
                view = ModelsView()
                view.model_combo.setCurrentText("Eliminar")
                view._handle_hard_delete()

            with open(model_file, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), [{"Nombre_Modelo": "Conservar"}])
            critical.assert_not_called()
            self.assertEqual(view.model_combo.findText("Eliminar"), -1)
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

    def test_cloud_view_blocks_when_regional_factor_is_missing(self):
        view = main_module.CloudView()
        current_region = view.region_combo.currentText()
        view.region_intensity_map[current_region] = None
        view._sync_cards()
        self.assertIn("cálculo ambiental bloqueado", view.region_factor_status.text())
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

    def test_diesel_contingency_increases_impact_and_restores_standard_calculation(self):
        class HomeStub:
            def set_semaforo_level(self, *args):
                self.last_level = args[0]

        class Controller:
            home_view = HomeStub()
            selection_state = {
                "provider": "Local", "region": "Chile", "region_intensity": 100,
                "model": "Demo", "model_energy": None, "hardware": "GPU",
                "hardware_tdp": 100, "diesel_generator_enabled": False,
                "diesel_factor": 850, "diesel_factor_fallback": False,
            }

        controller = Controller()
        with patch.object(main_module, "load_config", return_value={}):
            DashboardWindow._update_semaforo(controller)
            standard_carbon = controller.current_score
            controller.selection_state["diesel_generator_enabled"] = True
            DashboardWindow._update_semaforo(controller)

        self.assertGreater(controller.current_score, standard_carbon * 8)
        self.assertEqual(controller.current_semaphore_level, "Rojo")
        self.assertTrue(controller.current_evaluation["diesel_generator_enabled"])

        controller.selection_state["diesel_generator_enabled"] = False
        with patch.object(main_module, "load_config", return_value={}):
            DashboardWindow._update_semaforo(controller)
        self.assertEqual(controller.current_score, standard_carbon)

    def test_regional_water_factors_and_immersion_update_live_evaluation(self):
        class HomeStub:
            def set_semaforo_level(self, *args):
                pass

        class Controller:
            home_view = HomeStub()
            selection_state = {
                "provider": "Cloud", "region": "Sudáfrica (Ciudad del Cabo)", "region_intensity": 100,
                "model": "Demo", "model_energy": None, "hardware": "GPU", "hardware_tdp": 100,
                "diesel_generator_enabled": False, "diesel_factor": 850, "diesel_factor_fallback": False,
            }

        controller = Controller()
        with patch.object(main_module, "load_config", return_value={"local_metrics": {"pue": 1.0}}):
            DashboardWindow._update_semaforo(controller)
        self.assertEqual(controller.current_evaluation["wsi"], 3.0)
        self.assertEqual(controller.current_evaluation["water"], 0.66)
        self.assertTrue(controller.current_evaluation["wsi_severe"])

        with patch.object(main_module, "load_config", return_value={"local_metrics": {"pue": 1.5}, "immersion_enabled": True}):
            DashboardWindow._update_semaforo(controller)
        self.assertEqual(controller.current_evaluation["water"], 0.0)
        self.assertEqual(controller.current_evaluation["kwh"], 0.12)

    def test_unknown_region_uses_conservative_wue_with_warning_flag(self):
        factors = main_module.load_water_factors("Región sin catálogo", {"local_metrics": {}})
        self.assertEqual(factors["wue"], main_module.DEFAULT_WUE)
        self.assertEqual(factors["wsi"], 1.0)
        self.assertTrue(factors["wue_fallback"])

    def test_immersion_toggle_rejects_incompatible_selected_hardware(self):
        class HardwareStub:
            selected_by_type = {"GPU": {"Modelo": "GPU"}, "CPU": None, "RAM": {"Modelo": "RAM"}}

        class MainStub:
            hardware_view = HardwareStub()
            selection_state = {"hardware": "GPU + RAM"}

            def _update_semaforo(self):
                pass

        with tempfile.TemporaryDirectory() as directory, patch.object(
            main_module, "load_config", return_value={}
        ), patch.object(
            main_module, "writable_path", side_effect=lambda *parts: os.path.join(directory, *parts)
        ), patch.object(QMessageBox, "warning") as warning:
            settings = SettingsView(main_window=MainStub())
            settings.fluid_combo.setCurrentText("Aceite mineral")
            settings.immersion_checkbox.setChecked(True)

        self.assertFalse(settings.immersion_checkbox.isChecked())
        warning.assert_called()
        settings.deleteLater()

    def test_measured_wue_and_flow_meter_persist_while_invalid_water_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            config = {"local_metrics": {"pue": 1.0, "green_energy_percent": 0}}
            config_path = os.path.join(directory, "config.json")
            with patch.object(main_module, "load_config", side_effect=lambda: config), patch.object(
                main_module, "writable_path", side_effect=lambda *parts: os.path.join(directory, *parts)
            ), patch.object(QMessageBox, "warning") as warning, patch.object(QMessageBox, "information"):
                settings = SettingsView()
                settings.wue_input.setText("-1")
                settings.save_metrics_btn.click()
                warning.assert_called()
                self.assertNotIn("wue", config["local_metrics"])

                settings.wue_input.setText("1.7")
                settings.save_metrics_btn.click()
                with open(config_path, encoding="utf-8") as handle:
                    self.assertEqual(json.load(handle)["local_metrics"]["wue"], 1.7)

                settings.manual_litres_input.setText("0")
                settings._save_manual_litres()
                self.assertNotIn("manual_litres", config["local_metrics"])

                with patch.object(main_module, "flow_meter_reading", return_value=12.5):
                    settings._read_flow_meter()
                with open(config_path, encoding="utf-8") as handle:
                    saved = json.load(handle)
                self.assertEqual(saved["local_metrics"]["manual_litres"], 12.5)
                settings.deleteLater()

    def test_missing_diesel_matrix_uses_visible_safe_fallback(self):
        with patch.object(main_module, "resource_path", return_value="missing-environmental-factors.json"):
            factor, fallback = main_module.load_diesel_factor()
        self.assertEqual(factor, main_module.DEFAULT_DIESEL_FACTOR)
        self.assertTrue(fallback)

        with patch.object(main_module, "resource_path", return_value="missing-environmental-factors.json"), patch.object(
            main_module, "load_config", return_value={}
        ):
            settings = SettingsView()
        self.assertIn("matriz diésel no disponible", settings.generator_status_label.text())
        self.assertIn("850", settings.generator_status_label.text())
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
