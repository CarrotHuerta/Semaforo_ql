# Exportación de informes

Este proyecto genera informes de Semáforo IA en PDF, JSON o en ambos formatos.

## Archivos principales

- `eco.py`: informe de rendimiento ambiental.
- `economia.py`: informe de costos FinOps.
- `config_loader.py`: carga la configuración y exporta los datos JSON.
- `report_config.json`: textos, colores, KPIs, gráficos, detalles y logs de ambos informes.

## Uso desde la terminal

Ejecuta los comandos desde la carpeta del proyecto:

```powershell
python eco.py --format pdf
python eco.py --format json
python eco.py --format both

python economia.py --format pdf
python economia.py --format json
python economia.py --format both
```

El formato predeterminado es `both`, por lo que también funciona ejecutar:

```powershell
python eco.py
python economia.py
```

Los archivos generados son:

| Script | PDF | JSON |
|---|---|---|
| `eco.py` | `informe_semaforo_ia.pdf` | `informe_semaforo_ia.json` |
| `economia.py` | `informe_economia_semaforo_ia.pdf` | `informe_economia_semaforo_ia.json` |

Los gráficos PNG se crean únicamente durante la generación del PDF y se eliminan automáticamente al terminar.

## Uso desde otro `main.py`

Para controlar el formato desde Python, importa `create_pdf_report`:

```python
from eco import create_pdf_report as exportar_ambiental
from economia import create_pdf_report as exportar_economia

exportar_ambiental(export_format="pdf")
exportar_economia(export_format="json")
```

Los valores permitidos son:

- `"pdf"`: genera únicamente el PDF.
- `"json"`: genera únicamente el JSON.
- `"both"`: genera PDF y JSON.

También puedes indicar un nombre de PDF personalizado. El JSON usará automáticamente el mismo nombre con extensión `.json`:

```python
exportar_ambiental(
    filename="salidas/ambiental_2026.pdf",
    export_format="both",
)
```

Esto genera:

- `salidas/ambiental_2026.pdf`
- `salidas/ambiental_2026.json`

## Estructura del JSON

Cada JSON tiene esta estructura general:

```json
{
  "report_type": "eco",
  "generated_at": "2026-08-20T12:30:00",
  "shared": {
    "product_name": "Semáforo IA",
    "exported_by": "Nacha (Administrador)"
  },
  "report": {
    "subtitle": "Informe de Rendimiento Ambiental",
    "chart_values": [98, 44],
    "chart_colors": ["#10b981", "#6ee7b7"],
    "chart_labels": [
      "Entrenamiento: 98 gCO2eq",
      "Ejecución: 44 gCO2eq"
    ],
    "progress": 45,
    "kpis": [],
    "details": [],
    "logs": []
  }
}
```

El informe económico usa `"report_type": "economia"` y contiene los valores de `report_config.json` correspondientes a esa sección.

## Leer un JSON desde `main.py`

```python
import json
from pathlib import Path


def leer_informe(ruta):
    with Path(ruta).open(encoding="utf-8") as archivo:
        return json.load(archivo)


informe = leer_informe("informe_semaforo_ia.json")
print(informe["report_type"])
print(informe["report"]["kpis"])
```

## Configuración

Los datos visibles no deben cambiarse directamente en los scripts. Para modificar textos, KPIs, colores, leyendas o detalles, edita `report_config.json`. Ambos scripts leen ese archivo mediante `config_loader.py`.

## Requisitos

Instala las dependencias si todavía no están disponibles:

```powershell
pip install fpdf2 matplotlib
```

Validación rápida:

```powershell
python -m py_compile eco.py economia.py config_loader.py
```
