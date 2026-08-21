import os
import sys
from PySide6.QtCore import QObject, QThread, Qt, QStandardPaths, Signal, Slot
from PySide6.QtWidgets import QApplication, QMessageBox, QFileDialog

import i18n
from i18n import t

# Add export handler to path
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "export handler"))

try:
    import eco
    import economia
    import inicio
except Exception as e:
    print(f"Error importing export scripts: {e}")

# Mantiene vivas las referencias a hilos/workers en curso (si no, Python los recolecta a mitad de la tarea).
_active_exports = []

def _pick_export_target(parent_widget, report_type, export_format, lang=None):
    if export_format == "json":
        ext = ".json"
        file_filter = t("Archivo JSON (*.json);;Todos los archivos (*)", lang)
    else:
        ext = ".pdf"
        file_filter = t("Archivo PDF (*.pdf);;Todos los archivos (*)", lang)

    default_names = {
        "eco": f"informe_semaforo_ia{ext}",
        "economia": f"informe_economia_semaforo_ia{ext}",
        "inicio": f"informe_inicio_semaforo_ia{ext}",
    }
    default_name = default_names.get(report_type, f"informe_semaforo_ia{ext}")

    documents_dir = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or os.path.expanduser("~")

    selected_path, _ = QFileDialog.getSaveFileName(
        parent_widget,
        t("Guardar Informe", lang),
        os.path.join(documents_dir, default_name),
        file_filter,
    )

    if not selected_path:
        return ""

    if export_format == "json" and not selected_path.lower().endswith(".json"):
        selected_path += ".json"
    elif export_format in {"pdf", "both"} and not selected_path.lower().endswith(".pdf"):
        selected_path += ".pdf"

    return selected_path


def _apply_report_data(report_type, data, file_path, export_format, lang):
    """Actualiza el modulo de reporte y genera el PDF/JSON. Pensada para correr en un hilo aparte."""
    if report_type == 'eco':
        # Update eco module data
        if "kpis" in data:
            eco.REPORT["kpis"] = data["kpis"]
        if "details" in data:
            eco.REPORT["details"] = data["details"]
        if "logs" in data:
            eco.REPORT["logs"] = data["logs"]
        if "progress" in data:
            eco.REPORT["progress"] = data["progress"]
        if "exported_by" in data:
            eco.SHARED["exported_by"] = data["exported_by"]

        if "chart_values" in data:
            eco.REPORT["chart_values"] = data["chart_values"]
        if "chart_labels" in data:
            eco.REPORT["chart_labels"] = data["chart_labels"]
        eco.create_pdf_report(filename=file_path, export_format=export_format, lang=lang)

    elif report_type == 'economia':
        if "kpis" in data:
            economia.REPORT["kpis"] = data["kpis"]
        if "details" in data:
            economia.REPORT["details"] = data["details"]
        if "logs" in data:
            economia.REPORT["logs"] = data["logs"]
        if "progress" in data:
            economia.REPORT["progress"] = data["progress"]
        if "exported_by" in data:
            economia.SHARED["exported_by"] = data["exported_by"]
        if "chart_values" in data:
            economia.REPORT["chart_values"] = data["chart_values"]
        if "chart_labels" in data:
            economia.REPORT["chart_labels"] = data["chart_labels"]

        economia.create_pdf_report(filename=file_path, export_format=export_format, lang=lang)

    elif report_type == 'inicio':
        if "kpis" in data:
            inicio.REPORT["kpis"] = data["kpis"]
        if "details" in data:
            inicio.REPORT["details"] = data["details"]
        if "logs" in data:
            inicio.REPORT["logs"] = data["logs"]
        if "progress" in data:
            inicio.REPORT["progress"] = data["progress"]
        if "badge" in data:
            inicio.REPORT["badge"] = data["badge"]
        if "accent_color" in data:
            inicio.REPORT["accent_color"] = data["accent_color"]
        if "accent_color_dark" in data:
            inicio.REPORT["accent_color_dark"] = data["accent_color_dark"]
        if "accent_color_light" in data:
            inicio.REPORT["accent_color_light"] = data["accent_color_light"]
        if "exported_by" in data:
            inicio.SHARED["exported_by"] = data["exported_by"]
        if "chart_values" in data:
            inicio.REPORT["chart_values"] = data["chart_values"]
        if "chart_labels" in data:
            inicio.REPORT["chart_labels"] = data["chart_labels"]
        if "chart_colors" in data:
            inicio.REPORT["chart_colors"] = data["chart_colors"]

        inicio.create_pdf_report(filename=file_path, export_format=export_format, lang=lang)


class _ExportWorker(QObject):
    finished = Signal(bool, str)

    def __init__(self, report_type, data, file_path, export_format, lang):
        super().__init__()
        self._report_type = report_type
        self._data = data
        self._file_path = file_path
        self._export_format = export_format
        self._lang = lang

    def run(self):
        try:
            _apply_report_data(self._report_type, self._data, self._file_path, self._export_format, self._lang)
        except Exception as exc:
            self.finished.emit(False, str(exc))
        else:
            self.finished.emit(True, "")


class _ExportController(QObject):
    """Vive en el hilo principal: conectar una senal cruzando hilos a un slot de un
    QObject (en vez de a una funcion Python suelta) es lo que permite a Qt detectar
    la diferencia de hilo y encolar la llamada correctamente en el hilo de la UI."""

    def __init__(self, parent_widget, thread, worker, trigger_widget, lang, export_entry):
        super().__init__()
        self.parent_widget = parent_widget
        self.thread = thread
        self.worker = worker
        self.trigger_widget = trigger_widget
        self.lang = lang
        self.export_entry = export_entry

    @Slot(bool, str)
    def on_finished(self, success, error_message):
        QApplication.restoreOverrideCursor()
        if self.trigger_widget is not None:
            self.trigger_widget.setEnabled(True)

        if success:
            QMessageBox.information(
                self.parent_widget,
                t("Éxito", self.lang),
                t("El reporte ha sido generado y guardado exitosamente.", self.lang)
            )
        else:
            QMessageBox.critical(
                self.parent_widget,
                t("Error", self.lang),
                t("Ocurrió un error al generar el archivo:\n{error}", self.lang).format(error=error_message)
            )

        self.thread.quit()
        self.thread.wait()
        if self.export_entry in _active_exports:
            _active_exports.remove(self.export_entry)


def generate_and_save_report(parent_widget, report_type, data, export_format="pdf", lang=None, trigger_widget=None):
    """
    report_type: 'eco', 'economia' or 'inicio'
    data: dictionary containing dynamic info to update the report.
    lang: idioma a usar para el PDF/JSON (por defecto, el idioma actual de la UI).
    trigger_widget: boton que dispara la exportacion; se deshabilita mientras se genera
    el reporte en segundo plano para evitar que la UI se congele o se dispare dos veces.
    """
    if export_format not in {"pdf", "json", "both"}:
        raise ValueError("export_format debe ser 'pdf', 'json' o 'both'")

    lang = lang or i18n.get_language()

    file_path = _pick_export_target(parent_widget, report_type, export_format, lang=lang)

    if not file_path:
        return

    if trigger_widget is not None:
        trigger_widget.setEnabled(False)
    QApplication.setOverrideCursor(Qt.WaitCursor)

    thread = QThread(parent_widget)
    worker = _ExportWorker(report_type, data, file_path, export_format, lang)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)

    export_entry = {"thread": thread, "worker": worker}
    _active_exports.append(export_entry)

    # El controller se crea (y se queda) en el hilo principal: eso es lo que hace que
    # la conexion de abajo se encole automaticamente en vez de ejecutarse en el hilo worker.
    controller = _ExportController(parent_widget, thread, worker, trigger_widget, lang, export_entry)
    export_entry["controller"] = controller
    worker.finished.connect(controller.on_finished)
    thread.finished.connect(thread.deleteLater)
    thread.start()
