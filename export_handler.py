import os
from PySide6.QtWidgets import QMessageBox

def generate_and_save_report(parent_widget, score, green_score):
    html_content = f"""<!DOCTYPE html>
<html>
<head>
<title>Reporte Semáforo IA</title>
<style>
body {{ font-family: sans-serif; background-color: #0b0b0b; color: white; margin: 20px; }}
h1 {{ color: #4ade80; }}
</style>
</head>
<body>
<h1>Reporte de Impacto - Semáforo IA</h1>
<p>Score de Impacto de Carbono: {score}</p>
<p>Green Score (0-100): {green_score}</p>
<!-- The HTML is generated from desktop application state -->
</body>
</html>"""

    base_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(base_dir, "reporte_semaforo.html")

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        QMessageBox.information(
            parent_widget,
            "Éxito",
            f"El reporte HTML ha sido generado y guardado exitosamente en:\\n{file_path}"
        )
    except Exception as e:
        QMessageBox.critical(
            parent_widget,
            "Error",
            f"Ocurrió un error al guardar el archivo:\\n{e}"
        )
