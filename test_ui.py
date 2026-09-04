import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton, QSizePolicy

from main import AdminMenuView, FinOpsView, HardwareCatalogView, HomeView, ResponsiveStackedWidget, SettingsView


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

        admin = AdminMenuView({"display_name": "Nacha", "role": "Administrador", "username": "nacha"})
        admin.resize(800, 480)
        admin.show()
        self.app.processEvents()
        self.assertGreater(admin.admin_scroll.verticalScrollBar().maximum(), 0)
        unavailable = [button for button in admin.findChildren(QPushButton) if button.text() == "Roles y permisos"]
        self.assertEqual(len(unavailable), 1)
        self.assertFalse(unavailable[0].isEnabled())
        admin.deleteLater()


if __name__ == "__main__":
    unittest.main()
