import csv
import json
import http.client
import threading
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import i18n

from functional_core import (
    ApiKeyError,
    CircuitBreakerError,
    DataIntegrityError,
    Execution,
    LocalStore,
    ValidationError,
    calculate_carbon,
    classify_cpu_tier,
    calculate_cost,
    calculate_energy,
    calculate_execution,
    calculate_water,
    budget_percentage,
    capacity_plan,
    component_percentages,
    compare_models,
    convert_clp,
    decrypt_api_key,
    encrypt_api_key,
    estimate_cloud,
    export_records,
    fetch_exchange_rates,
    format_carbon,
    green_score,
    import_records,
    forecast_budget,
    predict_limit_breach,
    mask_api_key,
    rightsizing,
    semaphore_level,
    sanitize_markdown,
    render_markdown,
    software_efficiency_recommendations,
    validate_api_key_format,
    validate_password,
    validate_thresholds,
    hash_password,
)


class FunctionalCoreTests(unittest.TestCase):
    def test_calculation_pipeline(self):
        self.assertEqual(calculate_cost(12, 2, "USD"), 24.0)
        self.assertEqual(calculate_energy(1000, 2, 1.5), 3.0)
        self.assertEqual(calculate_carbon(1000, 2, 1, 400), 800.0)
        self.assertEqual(calculate_carbon(1000, 2, 1, 400, 1, 1000), 1400.0)
        self.assertEqual(calculate_water(3, 2, 3, immersion=True), 0.0)
        self.assertEqual(format_carbon(10001), "10.00 kgCO2eq")

    @patch("functional_core.requests.get")
    def test_exchange_rates_from_api_and_inverse_conversion(self, get):
        response = Mock()
        response.json.return_value = {
            "result": "success",
            "rates": {currency: index + 1 for index, currency in enumerate(("USD", "EUR", "BRL", "PEN", "ARS", "CNY", "GBP", "JPY", "CAD", "CHF"))},
        }
        get.return_value = response
        with tempfile.TemporaryDirectory() as directory:
            rates = fetch_exchange_rates(Path(directory) / "rates.json")
        self.assertEqual(rates["CLP"], 1.0)
        self.assertEqual(set(rates), {"CLP", "USD", "EUR", "BRL", "PEN", "ARS", "CNY", "GBP", "JPY", "CAD", "CHF"})
        self.assertEqual(convert_clp(100, "USD", rates), (100.0, 1.0))
        get.assert_called_once()

    @patch("functional_core.requests.get", side_effect=ConnectionError("offline"))
    def test_exchange_rates_use_local_fallback(self, get):
        rates_data = {currency: 0.5 for currency in ("USD", "EUR", "BRL", "PEN", "ARS", "CNY", "GBP", "JPY", "CAD", "CHF")}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rates.json"
            path.write_text(json.dumps({"rates": rates_data}), encoding="utf-8")
            rates = fetch_exchange_rates(path)
        self.assertEqual(rates["USD"], 0.5)

    def test_xlsx_report_contains_structured_sheets(self):
        from openpyxl import load_workbook
        from export_handler import _create_xlsx_report

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.xlsx"
            _create_xlsx_report(
                "economia",
                {
                    "kpis": [[15, 60, "Costo", "100", "USD ($)", "cyan_500"]],
                    "details": [["GPU", "48%", "emerald_500"]],
                    "logs": [["OK", "red_500"]],
                    "exported_by": "Test",
                    "progress": 64,
                },
                path,
            )
            workbook = load_workbook(path)
            try:
                self.assertEqual(set(workbook.sheetnames), {"KPIs", "Detalles", "Actividad", "Resumen"})
                self.assertEqual(workbook["KPIs"]["A1"].value, "Posición")
                self.assertEqual(workbook["KPIs"]["E2"].value, "USD ($)")
                self.assertNotIn("Color", [cell.value for cell in workbook["KPIs"][1]])
                self.assertNotIn("Color", [cell.value for cell in workbook["Detalles"][1]])
                self.assertNotIn("Color", [cell.value for cell in workbook["Actividad"][1]])
                self.assertEqual(workbook["Resumen"]["B4"].value, "Test")
                self.assertEqual(workbook["KPIs"]["A1"].fill.fgColor.rgb[-6:], "17324D")
                self.assertEqual(workbook["KPIs"]["D2"].fill.fgColor.rgb[-6:], "CFFAFE")
                self.assertEqual(workbook["Detalles"]["A2"].fill.fgColor.rgb[-6:], "D1FAE5")
                self.assertEqual(workbook["Actividad"]["A2"].fill.fgColor.rgb[-6:], "FEE2E2")
                self.assertEqual(workbook["KPIs"].auto_filter.ref, "A1:E2")
            finally:
                workbook.close()

    def test_invalid_business_values(self):
        with self.assertRaises(ValidationError):
            validate_thresholds(60, 50, 90)
        with self.assertRaises(ValidationError):
            validate_password("weak")
        with self.assertRaises(ValidationError):
            calculate_water(1, 1, 4)

    def test_green_score_and_semaphore(self):
        score, badge = green_score(10, 100, 10, 100)
        self.assertEqual((score, badge), (90.0, "A+"))
        self.assertEqual(semaphore_level(40, 50, 90, 100), "Verde")
        self.assertEqual(semaphore_level(70, 50, 90, 100), "Amarillo")
        self.assertEqual(semaphore_level(95, 50, 90, 100), "Rojo")

    def test_comparison_ties_and_markdown_limits(self):
        compared = compare_models([
            {"name": "A", "carbon": 10, "cost": 2},
            {"name": "B", "carbon": 10, "cost": 3},
            {"name": "C", "carbon": 20, "cost": 1},
        ])
        self.assertEqual([row["optimal"] for row in compared], [True, True, False])
        self.assertEqual(sanitize_markdown("<script>alert(1)</script>"), "&lt;script&gt;alert(1)&lt;/script&gt;")
        with self.assertRaises(ValidationError):
            sanitize_markdown("x" * 4, max_chars=3)

    def test_safe_markdown_and_component_percentages(self):
        html = render_markdown("# Titulo\n\n- **CPU**\n- [Sitio](https://example.com)\n<script>alert(1)</script>")
        self.assertIn("<h1>Titulo</h1>", html)
        self.assertIn("<strong>CPU</strong>", html)
        self.assertIn('href="https://example.com"', html)
        self.assertNotIn("<script>", html)
        percentages = component_percentages({"CPU": 1, "GPU": 2, "RAM": 1})
        self.assertEqual(sum(percentages.values()), 100.0)
        self.assertEqual(percentages["GPU"], 50.0)
        self.assertEqual(budget_percentage(125, 100), 100)
        self.assertIsNone(budget_percentage(125, 0))
        with self.assertRaises(ValidationError):
            budget_percentage(-1, 100)

    def test_software_efficiency_recommendations_are_conservative(self):
        self.assertEqual(software_efficiency_recommendations(60_000, 70, 60, 8), [])
        findings = software_efficiency_recommendations(700_000, 35, 95, 1)
        self.assertEqual(
            {item["code"] for item in findings},
            {"LONG_RUNTIME", "LOW_CPU_UTILIZATION", "HIGH_MEMORY_PRESSURE", "SINGLE_ITEM_BATCH"},
        )
        with self.assertRaises(ValidationError):
            software_efficiency_recommendations(1, 101)

    def test_import_records_validates_declared_schema_and_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            valid = Path(directory) / "valid.json"
            valid.write_text(json.dumps([{"model_id": 1, "cost": 2.5}]), encoding="utf-8")
            self.assertEqual(
                import_records(valid, required_fields=("model_id", "cost"))[0]["model_id"],
                1,
            )

            missing = Path(directory) / "missing.csv"
            missing.write_text("model_id\n1\n", encoding="utf-8")
            with self.assertRaises(DataIntegrityError):
                import_records(missing, required_fields=("model_id", "cost"))

            inconsistent = Path(directory) / "inconsistent.json"
            inconsistent.write_text(
                json.dumps([{"model_id": 1, "cost": 2.5}, {"model_id": 2}]),
                encoding="utf-8",
            )
            with self.assertRaises(DataIntegrityError):
                import_records(inconsistent)
            self.assertEqual(
                len(import_records(inconsistent, require_uniform_columns=False)),
                2,
            )

    def test_api_key_encryption_roundtrip_and_validation(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            key_path = Path(tmp_dir) / "secrets" / "financial_api.key"
            token = encrypt_api_key("ABCDEFGHIJKLMNOP1234", key_path)
            self.assertNotIn("ABCDEFGHIJKLMNOP1234", token)
            self.assertEqual(decrypt_api_key(token, key_path), "ABCDEFGHIJKLMNOP1234")
            self.assertEqual(mask_api_key("ABCDEFGHIJKLMNOP1234"), "****1234")
            with self.assertRaises(ApiKeyError):
                validate_api_key_format("short")
            with self.assertRaises(ApiKeyError):
                decrypt_api_key("not-a-real-token", key_path)

    def test_rightsizing_and_budget_forecast(self):
        recommendation = rightsizing(200, [
            {"name": "same", "tdp_watts": 190},
            {"name": "efficient", "tdp_watts": 150},
        ])
        self.assertEqual(recommendation["candidate"]["name"], "efficient")
        self.assertEqual(recommendation["saving_percent"], 25.0)
        self.assertEqual(forecast_budget(500, 15, 800, 30), 1000.0)
        with self.assertRaises(ValidationError):
            forecast_budget(500, 0, 800, 30)

    def test_governance_circuit_override_and_capacity_plan(self):
        now = datetime(2026, 9, 4, tzinfo=timezone.utc)
        breach = predict_limit_breach(
            [{"timestamp": "2026-09-01T00:00:00+00:00", "cost": 30}], 100, "cost", now,
        )
        self.assertEqual(breach.date(), date(2026, 9, 11))
        plan = capacity_plan(4000, 300, [
            {"name": "Viable", "tdp_watts": 150, "acquisition_cost": 200},
            {"name": "Caro", "tdp_watts": 100, "acquisition_cost": 10000},
        ], energy_price_per_kwh=0.25, pue=1.2, grid_factor=400)
        self.assertEqual(plan["candidate"]["name"], "Viable")
        self.assertLessEqual(plan["payback_years"], 3)

        with tempfile.TemporaryDirectory() as directory:
            store = LocalStore(Path(directory) / "governance.sqlite3")
            project = store.add_project("Gobernado")
            model = store.add_model(project, "Modelo")
            store.add_user("admin", "ClaveSegura1@", "Administrador")
            store.set_project_quotas(project, 10, 100)
            execution = Execution(model, "2026-09-04 12:00:00", 11, 50, 1, 1, 10, "Rojo")
            with self.assertRaises(CircuitBreakerError):
                store.add_execution(execution)
            with self.assertRaises(PermissionError):
                store.create_admin_override(project, "admin", "incorrecta", "Emergencia")
            token = store.create_admin_override(project, "admin", "ClaveSegura1@", "Emergencia")
            store.add_execution(execution, token)
            with self.assertRaises(CircuitBreakerError):
                store.add_execution(execution, token)
            actions = [row["action"] for row in store.connection.execute("SELECT action FROM audit_log")]
            self.assertEqual(actions, ["override_denied", "override_granted", "override_used"])
            store.close()

    def test_admin_override_expiration_and_closed_project_block_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            store = LocalStore(Path(directory) / "closed.sqlite3")
            project = store.add_project("Cerrado")
            model = store.add_model(project, "Modelo")
            store.add_user("admin", "ClaveSegura1@", "Administrador")
            first = Execution(model, "2026-09-04 12:00:00", 1, 1, 1, 1, 10, "Verde")
            store.add_execution(first)
            store.close_project(project)
            with self.assertRaises(CircuitBreakerError):
                store.add_execution(first)

            open_project = store.add_project("Override expirado")
            open_model = store.add_model(open_project, "Modelo")
            token = store.create_admin_override(
                open_project, "admin", "ClaveSegura1@", "Prueba", ttl_seconds=1,
            )
            store.connection.execute(
                "UPDATE admin_overrides SET expires_at = ? WHERE token = ?",
                ("2000-01-01 00:00:00", token),
            )
            store.connection.commit()
            expired = Execution(open_model, "2026-09-04 12:00:00", 2, 2, 1, 1, 10, "Rojo")
            store.set_project_quotas(open_project, 1, None)
            with self.assertRaises(CircuitBreakerError):
                store.add_execution(expired, token)
            store.close()

    def test_cpu_tier_classification_and_rightsizing_filter(self):
        self.assertEqual(classify_cpu_tier("Atom C2750"), 0)
        self.assertEqual(classify_cpu_tier("Core i5-10300H"), 2)
        self.assertEqual(classify_cpu_tier("Ryzen 7 5800X"), 3)
        self.assertEqual(classify_cpu_tier("Core i9-14900K"), 4)

        current_tier = classify_cpu_tier("Core i5-10300H")
        candidates = [
            {"name": "Atom C2750", "tdp_watts": 20, "performance_score": classify_cpu_tier("Atom C2750")},
            {"name": "Core i5 Efficient", "tdp_watts": 30, "performance_score": classify_cpu_tier("Core i5-9400F")},
        ]
        recommendation = rightsizing(45, candidates, current_performance=current_tier)
        self.assertEqual(recommendation["candidate"]["name"], "Core i5 Efficient")

    def test_new_ui_strings_are_bilingual(self):
        translations = {
            "Comparativa de modelos": "Model comparison",
            "Empate técnico": "Technical tie",
            "Sugerir hardware eficiente": "Suggest efficient hardware",
            "No hay ejecuciones registradas.": "No executions recorded.",
            "Usuario bloqueado": "User locked",
            "Disyuntor: dentro de cuota": "Circuit breaker: within quota",
            "Disyuntor activo: {reason}": "Circuit breaker active: {reason}",
            "Fuente Primaria Operante": "Primary Operating Source",
            "Mix Equilibrado": "Balanced Mix",
            "Cuotas por usuario": "Per-user quotas",
            "Modo Concentración (silencia avisos)": "Focus Mode (mutes notifications)",
            "Usar entorno Cloud (bloquea factores locales)": "Use Cloud environment (locks local factors)",
            "Catálogo paginado": "Paginated catalog",
            "Copiar detalles": "Copy details",
            "Cambio de contraseña obligatorio": "Mandatory password change",
            "Importar CSV hidráulico": "Import hydraulic CSV",
        }
        for spanish, english in translations.items():
            self.assertEqual(i18n.t(spanish, "en"), english)
            self.assertEqual(i18n.t(english, "es"), spanish)

    def test_cloud_traceability_and_execution(self):
        estimate = estimate_cloud({"name": "small", "cost_per_hour_usd": 2, "watts": 500}, 3, 400)
        self.assertEqual(estimate["cost_usd"], 6.0)
        self.assertEqual(estimate["carbon_gco2eq"], 600.0)
        self.assertEqual(estimate["inputs"]["watts"], 500.0)
        execution, badge = calculate_execution(
            model_id=1, hourly_cost=2, hours=3, currency="USD", tdp_watts=500,
            pue=1.2, grid_factor=400, wue=1, wsi=1, cost_limit=100,
            carbon_limit=1000,
        )
        self.assertEqual(execution.kwh, 1.8)
        self.assertEqual(execution.carbon, 720.0)
        self.assertEqual(badge, "C")

    def test_clear_and_delete_project_are_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            store = LocalStore(Path(directory) / "projects.sqlite3")
            first_project = store.add_project("Primero")
            second_project = store.add_project("Segundo")
            first_model = store.add_model(first_project, "Modelo A")
            second_model = store.add_model(second_project, "Modelo B")
            for model_id in (first_model, second_model):
                store.connection.execute(
                    """INSERT INTO executions(
                           model_id, timestamp, cost, carbon, kwh, water, duration_ms, semaphore
                       ) VALUES (?, '2026-01-01 00:00:00', 1, 2, 3, 4, 5, 'Verde')""",
                    (model_id,),
                )
            store.connection.commit()

            store.clear_project(first_project)
            self.assertEqual(len(store.list_models(first_project)), 0)
            self.assertEqual(len(store.list_history(project_id=first_project)), 0)
            self.assertEqual(len(store.list_models(second_project)), 1)
            self.assertEqual(len(store.list_history(project_id=second_project)), 1)
            self.assertIsNotNone(store.connection.execute(
                "SELECT id FROM projects WHERE id = ?", (first_project,)
            ).fetchone())

            store.delete_project(first_project)
            self.assertIsNone(store.connection.execute(
                "SELECT id FROM projects WHERE id = ?", (first_project,)
            ).fetchone())
            self.assertEqual(len(store.list_projects()), 1)
            with self.assertRaises(ValidationError):
                store.delete_project(first_project)
            store.close()

    def test_secure_authentication_and_lockout(self):
        with tempfile.TemporaryDirectory() as directory:
            store = LocalStore(Path(directory) / "test.sqlite3")
            store.add_user("admin", "ClaveSegura1@", "admin")
            self.assertEqual(store.authenticate("admin", "ClaveSegura1@")["role"], "admin")
            for _ in range(5):
                self.assertIsNone(store.authenticate("admin", "incorrecta"))
            self.assertIsNone(store.authenticate("admin", "ClaveSegura1@"))
            row = store.connection.execute(
                "SELECT failed_attempts, is_locked FROM users WHERE username = ?", ("admin",)
            ).fetchone()
            self.assertEqual((row["failed_attempts"], row["is_locked"]), (5, 1))
            store.close()

    def test_admin_can_reset_password_and_change_role(self):
        with tempfile.TemporaryDirectory() as directory:
            store = LocalStore(Path(directory) / "admin.sqlite3")
            store.add_user("admin", "ClaveSegura1@", "Administrador")
            store.add_user("user", "ClaveSegura1@", "Usuario")
            store.set_user_password("user", "NuevaClave2_")
            self.assertEqual(store.authenticate("user", "NuevaClave2_")["username"], "user")
            store.set_user_role("user", "Administrador")
            role = store.connection.execute("SELECT role FROM users WHERE username='user'").fetchone()["role"]
            self.assertEqual(role, "Administrador")
            with self.assertRaises(ValidationError):
                store.set_user_password("user", "weak")
            store.close()

    def test_server_authentication_uses_shared_store_and_lockout(self):
        import server

        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "server.sqlite3"
            store = LocalStore(database_path)
            store.add_user("remote", "ClaveSegura1@")
            store.close()

            def open_store():
                return LocalStore(database_path)

            with patch("server.get_store", side_effect=open_store):
                user, error, status = server.authenticate_request("remote", "ClaveSegura1@")
                self.assertEqual((user["username"], error, status), ("remote", None, 200))
                for _ in range(5):
                    user, error, status = server.authenticate_request("remote", "incorrecta")
                self.assertEqual((user, error, status), (None, "Usuario bloqueado", 423))

    def test_server_http_login_token_and_hardware_access(self):
        import server

        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "server_http.sqlite3"
            store = LocalStore(database_path)
            password_hash = hash_password("ClaveSegura1@")
            store.add_hashed_user("remote", password_hash)
            store.close()

            def open_store():
                return LocalStore(database_path)

            httpd = server.socketserver.ThreadingTCPServer(("127.0.0.1", 0), server.SimpleHandler)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            try:
                with patch("server.get_store", side_effect=open_store), patch(
                    "server.load_config",
                    return_value={"users": [{"username": "remote", "password_hash": password_hash}]},
                ), patch("server.get_hardware_info", return_value={"cpu": "test"}):
                    connection = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1])
                    body = json.dumps({"username": "remote", "password": "ClaveSegura1@"})
                    connection.request("POST", "/login", body, {"Content-Type": "application/json"})
                    response = connection.getresponse()
                    login_data = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(response.status, 200)
                    self.assertTrue(login_data["token"])

                    connection.request("GET", "/hardware")
                    self.assertEqual(connection.getresponse().status, 401)
                    connection.request("GET", "/hardware", headers={"Authorization": f"Bearer {login_data['token']}"})
                    hardware_response = connection.getresponse()
                    self.assertEqual((hardware_response.status, json.loads(hardware_response.read())["cpu"]), (200, "test"))
                    connection.close()
            finally:
                httpd.shutdown()
                httpd.server_close()
                thread.join(timeout=2)

    def test_admin_can_view_and_unlock_accounts(self):
        with tempfile.TemporaryDirectory() as directory:
            store = LocalStore(Path(directory) / "users.sqlite3")
            store.add_user("maxine", "ClaveSegura1@")
            for _ in range(5):
                store.authenticate("maxine", "incorrecta")
            status = store.list_user_status()[0]
            self.assertEqual((status["failed_attempts"], status["is_locked"]), (5, 1))
            with self.assertRaises(PermissionError):
                store.unlock_user("maxine", "Usuario")
            store.unlock_user("maxine", "Administrador")
            status = store.list_user_status()[0]
            self.assertEqual((status["failed_attempts"], status["is_locked"]), (0, 0))
            store.close()

    def test_json_round_trip_and_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "records.json"
            records = [{"name": "modelo", "is_active": True}]
            export_records(records, path)
            self.assertEqual(import_records(path), records)
            path.write_text("{bad", encoding="utf-8")
            with self.assertRaises(ValidationError):
                import_records(path)

    def test_project_lifecycle_and_reassignment(self):
        with tempfile.TemporaryDirectory() as directory:
            store = LocalStore(Path(directory) / "projects.sqlite3")
            source = store.add_project("Proyecto A")
            target = store.add_project("Proyecto B")
            model = store.add_model(source, "Modelo QA", "# Descripcion")
            store.add_execution(Execution(model, "2026-08-24 12:00:00", 10, 20, 2, 3, 900, "Verde"))
            self.assertEqual(store.project_totals(source)["cost"], 10.0)
            store.reassign_model(model, target)
            self.assertEqual(store.project_totals(source)["cost"], 0.0)
            self.assertEqual(store.project_totals(target)["cost"], 10.0)
            store.archive_project(target)
            with self.assertRaises(ValidationError):
                store.add_model(target, "Bloqueado")
            backup = Path(directory) / "backup.sqlite3"
            store.backup(backup)
            self.assertTrue(backup.exists())
            backup_store = LocalStore(backup)
            self.assertEqual(backup_store.project_totals(target)["cost"], 10.0)
            self.assertEqual(len(backup_store.list_history()), 1)
            backup_store.close()
            store.close()

    def test_empty_history_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            store = LocalStore(Path(directory) / "history.sqlite3")
            self.assertEqual(store.list_history(), [])
            store.close()

    def test_hardware_catalog_has_real_ram_options(self):
        catalog_path = Path(__file__).parent / "data" / "hardware.csv"
        with catalog_path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        ram_rows = [row for row in rows if row["Tipo_Componente"] == "RAM"]
        self.assertGreaterEqual(len(ram_rows), 5)
        self.assertTrue(all(row["Capacidad_GB"] for row in ram_rows))
        self.assertFalse(any("prueba" in row["Modelo"].lower() for row in rows))

    def test_paginate_and_low_carbon_filter(self):
        from functional_core import is_low_carbon_region, paginate

        rows = [{"id": index} for index in range(23)]
        page = paginate(rows, 3, 10)
        self.assertEqual((page["page"], page["pages"], page["total"]), (3, 3, 23))
        self.assertEqual(len(page["items"]), 3)
        self.assertEqual(paginate(rows, 99, 10)["page"], 3)
        self.assertEqual(paginate([], 1, 10)["total"], 0)
        with self.assertRaises(ValidationError):
            paginate(rows, 1, 0)
        self.assertTrue(is_low_carbon_region(45.0))
        self.assertFalse(is_low_carbon_region(250.0))
        self.assertFalse(is_low_carbon_region(None))
        self.assertFalse(is_low_carbon_region("corrupto"))

    def test_guided_errors_and_locked_parameters(self):
        from functional_core import assert_parameters_unlocked, describe_error

        payload = describe_error("ERR_QUOTA_FIN", "detalle")
        self.assertEqual(payload["code"], "ERR_QUOTA_FIN")
        self.assertTrue(payload["cause"] and payload["action"])
        self.assertEqual(describe_error("NO_EXISTE")["code"], "ERR_UNKNOWN")
        assert_parameters_unlocked([], ["hardware"])
        assert_parameters_unlocked(["pue"], ["hardware"])
        with self.assertRaises(ValidationError):
            assert_parameters_unlocked(["hardware"], ["hardware"])

    def test_user_quotas_block_executions_and_report_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            store = LocalStore(Path(directory) / "user_quota.sqlite3")
            store.add_user("operadora", "Segura-123")
            project = store.add_project("Cuotas usuario")
            model = store.add_model(project, "Modelo U")
            store.set_user_quotas("operadora", 5.0, None)
            first = Execution(model, "2026-09-01 10:00:00", 4.0, 1.0, 1.0, 1.0, 10, "Verde")
            store.add_execution(first, username="operadora")
            status = store.circuit_breaker_status(model, 2.0, 0.0, username="operadora")
            self.assertFalse(status["allowed"])
            self.assertIn("ERR_USER_QUOTA_FIN", status["codes"])
            second = Execution(model, "2026-09-01 11:00:00", 2.0, 1.0, 1.0, 1.0, 10, "Verde")
            with self.assertRaises(CircuitBreakerError):
                store.add_execution(second, username="operadora")
            # Otro usuario sin cuota no queda bloqueado por la cuota ajena.
            store.add_execution(second, username="externa")
            with self.assertRaises(ValidationError):
                store.set_user_quotas("operadora", -1, None)
            with self.assertRaises(ValidationError):
                store.set_user_quotas("fantasma", 1, 1)
            store.close()

    def test_template_soft_delete_and_linked_projects(self):
        with tempfile.TemporaryDirectory() as directory:
            store = LocalStore(Path(directory) / "templates.sqlite3")
            project = store.add_project("Vinculado")
            template = store.add_template("Plantilla A", {"project_id": project})
            orphan = store.add_template("Plantilla B", {})
            factory = store.add_template("Fabrica", {}, is_factory=True)
            self.assertEqual(store.template_linked_projects(template), ["Vinculado"])
            self.assertEqual(store.template_linked_projects(orphan), [])
            store.soft_delete_template(template)
            names = [item["name"] for item in store.list_templates()]
            self.assertNotIn("Plantilla A", names)
            all_names = [item["name"] for item in store.list_templates(include_deleted=True)]
            self.assertIn("Plantilla A", all_names)
            with self.assertRaises(PermissionError):
                store.soft_delete_template(factory)
            store.close()

    def test_hydro_records_flow_meter_and_desync(self):
        from functional_core import (
            detect_hydro_desync, flow_meter_reading, hydro_total_litres, parse_hydro_records,
        )

        records = parse_hydro_records([
            {"timestamp": "2026-09-01T10:00:00", "litres": "2.5"},
            {"timestamp": "2026-09-01T11:00:00", "litros": 1.5},
        ])
        self.assertEqual(hydro_total_litres(records), 4.0)
        self.assertEqual(detect_hydro_desync(records), [])
        desynced = parse_hydro_records([
            {"timestamp": "2026-09-01T10:00:00", "litres": 1},
            {"timestamp": "2026-09-01T09:00:00", "litres": 1},
            {"timestamp": "2026-09-02T09:00:00", "litres": 1},
        ])
        issues = detect_hydro_desync(desynced, max_gap_minutes=120)
        self.assertEqual(len(issues), 2)
        with self.assertRaises(DataIntegrityError):
            parse_hydro_records([{"timestamp": "no-fecha", "litres": 1}])
        with self.assertRaises(DataIntegrityError):
            parse_hydro_records([{"timestamp": "2026-09-01T10:00:00", "litres": -1}])
        with self.assertRaises(DataIntegrityError):
            parse_hydro_records([])
        reading = flow_meter_reading("simulador")
        self.assertGreaterEqual(reading, 1.0)
        with self.assertRaises(TimeoutError):
            flow_meter_reading("10.0.0.99")

    def test_primary_energy_source_and_balanced_mix(self):
        from functional_core import primary_energy_source

        dominant = primary_energy_source({"Renovable": 70, "Red": 30})
        self.assertEqual(dominant["label"], "Renovable")
        self.assertFalse(dominant["tied"])
        tied = primary_energy_source({"Renovable": 50, "Red": 50})
        self.assertEqual(tied["label"], "Mix Equilibrado")
        self.assertTrue(tied["tied"])
        with self.assertRaises(ValidationError):
            primary_energy_source({"Renovable": -1})
        with self.assertRaises(ValidationError):
            primary_energy_source({})

    def test_immersion_fluid_compatibility(self):
        from functional_core import check_immersion_compatibility

        self.assertEqual(check_immersion_compatibility(("CPU", "GPU"), "aceite mineral"), [])
        self.assertEqual(check_immersion_compatibility(("CPU", "GPU", "RAM"), "aceite mineral"), ["RAM"])
        self.assertEqual(check_immersion_compatibility(("CPU", "GPU", "RAM"), "fluido sintetico"), [])
        with self.assertRaises(ValidationError):
            check_immersion_compatibility(("CPU",), "agua")

    def test_normative_dates_and_local_offset(self):
        from functional_core import clock_is_trusted, format_local_timestamp, normative_date

        self.assertTrue(clock_is_trusted(datetime(2026, 9, 8, tzinfo=timezone.utc)))
        self.assertFalse(clock_is_trusted(datetime(1980, 1, 1, tzinfo=timezone.utc)))
        self.assertEqual(normative_date(datetime(2026, 9, 8, 23, 0, tzinfo=timezone.utc)), "2026-09-08")
        with self.assertRaises(ValidationError):
            normative_date(datetime(1970, 1, 1, tzinfo=timezone.utc))
        formatted = format_local_timestamp("2026-09-08 12:00:00")
        self.assertIn("UTC", formatted)
        self.assertRegex(formatted, r"UTC[+-]\d{2}:\d{2}")
        self.assertEqual(format_local_timestamp("corrupto"), "corrupto")

    def test_detect_new_hardware_reports_unknown_components(self):
        from functional_core import detect_new_hardware

        catalog = ["Intel Core i9-14900K", "NVIDIA RTX 4090"]
        detected = {"cpu": "Core i9-14900K", "gpu": "Radeon RX 9700", "ram": "No detectado"}
        self.assertEqual(detect_new_hardware(detected, catalog), ["Radeon RX 9700"])
        self.assertEqual(detect_new_hardware({}, catalog), [])

    def test_temporary_password_forces_change_and_clears_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            store = LocalStore(Path(directory) / "temp_pass.sqlite3")
            store.add_user("temporal", "Inicial-123")
            store.reset_password_temporary("temporal", "Temporal-123")
            user = store.authenticate("temporal", "Temporal-123")
            self.assertIsNotNone(user)
            self.assertEqual(user["force_password_change"], 1)
            store.set_user_password("temporal", "Definitiva-123")
            user = store.authenticate("temporal", "Definitiva-123")
            self.assertEqual(user["force_password_change"], 0)
            with self.assertRaises(ValidationError):
                store.reset_password_temporary("fantasma", "Temporal-123")
            with self.assertRaises(ValidationError):
                store.reset_password_temporary("temporal", "corta")
            store.close()


if __name__ == "__main__":
    unittest.main()
