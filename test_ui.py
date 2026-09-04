import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from main import HardwareCatalogView, HomeView


class FakeMainWindow:
    current_semaphore_level = "Amarillo"


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


if __name__ == "__main__":
    unittest.main()
