"""One path policy shared by desktop, CLI and the optional HTTP server."""
from pathlib import Path
import json
import os
import sys
import tempfile

APP_ID = "SemaforoIA"
SOURCE_ROOT = Path(__file__).resolve().parent


def executable_dir():
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else SOURCE_ROOT


def is_portable():
    return (executable_dir() / "portable.flag").is_file()


def data_root():
    if is_portable():
        return executable_dir() / "userdata"
    if not getattr(sys, "frozen", False):
        return SOURCE_ROOT / "userdata"
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise OSError("LOCALAPPDATA no está definido; no se puede localizar Semáforo IA.")
    return Path(local) / APP_ID


def resource_path(*parts):
    return str(Path(getattr(sys, "_MEIPASS", SOURCE_ROOT)).joinpath(*parts))


def ensure_parent_dir(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def writable_path(*parts):
    root = data_root().resolve()
    target = root.joinpath(*parts).resolve()
    if target != root and root not in target.parents:
        raise ValueError("La ruta de datos sale de la carpeta de Semáforo IA.")
    return ensure_parent_dir(target)


def atomic_json(path, value):
    path = Path(ensure_parent_dir(path))
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".semaforo-", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def initialize_user_data():
    root = data_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=root):
            pass
        for name in ("config.json", "models.json"):
            target = root / name
            if not target.exists():
                content = Path(resource_path("defaults", name)).read_bytes()
                try:
                    with target.open("xb") as handle:
                        handle.write(content)
                except FileExistsError:
                    pass
        marker = root / ".semaforo-userdata"
        if not marker.exists():
            with marker.open("x", encoding="ascii") as handle:
                handle.write(APP_ID)
    except OSError as exc:
        mode = "portable (userdata junto al ejecutable)" if is_portable() else "de datos"
        raise OSError(f"No se puede escribir en la carpeta {mode}: {root}. Compruebe permisos o mueva la carpeta completa. {exc}") from exc
    return root
