import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from external_services import (
    BillingCloudClient,
    CarbonFactorClient,
    ExternalServiceError,
    SimulatedTelemetryClient,
    TelemetryError,
)
from functional_core import DataIntegrityError, LocalStore, ValidationError, liquid_cooling_roi
from functional_core import Execution
from esg_export import export_esg_pdf
import cli


class AdvancedFeatureTests(unittest.TestCase):
    def test_billing_sync_and_timeout_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "billing.json"
            response = Mock()
            response.json.return_value = {
                "rates": [{"instance": "g5.xlarge", "region": "us-east-1", "hourly_usd": 1.2}]
            }
            response.raise_for_status.return_value = None
            session = Mock()
            session.get.return_value = response
            client = BillingCloudClient(cache, timeout=0.25, session=session)
            rates, cached = client.sync("aws", "https://billing.example/rates", "secret")
            self.assertFalse(cached)
            self.assertEqual(rates[0]["hourly_usd"], 1.2)
            session.get.side_effect = requests.Timeout("offline")
            fallback, cached = client.sync("aws", "https://billing.example/rates")
            self.assertTrue(cached)
            self.assertEqual(fallback, rates)

    def test_billing_sync_retries_transient_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            response = Mock()
            response.json.return_value = {
                "rates": [{"instance": "g5.xlarge", "region": "us-east-1", "hourly_usd": 1.2}]
            }
            response.raise_for_status.return_value = None
            session = Mock()
            session.get.side_effect = [requests.Timeout("transient"), response]
            client = BillingCloudClient(
                Path(directory) / "billing.json",
                timeout=0.25,
                session=session,
                retries=1,
                backoff_seconds=0,
            )
            rates, cached = client.sync("aws", "https://billing.example/rates")
            self.assertFalse(cached)
            self.assertEqual(rates[0]["hourly_usd"], 1.2)
            self.assertEqual(session.get.call_count, 2)

    def test_carbon_sync_rejects_bad_network_and_cache_data(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "carbon.json"
            cache.write_text("{bad", encoding="utf-8")
            session = Mock()
            session.get.side_effect = requests.ConnectionError("offline")
            client = CarbonFactorClient(cache, session=session)
            with self.assertRaises(ExternalServiceError):
                client.sync("https://carbon.example/factors")

    def test_placeholder_external_adapters_return_demo_payloads(self):
        with tempfile.TemporaryDirectory() as directory:
            billing = BillingCloudClient(Path(directory) / "billing.json")
            rates, cached = billing.sync("aws", "placeholder://aws/rates")
            self.assertFalse(cached)
            self.assertTrue(rates)
            self.assertEqual(rates[0]["provider"], "aws")

            carbon = CarbonFactorClient(Path(directory) / "carbon.json")
            factors, cached = carbon.sync("placeholder://carbon/factors")
            self.assertFalse(cached)
            self.assertTrue(factors)
            self.assertIn("gco2eq_kwh", factors[0])

    def test_carbon_factor_versions_can_be_restored(self):
        from external_services import list_cache_snapshots, restore_cache_snapshot

        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "carbon.json"
            old = [{"region": "old", "gco2eq_kwh": 99, "updated_at": "2025-01-01"}]
            cache.write_text(json.dumps(old), encoding="utf-8")
            CarbonFactorClient(cache).sync("placeholder://carbon/factors")
            snapshots = list_cache_snapshots(cache)
            self.assertTrue(snapshots)
            restored = restore_cache_snapshot(cache, snapshots[0].name)
            self.assertEqual(restored, old)
            self.assertEqual(json.loads(cache.read_text(encoding="utf-8")), old)

    def test_simulated_telemetry_loss_factor_and_cancel(self):
        client = SimulatedTelemetryClient(100, 101, seed=7)
        watts = client.read_watts(loss_factor=1.5)
        self.assertGreaterEqual(watts, 150)
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(TelemetryError):
            client.read_watts(cancel_event=cancelled)
        with self.assertRaises(TelemetryError):
            client.read_watts(loss_factor=1.51)

    def test_safe_restore_and_factory_catalog_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            active_path = Path(directory) / "active.sqlite3"
            backup_path = Path(directory) / "backup.sqlite3"
            store = LocalStore(active_path)
            store.add_project("Original")
            store.backup(backup_path)
            store.add_project("Temporal")
            store.restore(backup_path)
            self.assertEqual([row["name"] for row in store.list_projects()], ["Original"])

            factory_id = store.add_hardware("Factory GPU", "GPU", 300, is_factory=True)
            custom_id = store.add_hardware("Custom GPU", "GPU", 200)
            with self.assertRaises(PermissionError):
                store.update_hardware(factory_id, "Changed", "GPU", 100)
            store.update_hardware(custom_id, "Custom GPU 2", "GPU", 180)
            self.assertEqual(len(store.list_hardware()), 2)
            factory_template = store.add_template("Factory", {"hours": 1}, is_factory=True)
            custom_template = store.add_template("Custom", {"hours": 2})
            with self.assertRaises(PermissionError):
                store.delete_template(factory_template)
            store.update_template(custom_template, "Custom 2", {"hours": 3})
            updated = next(item for item in store.list_templates() if item["name"] == "Custom 2")
            self.assertEqual(updated["config"]["hours"], 3)

            corrupt = Path(directory) / "corrupt.sqlite3"
            corrupt.write_bytes(b"not sqlite")
            with self.assertRaises(DataIntegrityError):
                store.restore(corrupt)
            self.assertEqual([row["name"] for row in store.list_projects()], ["Original"])
            store.close()

    def test_esg_certificate_and_headless_calculation(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "headless.sqlite3"
            output = Path(directory) / "certificate.pdf"
            store = LocalStore(database)
            project = store.add_project("Campana ESG")
            model = store.add_model(project, "Modelo completo")
            with self.assertRaises(ValidationError):
                store.close_project(project)
            store.add_execution(Execution(model, "2026-09-04 12:00:00", 2, 30, 1, 4, 10, "Verde"))
            store.close_project(project)
            data = store.consolidate_esg(project)
            store.close()
            export_esg_pdf(data, output)
            self.assertTrue(output.read_bytes().startswith(b"%PDF"))

            result = cli.main([
                "--database", str(database), "calculate", "--model-id", str(model),
                "--hourly-cost", "1", "--hours", "1", "--tdp-watts", "100",
                "--pue", "1", "--grid-factor", "100", "--wue", "1", "--wsi", "1",
                "--cost-limit", "100", "--carbon-limit", "100",
            ])
            self.assertEqual(result, 0)

    def test_headless_rejects_unknown_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "headless.sqlite3"
            store = LocalStore(database)
            project = store.add_project("Proyecto conocido")
            store.add_model(project, "Modelo conocido")
            store.close()

            with patch("sys.stderr", new_callable=io.StringIO) as stderr:
                result = cli.main([
                    "--database", str(database), "calculate", "--model-id", "999999",
                    "--hourly-cost", "1", "--hours", "1", "--tdp-watts", "100",
                    "--pue", "1", "--grid-factor", "100", "--wue", "1", "--wsi", "1",
                    "--cost-limit", "100", "--carbon-limit", "100",
                ])
            self.assertEqual(result, 2)
            self.assertIn("Not found: model ID 999999", stderr.getvalue())

            with patch("sys.stderr", new_callable=io.StringIO) as stderr:
                result = cli.main([
                    "--database", str(database), "export", "--project-id", "999999",
                    "--output", str(Path(directory) / "unknown.csv"),
                ])
            self.assertEqual(result, 2)
            self.assertIn("Not found: project ID 999999", stderr.getvalue())

    def test_liquid_cooling_roi_requires_real_savings(self):
        result = liquid_cooling_roi(10000, 1.5, 1.1, 0.2, 500)
        self.assertTrue(result["viable"])
        self.assertEqual(result["annual_cost_saving"], 800.0)
        no_saving = liquid_cooling_roi(10000, 1.1, 1.5, 0.2, 500)
        self.assertFalse(no_saving["viable"])

    @patch.dict('os.environ', {'DB_MODE': 'sqlite', 'DB_PATH': 'C:/tmp/semaforo_fallback.sqlite3'}, clear=False)
    def test_db_can_fallback_to_sqlite_when_postgres_is_unavailable(self):
        import db
        connection = db.get_connection()
        self.assertEqual(connection.__class__.__module__, 'sqlite3')
        connection.close()

    def test_restore_fails_cleanly_when_database_is_locked(self):
        """Windows: os.replace must fail without corrupting the live database."""
        import sqlite3

        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "live.sqlite3"
            store = LocalStore(db_path)
            store.add_project("Base viva")
            backup_path = Path(directory) / "backup.sqlite3"
            store.backup(backup_path)
            blocker = sqlite3.connect(db_path)
            blocker.execute("BEGIN EXCLUSIVE")
            try:
                with self.assertRaises((PermissionError, DataIntegrityError)):
                    store.restore(backup_path)
            finally:
                blocker.rollback()
                blocker.close()
            # La base activa sigue siendo usable tras el fallo controlado.
            names = [row["name"] for row in store.list_projects()]
            self.assertIn("Base viva", names)
            store.close()

    def test_export_records_reports_permission_error_on_unwritable_target(self):
        from functional_core import export_records

        with tempfile.TemporaryDirectory() as directory:
            blocked = Path(directory) / "out.json"
            blocked.mkdir()  # ocupa la ruta destino con un directorio
            with self.assertRaises(PermissionError):
                export_records([{"a": 1}], blocked)

    def test_export_records_preserves_destination_when_atomic_replace_fails(self):
        from functional_core import export_records

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "out.json"
            destination.write_text('[{"original": true}]', encoding="utf-8")
            with patch("functional_core.os.replace", side_effect=OSError("disk failure")):
                with self.assertRaises(PermissionError):
                    export_records([{"replacement": True}], destination)
            self.assertEqual(destination.read_text(encoding="utf-8"), '[{"original": true}]')
            self.assertEqual(list(Path(directory).glob(".out.json.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
