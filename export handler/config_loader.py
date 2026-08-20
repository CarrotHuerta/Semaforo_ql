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


def export_json_report(pdf_filename, report_name, shared, report):
    """Exporta los mismos datos del informe en un formato consumible por otros sistemas."""
    json_filename = Path(pdf_filename).with_suffix(".json")
    payload = {
        "report_type": report_name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "shared": shared,
        "report": report,
    }

    with json_filename.open("w", encoding="utf-8") as output_file:
        json.dump(payload, output_file, ensure_ascii=False, indent=2)

    return str(json_filename)
