import os
import sys
from PySide6.QtWidgets import QMessageBox, QFileDialog

# Add export handler to path
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "export handler"))

try:
    import eco
    import economia
except Exception as e:
    print(f"Error importing export scripts: {e}")

def _pick_export_target(parent_widget, report_type, export_format):
    if export_format == "json":
        ext = ".json"
        file_filter = "Archivo JSON (*.json);;Todos los archivos (*)"
    else:
        ext = ".pdf"
        file_filter = "Archivo PDF (*.pdf);;Todos los archivos (*)"

    default_name = (
        f"informe_semaforo_ia{ext}"
        if report_type == "eco"
        else f"informe_economia_semaforo_ia{ext}"
    )

    selected_path, _ = QFileDialog.getSaveFileName(
        parent_widget,
        "Guardar Informe",
        os.path.join(os.path.expanduser("~"), default_name),
        file_filter,
    )

    if not selected_path:
        return ""

    if export_format == "json" and not selected_path.lower().endswith(".json"):
        selected_path += ".json"
    elif export_format in {"pdf", "both"} and not selected_path.lower().endswith(".pdf"):
        selected_path += ".pdf"

    return selected_path


def generate_and_save_report(parent_widget, report_type, data, export_format="pdf"):
    """
    report_type: 'eco' or 'economia'
    data: dictionary containing dynamic info to update the report.
    """
    if export_format not in {"pdf", "json", "both"}:
        raise ValueError("export_format debe ser 'pdf', 'json' o 'both'")

    file_path = _pick_export_target(parent_widget, report_type, export_format)

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
            if "exported_by" in data:
                eco.SHARED["exported_by"] = data["exported_by"]

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
            if "exported_by" in data:
                economia.SHARED["exported_by"] = data["exported_by"]
            if "chart_values" in data:
                economia.REPORT["chart_values"] = data["chart_values"]
            if "chart_labels" in data:
                economia.REPORT["chart_labels"] = data["chart_labels"]

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
