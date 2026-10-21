"""Explicit migration; originals remain untouched. No import from the cwd."""
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import uuid
from contextlib import closing

from app_paths import data_root


def sqlite_backup(source, destination):
    with closing(sqlite3.connect(f"{Path(source).resolve().as_uri()}?mode=ro", uri=True)) as original:
        if original.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("La base de origen no pasó integrity_check.")
        with closing(sqlite3.connect(destination)) as backup:
            original.backup(backup)
            if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("El respaldo no pasó integrity_check.")


def migrate_legacy(source, destination=None):
    source = Path(source).resolve()
    target = Path(destination or data_root()).resolve()
    if source == target or (source in target.parents and target != source / "userdata"):
        raise ValueError("Origen y destino de migración no válidos.")
    config = json.loads((source / "config.json").read_text(encoding="utf-8"))
    if not isinstance(config, dict) or not isinstance(config.get("users"), list):
        raise ValueError("La configuración antigua no contiene una lista válida de cuentas.")
    if any(not isinstance(user, dict) or not isinstance(user.get("username"), str)
           or not user["username"].strip() or not str(user.get("password_hash", "")).startswith("pbkdf2_sha256$")
           for user in config["users"]):
        raise ValueError("Las cuentas antiguas deben tener nombre y hash PBKDF2 válidos.")
    if any("password" in user for user in config["users"]):
        raise ValueError("Hay contraseñas en texto plano; conviértalas a hashes antes de migrar.")
    if (target / "config.json").exists():
        existing = json.loads((target / "config.json").read_text(encoding="utf-8"))
        from app_paths import resource_path
        defaults = json.loads(Path(resource_path("defaults", "config.json")).read_text(encoding="utf-8"))
        if existing != defaults:
            raise ValueError("El destino ya contiene configuración propia; no se sobrescribirá.")
    if (target / "models.json").exists() and json.loads((target / "models.json").read_text(encoding="utf-8")) != []:
        raise ValueError("El destino ya contiene modelos propios; no se sobrescribirá.")
    if (target / "semaforo.sqlite3").exists():
        raise ValueError("El destino ya contiene una base de datos; no se sobrescribirá.")
    target.mkdir(parents=True, exist_ok=True)
    backup = target / "backups" / ("migration-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8])
    backup.mkdir(parents=True)
    paths = [Path(name) for name in ("config.json", "models.json", "exchange_rates.json", "semaforo.sqlite3") if (source / name).is_file()]
    paths += [path.relative_to(source) for path in (source / "secrets").glob("*.key") if path.is_file()]
    plan = {relative: (source / relative).resolve() for relative in paths}
    for user in config["users"]:
        photo = user.get("profile_photo")
        if photo:
            candidate = (source / photo).resolve()
            if not candidate.is_file() and not Path(photo).is_absolute():
                candidate = (source / "_internal" / photo).resolve()
            if source not in candidate.parents or not candidate.is_file():
                raise ValueError("Foto fuera del origen o ausente; corrija su ruta antes de migrar.")
            relative = candidate.relative_to(source)
            if relative.parts[0] == "_internal":
                relative = Path(*relative.parts[1:])
            user["profile_photo"] = relative.as_posix()
            plan[relative] = candidate
    for relative, origin in plan.items():
        if source not in origin.parents or origin.is_symlink():
            raise ValueError("La migración no sigue enlaces fuera de la distribución antigua.")
        saved = backup / relative
        saved.parent.mkdir(parents=True, exist_ok=True)
        if relative.suffix == ".json":
            json.loads(origin.read_text(encoding="utf-8"))
        if relative.name == "semaforo.sqlite3":
            sqlite_backup(origin, saved)
        else:
            shutil.copy2(origin, saved)
    (backup / "normalized-config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    for relative in plan:
        destination_path = target / relative
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        if destination_path.exists() and relative.name not in {"config.json", "models.json"}:
            raise ValueError(f"El destino ya contiene {relative}; respaldo conservado en {backup}.")
        shutil.copy2(backup / relative, destination_path)
    from app_paths import atomic_json
    atomic_json(target / "config.json", config)
    (backup / "COMPLETED").write_text("Originals retained; no external exports imported.", encoding="ascii")
    return str(backup)


def backup_before_upgrade(path, schema_version=1):
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        return
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as connection:
        previous = connection.execute("PRAGMA user_version").fetchone()[0]
    if previous > schema_version:
        raise ValueError("Base de datos de una versión posterior; no se permite descender.")
    if previous < schema_version:
        directory = path.parent / "backups"
        directory.mkdir(exist_ok=True)
        sqlite_backup(path, directory / f"{path.stem}-schema-{previous}-to-{schema_version}-{uuid.uuid4().hex[:8]}.sqlite3")
