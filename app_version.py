import json
from pathlib import Path
from app_paths import resource_path

PRODUCT = json.loads(Path(resource_path("product.json")).read_text(encoding="utf-8"))
VERSION = PRODUCT["version"]
