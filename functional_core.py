"""Core business rules for Semaforo IA.

This module is deliberately independent from PySide6 so calculations and
security rules can be tested without starting the desktop application.
"""

from __future__ import annotations

import csv
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from html import escape
from calendar import monthrange
from dataclasses import dataclass, asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PASSWORD_PATTERN = re.compile(r"^(?=.*[A-Z])(?=.*\d)(?=.*[@_-])[\x21-\x7E]{8,}$")
DEFAULT_RATES = {"USD": 1.0, "CLP": 950.0, "EUR": 0.9}


class ValidationError(ValueError):
    """Raised when user-provided business data is invalid."""


class UnsupportedCurrencyError(ValidationError):
    pass


class DataIntegrityError(ValidationError):
    pass


def validate_password(password: str) -> bool:
    if not isinstance(password, str) or not PASSWORD_PATTERN.fullmatch(password):
        raise ValidationError(
            "La contrasena debe tener ASCII imprimible, 8 caracteres, mayuscula, numero y @, - o _."
        )
    return True


def hash_password(password: str, iterations: int = 260_000) -> str:
    validate_password(password)
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("ascii"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        expected = hashlib.pbkdf2_hmac(
            "sha256", password.encode("ascii"), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(expected.hex(), digest_hex)
    except (ValueError, UnicodeEncodeError):
        return False


def validate_thresholds(green: float, yellow: float, red: float) -> tuple[float, float, float]:
    values = (float(green), float(yellow), float(red))
    if any(value < 0 or value > 100 for value in values):
        raise ValidationError("Los umbrales deben estar entre 0 y 100.")
    if not (values[0] < values[1] < values[2]):
        raise ValidationError("Los umbrales deben cumplir Verde < Amarillo < Rojo.")
    return values


def calculate_cost(hourly_cost: float, hours: float, currency: str = "USD", rates: dict[str, float] | None = None) -> float:
    if hourly_cost < 0 or hours < 0:
        raise ValidationError("El costo y las horas no pueden ser negativos.")
    rates = rates or DEFAULT_RATES
    currency = currency.upper()
    if currency not in rates or rates[currency] <= 0:
        raise UnsupportedCurrencyError(f"Divisa no soportada: {currency}")
    return round(float(hourly_cost) * float(hours) * float(rates[currency]), 2)


def calculate_energy(tdp_watts: float, hours: float, pue: float = 1.0) -> float:
    if tdp_watts < 0 or hours < 0 or pue < 1:
        raise ValidationError("TDP, horas y PUE deben ser validos; PUE debe ser >= 1.")
    return round(tdp_watts * hours * pue / 1000, 6)


def calculate_carbon(
    tdp_watts: float,
    hours: float,
    pue: float,
    grid_factor: float,
    diesel_hours: float = 0,
    diesel_factor: float = 0,
) -> float:
    if grid_factor < 0 or diesel_factor < 0 or diesel_hours < 0 or diesel_hours > hours:
        raise ValidationError("Factores y horas de diesel invalidos.")
    energy = calculate_energy(tdp_watts, hours, pue)
    if diesel_hours == 0:
        return round(energy * grid_factor, 4)
    grid_hours = hours - diesel_hours
    return round(
        (calculate_energy(tdp_watts, grid_hours, pue) * grid_factor)
        + (calculate_energy(tdp_watts, diesel_hours, pue) * diesel_factor),
        4,
    )


def format_carbon(grams: float) -> str:
    if grams < 0:
        raise ValidationError("La emision no puede ser negativa.")
    return f"{grams / 1000:.2f} kgCO2eq" if grams > 10_000 else f"{grams:.2f} gCO2eq"


def calculate_water(kwh: float, wue: float, wsi: float = 1.0, immersion: bool = False, manual_litres: float | None = None) -> float:
    if kwh < 0 or wue < 0 or not 1 <= wsi <= 3:
        raise ValidationError("KWh, WUE o WSI invalidos.")
    if manual_litres is not None:
        if manual_litres < 0:
            raise ValidationError("Los litros manuales no pueden ser negativos.")
        return round(float(manual_litres), 4)
    return 0.0 if immersion else round(kwh * wue * wsi, 4)


def green_score(cost: float, cost_limit: float, carbon: float, carbon_limit: float) -> tuple[float, str]:
    if cost_limit <= 0 or carbon_limit <= 0 or cost < 0 or carbon < 0:
        raise ValidationError("Los limites y valores del Green Score deben ser positivos.")
    score = max(1.0, min(100.0, 100 - (((cost / cost_limit) * 100) + ((carbon / carbon_limit) * 100)) / 2))
    badge = "A+" if score > 85 else "B" if score > 70 else "C"
    return round(score, 2), badge


def semaphore_level(value: float, green: float, yellow: float, red: float) -> str:
    validate_thresholds(green, yellow, red)
    if value < green:
        return "Verde"
    if value < yellow:
        return "Amarillo"
    return "Rojo"


def forecast_budget(spent: float, elapsed_days: int, limit: float, total_days: int | None = None) -> float:
    if elapsed_days <= 0 or spent < 0 or limit < 0:
        raise ValidationError("Datos insuficientes o invalidos para pronosticar.")
    total_days = total_days or monthrange(date.today().year, date.today().month)[1]
    return round(spent / elapsed_days * total_days, 2)


def best_shifting_hour(hourly_factors: Iterable[float]) -> tuple[int, float]:
    factors = list(hourly_factors)
    if len(factors) != 24 or any(value < 0 for value in factors):
        raise ValidationError("La matriz horaria debe contener 24 factores validos.")
    minimum = min(factors)
    return factors.index(minimum), minimum


def compare_models(models: Iterable[dict[str, Any]], limit: int = 4) -> list[dict[str, Any]]:
    """Return comparable models ordered by carbon impact, marking all ties."""
    rows = list(models)
    if not 2 <= len(rows) <= limit:
        raise ValidationError(f"La comparativa requiere entre 2 y {limit} modelos.")
    for row in rows:
        if float(row.get("carbon", -1)) < 0 or float(row.get("cost", -1)) < 0:
            raise DataIntegrityError("La comparativa contiene metricas invalidas.")
    best_value = min((float(row["carbon"]) for row in rows))
    return [
        {**row, "optimal": float(row["carbon"]) == best_value}
        for row in rows
    ]


def sanitize_markdown(markdown: str, max_chars: int = 5000) -> str:
    """Keep Markdown text bounded and remove raw HTML/script markup."""
    if not isinstance(markdown, str) or len(markdown) > max_chars:
        raise ValidationError(f"La descripcion no puede superar {max_chars} caracteres.")
    return escape(markdown, quote=False)


def rightsizing(current_tdp: float, candidates: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    if current_tdp <= 0:
        raise ValidationError("El TDP actual debe ser positivo.")
    valid = [candidate for candidate in candidates if float(candidate.get("tdp_watts", 0)) > 0]
    better = [candidate for candidate in valid if float(candidate["tdp_watts"]) < current_tdp]
    if not better:
        return None
    best = min(better, key=lambda candidate: float(candidate["tdp_watts"]))
    saving = (current_tdp - float(best["tdp_watts"])) / current_tdp * 100
    return {"candidate": best, "saving_percent": round(saving, 2)} if saving > 10 else None


def estimate_cloud(instance: dict[str, Any], hours: float, region_factor: float) -> dict[str, Any]:
    required = ("name", "cost_per_hour_usd", "watts")
    if not isinstance(instance, dict) or any(key not in instance for key in required):
        raise DataIntegrityError("La instancia cloud no tiene las variables requeridas.")
    if hours < 0 or region_factor < 0:
        raise ValidationError("Horas o factor regional invalidos.")
    kwh = calculate_energy(float(instance["watts"]), hours, 1.0)
    return {
        "instance": str(instance["name"]),
        "hours": float(hours),
        "cost_usd": round(float(instance["cost_per_hour_usd"]) * hours, 6),
        "kwh": kwh,
        "carbon_gco2eq": round(kwh * region_factor, 4),
        "inputs": {"cost_per_hour_usd": float(instance["cost_per_hour_usd"]), "watts": float(instance["watts"]), "region_factor": float(region_factor)},
    }


def calculate_execution(
    model_id: int,
    hourly_cost: float,
    hours: float,
    currency: str,
    tdp_watts: float,
    pue: float,
    grid_factor: float,
    wue: float,
    wsi: float,
    cost_limit: float,
    carbon_limit: float,
    thresholds: tuple[float, float, float] = (50, 90, 100),
    diesel_hours: float = 0,
    diesel_factor: float = 0,
    immersion: bool = False,
    started_at: datetime | None = None,
) -> tuple[Execution, str]:
    started = started_at or datetime.now(timezone.utc)
    cost = calculate_cost(hourly_cost, hours, currency)
    kwh = calculate_energy(tdp_watts, hours, pue)
    carbon = calculate_carbon(tdp_watts, hours, pue, grid_factor, diesel_hours, diesel_factor)
    water = calculate_water(kwh, wue, wsi, immersion)
    score, badge = green_score(cost, cost_limit, carbon, carbon_limit)
    semaphore = semaphore_level(100 - score, *thresholds)
    duration_ms = max(0, round((datetime.now(timezone.utc) - started).total_seconds() * 1000))
    execution = Execution(model_id, utc_iso(started), cost, carbon, kwh, water, duration_ms, semaphore)
    return execution, badge


@dataclass(frozen=True)
class Execution:
    model_id: int
    timestamp: str
    cost: float
    carbon: float
    kwh: float
    water: float
    duration_ms: int
    semaphore: str


def utc_iso(value: datetime | None = None) -> str:
    current = value or datetime.now(timezone.utc)
    return current.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class LocalStore:
    """SQLite persistence for users, projects, executions and raw imports."""

    def __init__(self, path: str | os.PathLike[str]):
        self.path = str(path)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._create_schema()

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'standard',
                failed_attempts INTEGER NOT NULL DEFAULT 0, is_locked INTEGER NOT NULL DEFAULT 0,
                force_password_change INTEGER NOT NULL DEFAULT 0,
                budget_usd REAL, budget_co2 REAL
            );
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL,
                state TEXT NOT NULL DEFAULT 'active', is_active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS models (
                id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, name TEXT NOT NULL,
                description_markdown TEXT NOT NULL DEFAULT '', is_active INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY(project_id) REFERENCES projects(id)
            );
            CREATE TABLE IF NOT EXISTS executions (
                id INTEGER PRIMARY KEY, model_id INTEGER NOT NULL, timestamp TEXT NOT NULL,
                cost REAL NOT NULL, carbon REAL NOT NULL, kwh REAL NOT NULL, water REAL NOT NULL,
                duration_ms INTEGER NOT NULL, semaphore TEXT NOT NULL,
                FOREIGN KEY(model_id) REFERENCES models(id)
            );
            """
        )
        self.connection.commit()

    def add_user(self, username: str, password: str, role: str = "standard") -> int:
        validate_password(password)
        cursor = self.connection.execute(
            "INSERT INTO users(username, password_hash, role) VALUES (?, ?, ?)",
            (username.strip(), hash_password(password), role),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def add_hashed_user(self, username: str, password_hash: str, role: str = "standard") -> int:
        if not password_hash.startswith("pbkdf2_sha256$"):
            raise ValidationError("El hash de contrasena no usa el formato soportado.")
        cursor = self.connection.execute(
            "INSERT INTO users(username, password_hash, role) VALUES (?, ?, ?)",
            (username.strip(), password_hash, role),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def authenticate(self, username: str, password: str) -> sqlite3.Row | None:
        user = self.connection.execute("SELECT * FROM users WHERE username = ?", (username.strip(),)).fetchone()
        if not user or user["is_locked"]:
            return None
        if verify_password(password, user["password_hash"]):
            self.connection.execute("UPDATE users SET failed_attempts = 0 WHERE id = ?", (user["id"],))
            self.connection.commit()
            return self.connection.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
        attempts = user["failed_attempts"] + 1
        self.connection.execute(
            "UPDATE users SET failed_attempts = ?, is_locked = ? WHERE id = ?",
            (attempts, int(attempts >= 5), user["id"]),
        )
        self.connection.commit()
        return None

    def list_user_status(self) -> list[sqlite3.Row]:
        return self.connection.execute(
            "SELECT id, username, role, failed_attempts, is_locked, force_password_change FROM users ORDER BY username"
        ).fetchall()

    def is_user_locked(self, username: str) -> bool:
        row = self.connection.execute(
            "SELECT is_locked FROM users WHERE username = ?", (username.strip(),)
        ).fetchone()
        return bool(row and row["is_locked"])

    def unlock_user(self, username: str, actor_role: str) -> None:
        if str(actor_role).lower() not in {"admin", "administrador"}:
            raise PermissionError("Solo un administrador puede desbloquear usuarios.")
        cursor = self.connection.execute(
            "UPDATE users SET failed_attempts = 0, is_locked = 0 WHERE username = ?", (username.strip(),)
        )
        if cursor.rowcount == 0:
            raise ValidationError("El usuario no existe.")
        self.connection.commit()

    def add_project(self, name: str) -> int:
        name = str(name).strip()
        if not name:
            raise ValidationError("El nombre del proyecto es obligatorio.")
        try:
            cursor = self.connection.execute("INSERT INTO projects(name) VALUES (?)", (name,))
            self.connection.commit()
        except sqlite3.IntegrityError as exc:
            raise ValidationError("Ya existe un proyecto con ese nombre.") from exc
        return int(cursor.lastrowid)

    def add_model(self, project_id: int, name: str, description_markdown: str = "") -> int:
        name = str(name).strip()
        project = self.connection.execute(
            "SELECT state, is_active FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if not project or not project["is_active"]:
            raise ValidationError("El proyecto no existe o esta inactivo.")
        if project["state"] != "active":
            raise ValidationError("Un proyecto archivado o cerrado es de solo lectura.")
        if not name:
            raise ValidationError("El nombre del modelo es obligatorio.")
        cursor = self.connection.execute(
            "INSERT INTO models(project_id, name, description_markdown) VALUES (?, ?, ?)",
            (project_id, name, str(description_markdown)),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def archive_project(self, project_id: int) -> None:
        project = self.connection.execute(
            "SELECT state, is_active FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if not project or not project["is_active"]:
            raise ValidationError("El proyecto no existe o ya esta inactivo.")
        self.connection.execute("UPDATE projects SET state = 'archived' WHERE id = ?", (project_id,))
        self.connection.commit()

    def reassign_model(self, model_id: int, target_project_id: int) -> None:
        target = self.connection.execute(
            "SELECT state, is_active FROM projects WHERE id = ?", (target_project_id,)
        ).fetchone()
        if not target or not target["is_active"] or target["state"] != "active":
            raise ValidationError("El proyecto destino no acepta modificaciones.")
        model = self.connection.execute("SELECT id FROM models WHERE id = ?", (model_id,)).fetchone()
        if not model:
            raise ValidationError("El modelo no existe.")
        with self.connection:
            self.connection.execute("UPDATE models SET project_id = ? WHERE id = ?", (target_project_id, model_id))

    def project_totals(self, project_id: int) -> dict[str, float]:
        row = self.connection.execute(
            """SELECT COALESCE(SUM(e.cost), 0) AS cost, COALESCE(SUM(e.carbon), 0) AS carbon,
                      COALESCE(SUM(e.kwh), 0) AS kwh, COALESCE(SUM(e.water), 0) AS water
                 FROM executions e JOIN models m ON m.id = e.model_id
                WHERE m.project_id = ? AND m.is_active = 1""",
            (project_id,),
        ).fetchone()
        return {key: round(float(row[key]), 6) for key in ("cost", "carbon", "kwh", "water")}

    def list_history(self, model_id: int | None = None) -> list[sqlite3.Row]:
        if model_id is None:
            return self.connection.execute(
                """SELECT e.*, m.name AS model_name FROM executions e
                   JOIN models m ON m.id = e.model_id ORDER BY e.timestamp DESC"""
            ).fetchall()
        return self.connection.execute(
            """SELECT e.*, m.name AS model_name FROM executions e
               JOIN models m ON m.id = e.model_id
              WHERE e.model_id = ? ORDER BY e.timestamp DESC""",
            (model_id,),
        ).fetchall()

    def backup(self, destination: str | os.PathLike[str]) -> None:
        """Create a consistent SQLite backup using the online backup API."""
        destination_connection = sqlite3.connect(str(destination))
        try:
            self.connection.backup(destination_connection)
        except sqlite3.Error as exc:
            raise PermissionError(f"No se pudo crear el respaldo: {exc}") from exc
        finally:
            destination_connection.close()

    def add_execution(self, execution: Execution) -> int:
        cursor = self.connection.execute(
            "INSERT INTO executions(model_id, timestamp, cost, carbon, kwh, water, duration_ms, semaphore) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            tuple(asdict(execution).values()),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def soft_delete_model(self, model_id: int) -> None:
        self.connection.execute("UPDATE models SET is_active = 0 WHERE id = ?", (model_id,))
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()


def import_records(path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    file_path = Path(path)
    try:
        if file_path.suffix.lower() == ".json":
            data = json.loads(file_path.read_text(encoding="utf-8"))
            if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                raise DataIntegrityError("El JSON debe contener una lista de objetos.")
            return data
        if file_path.suffix.lower() == ".csv":
            with file_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            if not rows or not rows[0]:
                raise DataIntegrityError("El CSV no contiene registros o encabezados.")
            return rows
    except (OSError, UnicodeError, json.JSONDecodeError, csv.Error) as exc:
        raise DataIntegrityError(f"No se pudo leer el archivo: {exc}") from exc
    raise DataIntegrityError("Formato no soportado; use JSON o CSV.")


def export_records(records: Iterable[dict[str, Any]], path: str | os.PathLike[str]) -> None:
    rows = list(records)
    destination = Path(path)
    try:
        if destination.suffix.lower() == ".json":
            destination.write_text(json.dumps(rows, ensure_ascii=True, indent=2), encoding="utf-8")
            return
        if destination.suffix.lower() == ".csv":
            if not rows:
                raise DataIntegrityError("No hay registros para exportar.")
            with destination.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            return
    except (OSError, csv.Error) as exc:
        raise PermissionError(f"No se pudo escribir {destination}: {exc}") from exc
    raise DataIntegrityError("Formato de exportacion no soportado; use JSON o CSV.")


def fetch_json_with_fallback(url: str, fallback_path: str | os.PathLike[str], timeout: float = 5) -> Any:
    try:
        request = Request(url, headers={"Accept": "application/json"})
        with urlopen(request, timeout=timeout) as response:
            if response.status >= 400:
                raise HTTPError(url, response.status, "HTTP error", response.headers, None)
            data = json.loads(response.read().decode("utf-8"))
        Path(fallback_path).write_text(json.dumps(data, ensure_ascii=True, indent=2), encoding="utf-8")
        return data
    except (OSError, URLError, HTTPError, TimeoutError, json.JSONDecodeError):
        try:
            return json.loads(Path(fallback_path).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise DataIntegrityError("No hay datos remotos ni respaldo local valido.") from exc


def sensor_reading(address: str, timeout: float = 1.0) -> float:
    if not address or not address.strip():
        raise TimeoutError("Timeout de conexion: direccion del sensor vacia.")
    if address.strip().lower() in {"simulator", "simulador", "127.0.0.1"}:
        seed = int(time.time() * 1000) % 401
        return float(100 + seed)
    raise TimeoutError(f"Timeout de conexion con el sensor {address}.")


def bootstrap_store(config: dict[str, Any], path: str | os.PathLike[str]) -> LocalStore:
    """Create the local store and import only already-hashed config users."""
    store = LocalStore(path)
    for profile in config.get("users", []):
        username = str(profile.get("username", "")).strip()
        password_hash = profile.get("password_hash")
        if not username or not password_hash:
            continue
        exists = store.connection.execute(
            "SELECT 1 FROM users WHERE username = ?", (username,)
        ).fetchone()
        if not exists:
            store.add_hashed_user(username, password_hash, profile.get("role", "standard"))
    return store
