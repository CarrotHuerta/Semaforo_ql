import os
from PySide6.QtWidgets import QMessageBox

def generate_and_save_report(parent_widget, score, green_score, details):
    hardware = details.get("hardware", "N/A")
    provider = details.get("provider", "N/A")
    region = details.get("region", "N/A")
    energy = details.get("model_energy", "N/A")

    html_content = f"""<!DOCTYPE html>
<html>
<head>
<title>Reporte Semáforo IA</title>
<style>
body {{ font-family: sans-serif; background-color: #0b0b0b; color: white; margin: 20px; }}
h1 {{ color: #4ade80; }}
.details {{ margin-top: 20px; padding: 15px; border: 1px solid #333; border-radius: 8px; background-color: #141414; }}
</style>
</head>
<body>
<h1>Reporte de Impacto - Semáforo IA</h1>
<p><strong>Score de Impacto de Carbono:</strong> {score}</p>
<p><strong>Green Score (0-100):</strong> {green_score}</p>

<div class="details">
    <h3>Detalles de la Simulación</h3>
    <ul>
        <li><strong>Hardware (TDP):</strong> {hardware}</li>
        <li><strong>Proveedor Cloud:</strong> {provider}</li>
        <li><strong>Región Eléctrica:</strong> {region}</li>
        <li><strong>Energía del Modelo:</strong> {energy}</li>
    </ul>
</div>
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
