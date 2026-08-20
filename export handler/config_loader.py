import json
from datetime import datetime
from pathlib import Path


CONFIG_PATH = Path(__file__).with_name("report_config.json")


def load_config(report_name):
    with CONFIG_PATH.open(encoding="utf-8") as config_file:
        config = json.load(config_file)

    def to_rgb(color):
        color = color.lstrip("#")
        return tuple(int(color[index:index + 2], 16) for index in (0, 2, 4))

    colors = {name: to_rgb(value) for name, value in config["colors"].items()}
    return config["shared"], config[report_name], colors


def _sanitize_kpis(kpis):
    clean = []
    for item in kpis or []:
        if not isinstance(item, (list, tuple)) or len(item) < 6:
            continue
        _, _, title, value, unit, _ = item[:6]
        clean.append({
            "title": title,
            "value": value,
            "unit": unit,
        })
    return clean


def _sanitize_details(details):
    clean = []
    for item in details or []:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        key, value = item[0], item[1]
        clean.append({
            "key": key,
            "value": value,
        })
    return clean


def _sanitize_logs(logs):
    clean = []
    for item in logs or []:
        if isinstance(item, (list, tuple)) and item:
            clean.append(str(item[0]))
        elif isinstance(item, str):
            clean.append(item)
    return clean


def export_json_report(pdf_filename, report_name, shared, report):
    """Exporta solo datos funcionales del informe, sin estilos ni metadata visual."""
    json_filename = Path(pdf_filename).with_suffix(".json")

    payload = {
        "report_type": report_name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "product_name": shared.get("product_name"),
        "exported_by": shared.get("exported_by"),
        "subtitle": report.get("subtitle"),
        "kpis": _sanitize_kpis(report.get("kpis")),
        "chart": {
            "title": report.get("chart_title"),
            "values": report.get("chart_values", []),
            "labels": report.get("chart_labels", []),
        },
        "progress": {
            "title": report.get("progress_title"),
            "value": report.get("progress"),
            "badge": report.get("badge"),
        },
        "details": {
            "title": report.get("details_title"),
            "items": _sanitize_details(report.get("details")),
        },
        "logs": _sanitize_logs(report.get("logs")),
    }

    with json_filename.open("w", encoding="utf-8") as output_file:
        json.dump(payload, output_file, ensure_ascii=False, indent=2)

    return str(json_filename)
