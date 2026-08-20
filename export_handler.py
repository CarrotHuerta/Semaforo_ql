import os
import sys
from PySide6.QtWidgets import QMessageBox, QFileDialog, QInputDialog

# Add export handler to path
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "export handler"))

try:
    import eco
    import economia
except Exception as e:
    print(f"Error importing export scripts: {e}")

def generate_and_save_report(parent_widget, report_type, data):
    """
    report_type: 'eco' or 'economia'
    data: dictionary containing dynamic info to update the report.
    """
    # Ask for export format
    items = ["Ambos (PDF y JSON)", "Solo PDF", "Solo JSON"]
    format_choice, ok = QInputDialog.getItem(
        parent_widget, "Formato de Exportación",
        "Seleccione el formato a exportar:", items, 0, False
    )
    if not ok or not format_choice:
        return

    export_format = "both"
    if format_choice == "Solo PDF":
        export_format = "pdf"
    elif format_choice == "Solo JSON":
        export_format = "json"

    # Ask for file path
    ext = ".json" if export_format == "json" else ".pdf"
    default_name = f"informe_semaforo_ia{ext}" if report_type == 'eco' else f"informe_economia_semaforo_ia{ext}"

    file_path, _ = QFileDialog.getSaveFileName(
        parent_widget,
        "Guardar Informe",
        os.path.join(os.path.expanduser("~"), default_name),
        "Archivos (*.pdf *.json);;Todos los archivos (*)"
    )

    if not file_path:
        return

    # Update data based on report type
    try:
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

            if "chart_values" in data:
                eco.REPORT["chart_values"] = data["chart_values"]
            if "chart_labels" in data:
                eco.REPORT["chart_labels"] = data["chart_labels"]
            eco.create_pdf_report(filename=file_path, export_format=export_format)

        elif report_type == 'economia':
            if "kpis" in data:
                economia.REPORT["kpis"] = data["kpis"]
            if "details" in data:
                economia.REPORT["details"] = data["details"]
            if "logs" in data:
                economia.REPORT["logs"] = data["logs"]
            if "progress" in data:
                economia.REPORT["progress"] = data["progress"]

            economia.create_pdf_report(filename=file_path, export_format=export_format)

        QMessageBox.information(
            parent_widget,
            "Éxito",
            f"El reporte ha sido generado y guardado exitosamente."
        )

    except Exception as e:
        QMessageBox.critical(
            parent_widget,
            "Error",
            f"Ocurrió un error al generar el archivo:\n{e}"
        )
