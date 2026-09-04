import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

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

    def test_carbon_sync_rejects_bad_network_and_cache_data(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "carbon.json"
            cache.write_text("{bad", encoding="utf-8")
            session = Mock()
            session.get.side_effect = requests.ConnectionError("offline")
            client = CarbonFactorClient(cache, session=session)
            with self.assertRaises(ExternalServiceError):
                client.sync("https://carbon.example/factors")

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

    def test_liquid_cooling_roi_requires_real_savings(self):
        result = liquid_cooling_roi(10000, 1.5, 1.1, 0.2, 500)
        self.assertTrue(result["viable"])
        self.assertEqual(result["annual_cost_saving"], 800.0)
        no_saving = liquid_cooling_roi(10000, 1.1, 1.5, 0.2, 500)
        self.assertFalse(no_saving["viable"])


if __name__ == "__main__":
    unittest.main()
