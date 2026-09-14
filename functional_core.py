"""Core business rules for Semaforo IA.

This module is deliberately independent from PySide6 so calculations and
security rules can be tested without starting the desktop application.
"""

from __future__ import annotations

import csv
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import sqlite3
import tempfile
import time
from decimal import Decimal, InvalidOperation
from html import escape
from calendar import monthrange
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import requests
from cryptography.fernet import Fernet, InvalidToken


PASSWORD_PATTERN = re.compile(r"^(?=.*[A-Z])(?=.*\d)(?=.*[@_-])[\x21-\x7E]{8,}$")
DEFAULT_RATES = {"USD": 1.0, "CLP": 950.0, "EUR": 0.9}
EXCHANGE_RATE_URL = "https://open.er-api.com/v6/latest/CLP"
SUPPORTED_CURRENCIES = ("CLP", "USD", "EUR", "BRL", "PEN", "ARS", "CNY", "GBP", "JPY", "CAD", "CHF")


class ValidationError(ValueError):
    """Raised when user-provided business data is invalid."""


class UnsupportedCurrencyError(ValidationError):
    pass


class DataIntegrityError(ValidationError):
    pass


class CircuitBreakerError(PermissionError):
    """Raised when a project quota or state forbids an execution."""


ERROR_CATALOG = {
    "ERR_QUOTA_FIN": {
        "cause": "La ejecucion proyectada supera la cuota financiera del proyecto.",
        "action": "Aumente la cuota, reduzca el costo estimado o solicite un override administrativo.",
    },
    "ERR_QUOTA_ECO": {
        "cause": "La ejecucion proyectada supera la cuota ecologica del proyecto.",
        "action": "Reduzca la duracion, migre a una region mas limpia o solicite un override administrativo.",
    },
    "ERR_USER_QUOTA_FIN": {
        "cause": "La ejecucion proyectada supera la cuota financiera del usuario.",
        "action": "Pida a un administrador que ajuste su cuota personal o reduzca el costo estimado.",
    },
    "ERR_USER_QUOTA_ECO": {
        "cause": "La ejecucion proyectada supera la cuota de CO2 del usuario.",
        "action": "Pida a un administrador que ajuste su cuota personal o reduzca las emisiones estimadas.",
    },
    "ERR_PROJECT_READONLY": {
        "cause": "El proyecto esta archivado, cerrado o inactivo.",
        "action": "Active otro proyecto o pida a un administrador que reabra el actual.",
    },
    "ERR_LOCKED_PARAM": {
        "cause": "Uno o mas parametros estan bloqueados por el entorno Cloud seleccionado.",
        "action": "Desactive el entorno Cloud o ajuste solo los parametros desbloqueados.",
    },
    "ERR_IO": {
        "cause": "No se pudo leer o escribir un archivo local (permisos, bloqueo o disco).",
        "action": "Cierre programas que usen el archivo, verifique permisos y reintente.",
    },
    "ERR_NET": {
        "cause": "Fallo de red o el servicio remoto no respondio a tiempo.",
        "action": "Verifique la conexion, la URL configurada y reintente; se usara la cache local si existe.",
    },
    "ERR_DB": {
        "cause": "La base de datos local esta corrupta o inaccesible.",
        "action": "Restaure un respaldo validado desde Ajustes o contacte a un administrador.",
    },
    "ERR_DATA": {
        "cause": "Los datos de entrada no cumplen el formato o esquema requerido.",
        "action": "Corrija los campos marcados y vuelva a intentar la operacion.",
    },
}


def describe_error(code: str, detail: str = "") -> dict[str, str]:
    """Return a guided error payload (code, cause, action) for the given catalog code."""
    entry = ERROR_CATALOG.get(code)
    if not entry:
        entry = {"cause": "Error no catalogado.", "action": "Revise el detalle tecnico y reintente."}
        code = "ERR_UNKNOWN"
    return {"code": code, "cause": entry["cause"], "action": entry["action"], "detail": str(detail)}


def assert_parameters_unlocked(locked: Iterable[str], required: Iterable[str]) -> None:
    """Reject an action that needs parameters currently locked by the active environment."""
    locked_set = {str(item).strip().lower() for item in locked}
    blocked = sorted(str(item) for item in required if str(item).strip().lower() in locked_set)
    if blocked:
        raise ValidationError(
            "Parametros bloqueados por el entorno activo: " + ", ".join(blocked) + "."
        )


def paginate(records: Iterable[dict[str, Any]], page: int, page_size: int = 10) -> dict[str, Any]:
    """Slice records into a validated page; pages are 1-based."""
    rows = list(records)
    if page_size <= 0:
        raise ValidationError("El tamano de pagina debe ser positivo.")
    total = len(rows)
    pages = max(1, -(-total // page_size))
    page = min(max(1, int(page)), pages)
    start = (page - 1) * page_size
    return {"items": rows[start:start + page_size], "page": page, "pages": pages, "total": total}


LOW_CARBON_THRESHOLD = 100.0


def is_low_carbon_region(intensity: float | None, threshold: float = LOW_CARBON_THRESHOLD) -> bool:
    """A region qualifies as low-carbon when its factor is a known value under the threshold."""
    if intensity is None:
        return False
    try:
        return 0 <= float(intensity) < threshold
    except (TypeError, ValueError):
        return False


def detect_new_hardware(detected: dict[str, str], catalog_names: Iterable[str]) -> list[str]:
    """Return detected component names that do not appear in the local catalog."""
    known = {str(name).strip().lower() for name in catalog_names if str(name).strip()}
    unknown = []
    for key in ("cpu", "gpu", "ram"):
        name = str(detected.get(key, "")).strip()
        if not name or name.lower() in {"no detectado", "not detected"}:
            continue
        if not any(name.lower() in entry or entry in name.lower() for entry in known):
            unknown.append(name)
    return unknown


IMMERSION_FLUID_COMPATIBILITY = {
    "aceite mineral": {"CPU", "GPU"},
    "fluido sintetico": {"CPU", "GPU", "RAM"},
    "fluorocarbono": {"CPU", "GPU", "RAM"},
}


def check_immersion_compatibility(components: Iterable[str], fluid: str) -> list[str]:
    """Return the components NOT compatible with the selected immersion fluid."""
    key = str(fluid).strip().lower()
    if key not in IMMERSION_FLUID_COMPATIBILITY:
        raise ValidationError(f"Fluido de inmersion no soportado: {fluid}")
    allowed = IMMERSION_FLUID_COMPATIBILITY[key]
    return sorted({str(c).strip().upper() for c in components if str(c).strip()} - allowed)


def parse_hydro_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate flow-meter/CSV water records with timestamp and litres columns."""
    parsed = []
    for index, record in enumerate(records, start=1):
        raw_ts = str(record.get("timestamp", "")).strip()
        try:
            timestamp = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
        except ValueError as exc:
            raise DataIntegrityError(f"El registro hidrico {index} tiene un timestamp invalido.") from exc
        try:
            litres = float(record.get("litres", record.get("litros", "")))
        except (TypeError, ValueError) as exc:
            raise DataIntegrityError(f"El registro hidrico {index} no tiene litros validos.") from exc
        if litres < 0:
            raise DataIntegrityError(f"El registro hidrico {index} tiene litros negativos.")
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        parsed.append({"timestamp": timestamp, "litres": litres})
    if not parsed:
        raise DataIntegrityError("El archivo hidrico no contiene registros.")
    return parsed


def detect_hydro_desync(records: list[dict[str, Any]], max_gap_minutes: float = 120.0) -> list[str]:
    """Detect out-of-order timestamps or gaps larger than the tolerated window."""
    if max_gap_minutes <= 0:
        raise ValidationError("La tolerancia de desincronizacion debe ser positiva.")
    issues = []
    previous = None
    for index, record in enumerate(records, start=1):
        current = record["timestamp"]
        if previous is not None:
            delta = (current - previous).total_seconds() / 60
            if delta < 0:
                issues.append(f"Registro {index}: timestamp anterior al previo (desincronizacion horaria).")
            elif delta > max_gap_minutes:
                issues.append(f"Registro {index}: brecha de {delta:.0f} min supera la tolerancia.")
        previous = current
    return issues


def hydro_total_litres(records: list[dict[str, Any]]) -> float:
    return round(sum(record["litres"] for record in records), 4)


def flow_meter_reading(address: str, timeout: float = 1.0) -> float:
    """Read litres/hour from a flow meter; only the local simulator is reachable offline."""
    if not address or not str(address).strip():
        raise TimeoutError("Timeout de conexion: direccion del flujometro vacia.")
    if str(address).strip().lower() in {"simulator", "simulador", "127.0.0.1"}:
        seed = int(time.time() * 1000) % 191
        return round(float(10 + seed) / 10, 2)
    raise TimeoutError(f"Timeout de conexion con el flujometro {address}.")


def primary_energy_source(mix: dict[str, float]) -> dict[str, Any]:
    """Identify the dominant energy source; ties are reported as 'Mix Equilibrado'."""
    cleaned = {}
    for name, value in mix.items():
        label = str(name).strip()
        try:
            percent = float(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"El porcentaje de {label} no es valido.") from exc
        if percent < 0:
            raise ValidationError(f"El porcentaje de {label} no puede ser negativo.")
        if label:
            cleaned[label] = percent
    total = sum(cleaned.values())
    if not cleaned or total <= 0:
        raise ValidationError("La matriz energetica no contiene porcentajes positivos.")
    normalized = {name: round(value / total * 100, 2) for name, value in cleaned.items()}
    top_value = max(normalized.values())
    leaders = sorted(name for name, value in normalized.items() if value == top_value)
    tied = len(leaders) > 1
    return {
        "label": "Mix Equilibrado" if tied else leaders[0],
        "percent": top_value,
        "tied": tied,
        "breakdown": normalized,
    }


MIN_TRUSTED_YEAR = 2020
MAX_TRUSTED_YEAR = 2100


def clock_is_trusted(value: datetime | None = None) -> bool:
    """Detect an obviously corrupt OS clock before emitting normative timestamps."""
    current = value or datetime.now(timezone.utc)
    return MIN_TRUSTED_YEAR <= current.year <= MAX_TRUSTED_YEAR


def normative_date(value: datetime | None = None) -> str:
    """Return a strict YYYY-MM-DD date in UTC, refusing corrupt clocks."""
    current = value or datetime.now(timezone.utc)
    if not clock_is_trusted(current):
        raise ValidationError("El reloj del sistema es invalido; corrija la fecha del equipo.")
    return current.astimezone(timezone.utc).strftime("%Y-%m-%d")


def format_local_timestamp(utc_text: str) -> str:
    """Convert a stored UTC timestamp to local time with explicit offset for the UI."""
    try:
        parsed = datetime.strptime(str(utc_text).strip(), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return str(utc_text)
    local = parsed.replace(tzinfo=timezone.utc).astimezone()
    offset = local.strftime("%z")
    return f"{local.strftime('%Y-%m-%d %H:%M:%S')} UTC{offset[:3]}:{offset[3:]}" if offset else local.strftime("%Y-%m-%d %H:%M:%S")


def predict_limit_breach(
    history: Iterable[dict[str, Any]],
    limit: float,
    metric: str,
    as_of: datetime | None = None,
) -> datetime | None:
    """Extrapolate the UTC date when a cumulative metric reaches its limit."""
    if limit <= 0 or metric not in {"cost", "carbon"}:
        raise ValidationError("El limite debe ser positivo y la metrica debe ser cost o carbon.")
    rows = sorted(history, key=lambda row: str(row.get("timestamp", "")))
    if len(rows) < 2:
        return None
    try:
        first = datetime.fromisoformat(str(rows[0]["timestamp"]).replace("Z", "+00:00"))
        last = datetime.fromisoformat(str(rows[-1]["timestamp"]).replace("Z", "+00:00"))
        total = sum(float(row[metric]) for row in rows)
    except (KeyError, TypeError, ValueError) as exc:
        raise DataIntegrityError("El historial no permite calcular una proyeccion.") from exc
    if total < 0:
        raise DataIntegrityError("El historial contiene valores negativos.")
    current = as_of or datetime.now(timezone.utc)
    if first.tzinfo is None:
        first = first.replace(tzinfo=timezone.utc)
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    if last <= first:
        return None
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    if total >= limit:
        return current.astimezone(timezone.utc)
    elapsed_days = max((current - first).total_seconds() / 86400, 1.0)
    daily_rate = total / elapsed_days
    if daily_rate <= 0:
        return None
    return current.astimezone(timezone.utc) + timedelta(days=(limit - total) / daily_rate)


def predict_execution_duration(history: Iterable[dict[str, Any]], minimum_samples: int = 3) -> dict[str, Any] | None:
    """Forecast the next duration with a least-squares trend over valid historical sessions."""
    if minimum_samples < 3:
        raise ValidationError("El mínimo estadístico debe ser de al menos tres sesiones.")
    durations = []
    for row in history:
        try:
            value = float(row["duration_ms"])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(value) and value > 0:
            durations.append(value)
    if len(durations) < minimum_samples:
        return None
    count = len(durations)
    mean_x = (count - 1) / 2
    mean_y = sum(durations) / count
    denominator = sum((index - mean_x) ** 2 for index in range(count))
    slope = sum((index - mean_x) * (value - mean_y) for index, value in enumerate(durations)) / denominator
    predicted = max(1.0, mean_y + slope * (count - mean_x))
    variance = sum((value - mean_y) ** 2 for value in durations) / count
    deviation = math.sqrt(variance)
    return {
        "predicted_ms": round(predicted),
        "sample_size": count,
        "trend_ms_per_run": round(slope, 2),
        "deviation_ms": round(deviation, 2),
    }


def capacity_plan(
    annual_runtime_hours: float,
    current_tdp_watts: float,
    candidates: Iterable[dict[str, Any]],
    energy_price_per_kwh: float,
    pue: float = 1.0,
    grid_factor: float = 0.0,
    max_payback_years: float = 3.0,
) -> dict[str, Any] | None:
    """Recommend replacement only when energy savings repay its acquisition cost."""
    values = (annual_runtime_hours, current_tdp_watts, energy_price_per_kwh, grid_factor)
    if any(value < 0 for value in values) or current_tdp_watts == 0 or pue < 1 or max_payback_years <= 0:
        raise ValidationError("Los datos de capacity planning no son validos.")
    plans = []
    for candidate in candidates:
        try:
            tdp = float(candidate["tdp_watts"])
            acquisition_cost = float(candidate["acquisition_cost"])
        except (KeyError, TypeError, ValueError) as exc:
            raise DataIntegrityError("Un candidato no contiene TDP y costo validos.") from exc
        if tdp <= 0 or acquisition_cost < 0 or tdp >= current_tdp_watts:
            continue
        annual_kwh_saving = (current_tdp_watts - tdp) * annual_runtime_hours * pue / 1000
        annual_cost_saving = annual_kwh_saving * energy_price_per_kwh
        payback = acquisition_cost / annual_cost_saving if annual_cost_saving > 0 else float("inf")
        saving_percent = (current_tdp_watts - tdp) / current_tdp_watts * 100
        if saving_percent > 10 and payback <= max_payback_years:
            plans.append({
                "candidate": candidate,
                "saving_percent": round(saving_percent, 2),
                "annual_kwh_saving": round(annual_kwh_saving, 4),
                "annual_cost_saving": round(annual_cost_saving, 2),
                "annual_carbon_saving": round(annual_kwh_saving * grid_factor, 4),
                "payback_years": round(payback, 2),
            })
    return max(plans, key=lambda plan: plan["annual_cost_saving"] - float(plan["candidate"]["acquisition_cost"]) / max_payback_years) if plans else None


def liquid_cooling_roi(
    annual_kwh: float,
    current_pue: float,
    immersion_pue: float,
    energy_price_per_kwh: float,
    investment: float,
) -> dict[str, float | bool]:
    if annual_kwh < 0 or energy_price_per_kwh < 0 or investment < 0 or current_pue < 1 or immersion_pue < 1:
        raise ValidationError("Los datos de ROI de inmersion no son validos.")
    saved_kwh = annual_kwh * max(0.0, current_pue - immersion_pue)
    annual_saving = saved_kwh * energy_price_per_kwh
    payback = investment / annual_saving if annual_saving else float("inf")
    return {
        "annual_kwh_saving": round(saved_kwh, 4),
        "annual_cost_saving": round(annual_saving, 2),
        "payback_years": round(payback, 2) if payback != float("inf") else payback,
        "viable": payback <= 5,
    }


def compare_cooling_scenarios(baseline: dict[str, Any], immersion: dict[str, Any]) -> dict[str, Any]:
    """Compare cooling-only clones and reject unrelated structural differences."""
    for key in ("hardware", "annual_kwh", "energy_price_per_kwh"):
        if baseline.get(key) != immersion.get(key):
            raise ValidationError(f"Los escenarios divergen en {key}; la comparación térmica no es válida.")
    result = liquid_cooling_roi(
        float(baseline["annual_kwh"]), float(baseline["pue"]), float(immersion["pue"]),
        float(baseline["energy_price_per_kwh"]), float(immersion.get("investment", 0)),
    )
    baseline_water = float(baseline["annual_kwh"]) * float(baseline.get("wue", 0))
    immersion_water = float(immersion["annual_kwh"]) * float(immersion.get("wue", 0))
    return {**result, "annual_water_saving_litres": round(max(0.0, baseline_water - immersion_water), 4)}


def fetch_exchange_rates(
    fallback_path: str | os.PathLike[str] | None = None,
    timeout: float = 5.0,
    url: str = EXCHANGE_RATE_URL,
) -> dict[str, float]:
    """Fetch CLP-based rates and retain the last valid response locally."""
    data = None
    try:
        response = requests.get(url, timeout=timeout, headers={"Accept": "application/json"})
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or data.get("result") != "success":
            raise DataIntegrityError("La API de divisas devolvio una respuesta invalida.")
        rates = data.get("rates")
        if not isinstance(rates, dict):
            raise DataIntegrityError("La API de divisas no contiene tasas.")
        parsed = {"CLP": 1.0}
        for currency in SUPPORTED_CURRENCIES:
            if currency == "CLP":
                continue
            value = rates.get(currency)
            try:
                parsed[currency] = float(Decimal(str(value)))
            except (InvalidOperation, TypeError, ValueError):
                raise DataIntegrityError(f"La tasa {currency} no es valida.")
            if parsed[currency] <= 0:
                raise DataIntegrityError(f"La tasa {currency} debe ser positiva.")
        data = {"result": "success", "base_code": "CLP", "rates": parsed}
        if fallback_path:
            Path(fallback_path).write_text(json.dumps(data, ensure_ascii=True, indent=2), encoding="utf-8")
        return parsed
    except (requests.RequestException, OSError, ValueError, DataIntegrityError) as exc:
        if fallback_path:
            try:
                cached = json.loads(Path(fallback_path).read_text(encoding="utf-8"))
                rates = cached.get("rates") if isinstance(cached, dict) else None
                if isinstance(rates, dict):
                    return fetch_exchange_rates_from_mapping(rates)
            except (OSError, UnicodeError, json.JSONDecodeError, AttributeError, DataIntegrityError):
                pass
        raise DataIntegrityError(f"No se pudieron obtener tasas de divisas: {exc}") from exc


def fetch_exchange_rates_from_mapping(rates: dict[str, Any]) -> dict[str, float]:
    """Validate a cached CLP-based rate mapping without making a network call."""
    parsed = {"CLP": 1.0}
    for currency in SUPPORTED_CURRENCIES:
        if currency == "CLP":
            continue
        try:
            value = float(Decimal(str(rates[currency])))
        except (KeyError, InvalidOperation, TypeError, ValueError) as exc:
            raise DataIntegrityError(f"La tasa {currency} no es valida.") from exc
        if value <= 0:
            raise DataIntegrityError(f"La tasa {currency} debe ser positiva.")
        parsed[currency] = value
    return parsed


def convert_clp(amount_clp: float, currency: str, rates: dict[str, float]) -> tuple[float, float]:
    """Return foreign amount and CLP cost of one unit of that currency."""
    if amount_clp < 0:
        raise ValidationError("El monto en CLP no puede ser negativo.")
    currency = currency.upper()
    if currency not in SUPPORTED_CURRENCIES:
        raise UnsupportedCurrencyError(f"Divisa no soportada: {currency}")
    rate = float(rates[currency])
    if rate <= 0:
        raise ValidationError("La tasa de cambio debe ser positiva.")
    return round(amount_clp * rate, 2), round(1 / rate, 8)


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


def _normalize_security_answer(answer: str) -> str:
    """Case-insensitive, whitespace-insensitive normalization for security answers."""
    return " ".join(str(answer).strip().casefold().split())


def hash_security_answer(answer: str, iterations: int = 260_000) -> str:
    normalized = _normalize_security_answer(answer)
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", normalized.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_security_answer(answer: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        normalized = _normalize_security_answer(answer)
        expected = hashlib.pbkdf2_hmac(
            "sha256", normalized.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
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
    if immersion:
        return 0.0
    if manual_litres is not None:
        if manual_litres < 0:
            raise ValidationError("Los litros manuales no pueden ser negativos.")
        return round(float(manual_litres), 4)
    return round(kwh * wue * wsi, 4)


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


def carbon_shifting_recommendation(
    hourly_factors: Iterable[float], current_hour: int
) -> dict[str, float | int] | None:
    factors = [float(value) for value in hourly_factors]
    best_hour, best_factor = best_shifting_hour(factors)
    if not 0 <= current_hour <= 23:
        raise ValidationError("La hora actual debe estar entre 0 y 23.")
    current_factor = factors[current_hour]
    if current_factor <= 0 or max(factors) - min(factors) <= 1e-12:
        return None
    saving_percent = (current_factor - best_factor) / current_factor * 100
    if saving_percent <= 0:
        return None
    return {
        "current_hour": current_hour,
        "recommended_hour": best_hour,
        "current_factor": current_factor,
        "recommended_factor": best_factor,
        "saving_percent": round(saving_percent, 2),
    }


def software_efficiency_recommendations(
    duration_ms: int,
    cpu_utilization: float | None = None,
    memory_utilization: float | None = None,
    batch_size: int | None = None,
) -> list[dict[str, str]]:
    """Return conservative software-efficiency findings from explicit runtime metrics."""
    if duration_ms < 0:
        raise ValidationError("La duracion no puede ser negativa.")
    for value, label in (
        (cpu_utilization, "CPU"),
        (memory_utilization, "RAM"),
    ):
        if value is not None and not 0 <= value <= 100:
            raise ValidationError(f"La utilizacion de {label} debe estar entre 0 y 100.")
    if batch_size is not None and batch_size <= 0:
        raise ValidationError("El tamano de lote debe ser positivo.")

    findings = []
    if duration_ms > 600_000:
        findings.append({
            "code": "LONG_RUNTIME",
            "title": "Duracion elevada",
            "recommendation": "Revisar early stopping, cache y paralelismo antes de aumentar hardware.",
        })
    if cpu_utilization is not None and cpu_utilization < 50 and duration_ms > 120_000:
        findings.append({
            "code": "LOW_CPU_UTILIZATION",
            "title": "CPU subutilizada",
            "recommendation": "Revisar esperas de I/O, serializacion o tamano de lote.",
        })
    if memory_utilization is not None and memory_utilization > 90:
        findings.append({
            "code": "HIGH_MEMORY_PRESSURE",
            "title": "Presion de memoria",
            "recommendation": "Reducir el tamano de lote o liberar datos intermedios antes de continuar.",
        })
    if batch_size == 1 and duration_ms > 120_000:
        findings.append({
            "code": "SINGLE_ITEM_BATCH",
            "title": "Lote unitario",
            "recommendation": "Evaluar procesamiento por lotes para reducir el costo fijo por iteracion.",
        })
    return findings


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


def render_markdown(markdown: str, max_chars: int = 5000) -> str:
    """Render a small safe Markdown subset suitable for a Qt rich-text widget."""
    source = sanitize_markdown(markdown, max_chars=max_chars)
    rendered = []
    in_list = False
    for raw_line in source.splitlines():
        line = raw_line.strip()
        if not line:
            if in_list:
                rendered.append("</ul>")
                in_list = False
            continue
        heading = re.match(r"^(#{1,3})\s+(.+)$", line)
        bullet = re.match(r"^(?:[-*])\s+(.+)$", line)
        if bullet:
            if not in_list:
                rendered.append("<ul>")
                in_list = True
            rendered.append(f"<li>{_render_inline_markdown(bullet.group(1))}</li>")
        else:
            if in_list:
                rendered.append("</ul>")
                in_list = False
            if heading:
                level = len(heading.group(1))
                rendered.append(f"<h{level}>{_render_inline_markdown(heading.group(2))}</h{level}>")
            else:
                rendered.append(f"<p>{_render_inline_markdown(line)}</p>")
    if in_list:
        rendered.append("</ul>")
    return "".join(rendered)


def _render_inline_markdown(value: str) -> str:
    value = re.sub(r"\[([^]]+)\]\((https?://[^\s)]+)\)", r'<a href="\2">\1</a>', value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", value)
    value = re.sub(r"__([^_]+)__", r"<strong>\1</strong>", value)
    value = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", value)
    return value


def component_percentages(components: dict[str, float]) -> dict[str, float]:
    """Normalize positive CPU/GPU/RAM values to percentages that sum to 100."""
    allowed = ("CPU", "GPU", "RAM")
    values = {name: max(0.0, float(components.get(name, 0.0))) for name in allowed}
    total = sum(values.values())
    if total <= 0:
        return {name: 0.0 for name in allowed}
    percentages = {name: round(value / total * 100, 2) for name, value in values.items()}
    largest = max(allowed, key=lambda name: percentages[name])
    percentages[largest] = round(percentages[largest] + 100 - sum(percentages.values()), 2)
    return percentages


def budget_percentage(spent: float, limit: float) -> int | None:
    """Return a capped budget percentage, or None when no finite limit exists."""
    if spent < 0 or limit < 0:
        raise ValidationError("El gasto y el limite no pueden ser negativos.")
    if limit == 0:
        return None
    return max(0, min(100, round(spent / limit * 100)))


class ApiKeyError(ValidationError):
    """Raised when a financial/cloud billing API key is invalid or cannot be decrypted."""


API_KEY_PATTERN = re.compile(r"^[A-Za-z0-9/_+=-]{16,128}$")


def validate_api_key_format(api_key: str) -> str:
    """Reject empty, too short/long or malformed API keys before they are encrypted."""
    if not isinstance(api_key, str) or not API_KEY_PATTERN.match(api_key.strip()):
        raise ApiKeyError("La API Key debe tener entre 16 y 128 caracteres alfanumericos validos.")
    return api_key.strip()


def load_or_create_encryption_key(key_path: str | os.PathLike[str]) -> bytes:
    """Load the local Fernet key used to encrypt secrets, creating it on first use."""
    path = Path(key_path)
    if path.exists():
        return path.read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    path.write_bytes(key)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key


def encrypt_api_key(api_key: str, key_path: str | os.PathLike[str]) -> str:
    """Encrypt an API key with a locally stored key; the plaintext is never persisted."""
    validated = validate_api_key_format(api_key)
    key = load_or_create_encryption_key(key_path)
    token = Fernet(key).encrypt(validated.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_api_key(token: str, key_path: str | os.PathLike[str]) -> str:
    """Decrypt a previously stored API key token, raising ApiKeyError on failure."""
    path = Path(key_path)
    if not token or not path.exists():
        raise ApiKeyError("No hay una API Key almacenada localmente.")
    key = path.read_bytes()
    try:
        return Fernet(key).decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ApiKeyError("La API Key almacenada esta corrupta o la llave local cambio.") from exc


def mask_api_key(api_key: str) -> str:
    """Return a masked preview (e.g. ****ab12) safe for on-screen display."""
    if not api_key or len(api_key) < 4:
        return "****"
    return f"****{api_key[-4:]}"


CPU_TIER_LABELS = {0: "Entrada", 1: "Basico", 2: "Medio", 3: "Alto", 4: "Extremo"}

# Ordered from highest to lowest so specific tokens (e.g. "m3 max") win over
# the more generic pattern of the tier below (e.g. plain "m3").
CPU_TIER_PATTERNS = (
    (4, re.compile(r"\bi9\b|ryzen\s*9|ultra\s*9|threadripper|\bxeon\b|\bm\d+\s*(max|ultra)\b", re.IGNORECASE)),
    (3, re.compile(r"\bi7\b|ryzen\s*7|ultra\s*7|\bm\d+\s*pro\b", re.IGNORECASE)),
    (2, re.compile(r"\bi5\b|ryzen\s*5|ultra\s*5|fx-8|\bm\d+\b", re.IGNORECASE)),
    (1, re.compile(r"\bi3\b|ryzen\s*3|fx-6|pentium\s*gold", re.IGNORECASE)),
    (0, re.compile(r"\batom\b|\bceleron\b|\bpentium\b|\bathlon\b", re.IGNORECASE)),
)


def classify_cpu_tier(model_name: str) -> int:
    """Classify a CPU model name into a rough performance tier (0=entrada .. 4=extremo)."""
    text = str(model_name or "")
    for tier, pattern in CPU_TIER_PATTERNS:
        if pattern.search(text):
            return tier
    return 2


def rightsizing(
    current_tdp: float,
    candidates: Iterable[dict[str, Any]],
    current_performance: float | None = None,
    min_performance_ratio: float = 1.0,
) -> dict[str, Any] | None:
    if current_tdp <= 0:
        raise ValidationError("El TDP actual debe ser positivo.")
    valid = [candidate for candidate in candidates if float(candidate.get("tdp_watts", 0)) > 0]
    better = [candidate for candidate in valid if float(candidate["tdp_watts"]) < current_tdp]
    if current_performance is not None:
        threshold = current_performance * min_performance_ratio
        better = [
            candidate for candidate in better
            if candidate.get("performance_score") is None or candidate["performance_score"] >= threshold
        ]
    if not better:
        return None
    best = min(better, key=lambda candidate: float(candidate["tdp_watts"]))
    saving = (current_tdp - float(best["tdp_watts"])) / current_tdp * 100
    return {"candidate": best, "saving_percent": round(saving, 2)} if saving > 10 else None


def assert_hardware_upgrade_allowed(candidate: dict[str, Any]) -> None:
    """Reject catalog upgrades explicitly restricted by licensing or corporate policy."""
    metadata = candidate.get("_metadata", {}) if isinstance(candidate, dict) else {}
    allowed = metadata.get("license_allowed", candidate.get("license_allowed", True))
    status = str(metadata.get("license_status", candidate.get("license_status", "allowed"))).strip().lower()
    if allowed is False or status in {"blocked", "restricted", "denied", "expired"}:
        reason = str(metadata.get("license_reason", candidate.get("license_reason", ""))).strip()
        suffix = f" Motivo: {reason}." if reason else ""
        raise PermissionError("El hardware recomendado no está autorizado por la licencia corporativa." + suffix)


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
    started_monotonic_ns = time.perf_counter_ns()
    cost = calculate_cost(hourly_cost, hours, currency)
    kwh = calculate_energy(tdp_watts, hours, pue)
    carbon = calculate_carbon(tdp_watts, hours, pue, grid_factor, diesel_hours, diesel_factor)
    water = calculate_water(kwh, wue, wsi, immersion)
    score, badge = green_score(cost, cost_limit, carbon, carbon_limit)
    semaphore = semaphore_level(100 - score, *thresholds)
    duration_ms = max(1, round((time.perf_counter_ns() - started_monotonic_ns) / 1_000_000))
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
                state TEXT NOT NULL DEFAULT 'active', is_active INTEGER NOT NULL DEFAULT 1,
                recalculation_pending INTEGER NOT NULL DEFAULT 0
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
            CREATE TABLE IF NOT EXISTS hydro_readings (
                id INTEGER PRIMARY KEY, execution_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL, litres REAL NOT NULL, source TEXT NOT NULL,
                FOREIGN KEY(execution_id) REFERENCES executions(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS project_quotas (
                project_id INTEGER PRIMARY KEY, budget_usd REAL, carbon_gco2eq REAL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS quota_master (
                id INTEGER PRIMARY KEY CHECK(id = 1),
                budget_usd REAL, carbon_gco2eq REAL
            );
            CREATE TABLE IF NOT EXISTS admin_overrides (
                token TEXT PRIMARY KEY, project_id INTEGER NOT NULL, admin_user_id INTEGER NOT NULL,
                reason TEXT NOT NULL, expires_at TEXT NOT NULL, used_at TEXT,
                FOREIGN KEY(project_id) REFERENCES projects(id), FOREIGN KEY(admin_user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, actor TEXT NOT NULL,
                action TEXT NOT NULL, project_id INTEGER, details TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS hardware_catalog (
                id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, category TEXT NOT NULL,
                tdp_watts REAL NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}',
                is_factory INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS model_templates (
                id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL,
                config_json TEXT NOT NULL, is_factory INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS emission_factors (
                id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL,
                gco2eq_kwh REAL NOT NULL CHECK(gco2eq_kwh > 0),
                is_factory INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            """
        )
        self.connection.executemany(
            "INSERT OR IGNORE INTO emission_factors(name, gco2eq_kwh, is_factory, created_at) VALUES (?, ?, 1, ?)",
            (("Eólica", 11.0, utc_iso()), ("Solar", 41.0, utc_iso()), ("Red genérica", 475.0, utc_iso())),
        )
        self.connection.commit()
        self._migrate_schema()

    def _migrate_schema(self) -> None:
        """Additive migrations for databases created by older releases."""
        migrations = (
            ("executions", "username", "ALTER TABLE executions ADD COLUMN username TEXT"),
            ("model_templates", "is_deleted", "ALTER TABLE model_templates ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0"),
            ("projects", "recalculation_pending", "ALTER TABLE projects ADD COLUMN recalculation_pending INTEGER NOT NULL DEFAULT 0"),
        )
        for table, column, statement in migrations:
            columns = {row[1] for row in self.connection.execute(f"PRAGMA table_info({table})")}
            if column not in columns:
                self.connection.execute(statement)
        self.connection.commit()

    def add_user(self, username: str, password: str, role: str = "standard", force_password_change: bool = True) -> int:
        validate_password(password)
        cursor = self.connection.execute(
            "INSERT INTO users(username, password_hash, role, force_password_change) VALUES (?, ?, ?, ?)",
            (username.strip(), hash_password(password), role, int(force_password_change)),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def add_hashed_user(
        self, username: str, password_hash: str, role: str = "standard",
        force_password_change: bool = False,
    ) -> int:
        if not password_hash.startswith("pbkdf2_sha256$"):
            raise ValidationError("El hash de contrasena no usa el formato soportado.")
        cursor = self.connection.execute(
            "INSERT INTO users(username, password_hash, role, force_password_change) VALUES (?, ?, ?, ?)",
            (username.strip(), password_hash, role, int(force_password_change)),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def set_user_password(self, username: str, password: str) -> None:
        validate_password(password)
        cursor = self.connection.execute(
            "UPDATE users SET password_hash = ?, failed_attempts = 0, is_locked = 0, "
            "force_password_change = 0 WHERE username = ?",
            (hash_password(password), username.strip()),
        )
        if cursor.rowcount == 0:
            raise ValidationError("El usuario no existe.")
        self.connection.commit()

    def reset_password_temporary(self, username: str, temp_password: str) -> None:
        """Admin reset: assign a temporary password that must be changed at next login."""
        validate_password(temp_password)
        cursor = self.connection.execute(
            "UPDATE users SET password_hash = ?, failed_attempts = 0, is_locked = 0, "
            "force_password_change = 1 WHERE username = ?",
            (hash_password(temp_password), username.strip()),
        )
        if cursor.rowcount == 0:
            raise ValidationError("El usuario no existe.")
        self.connection.commit()

    def set_user_quotas(self, username: str, budget_usd: float | None, budget_co2: float | None) -> None:
        """Persist per-user USD/CO2 quotas; None removes the corresponding limit."""
        if any(value is not None and value <= 0 for value in (budget_usd, budget_co2)):
            raise ValidationError("Las cuotas de usuario deben ser positivas o quedar vacias.")
        master = self.master_quotas()
        if master["budget_usd"] is not None and budget_usd is not None and budget_usd > master["budget_usd"]:
            raise ValidationError("La cuota financiera del usuario supera el techo maestro.")
        if master["carbon_gco2eq"] is not None and budget_co2 is not None and budget_co2 > master["carbon_gco2eq"]:
            raise ValidationError("La cuota de CO2 del usuario supera el techo maestro.")
        cursor = self.connection.execute(
            "UPDATE users SET budget_usd = ?, budget_co2 = ? WHERE username = ?",
            (budget_usd, budget_co2, username.strip()),
        )
        if cursor.rowcount == 0:
            raise ValidationError("El usuario no existe.")
        self.connection.commit()

    def master_quotas(self) -> dict[str, float | None]:
        row = self.connection.execute(
            "SELECT budget_usd, carbon_gco2eq FROM quota_master WHERE id=1"
        ).fetchone()
        return {
            "budget_usd": row["budget_usd"] if row else None,
            "carbon_gco2eq": row["carbon_gco2eq"] if row else None,
        }

    def set_master_quotas(self, budget_usd: float | None, carbon_gco2eq: float | None) -> None:
        if any(value is not None and value <= 0 for value in (budget_usd, carbon_gco2eq)):
            raise ValidationError("Los techos maestros deben ser positivos o quedar vacíos.")
        maximums = self.connection.execute(
            "SELECT MAX(budget_usd) AS budget_usd, MAX(budget_co2) AS carbon_gco2eq FROM users"
        ).fetchone()
        if budget_usd is not None and maximums["budget_usd"] is not None and maximums["budget_usd"] > budget_usd:
            raise ValidationError("El techo financiero maestro no puede ser menor que una cuota de usuario vigente.")
        if carbon_gco2eq is not None and maximums["carbon_gco2eq"] is not None and maximums["carbon_gco2eq"] > carbon_gco2eq:
            raise ValidationError("El techo ambiental maestro no puede ser menor que una cuota de usuario vigente.")
        self.connection.execute(
            "INSERT INTO quota_master(id, budget_usd, carbon_gco2eq) VALUES (1, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET budget_usd=excluded.budget_usd, carbon_gco2eq=excluded.carbon_gco2eq",
            (budget_usd, carbon_gco2eq),
        )
        self.connection.commit()

    def user_quotas(self, username: str) -> dict[str, float | None]:
        row = self.connection.execute(
            "SELECT budget_usd, budget_co2 FROM users WHERE username = ?", (username.strip(),)
        ).fetchone()
        if not row:
            raise ValidationError("El usuario no existe.")
        return {"budget_usd": row["budget_usd"], "budget_co2": row["budget_co2"]}

    def user_totals(self, username: str) -> dict[str, float]:
        row = self.connection.execute(
            "SELECT COALESCE(SUM(cost), 0) AS cost, COALESCE(SUM(carbon), 0) AS carbon "
            "FROM executions WHERE username = ?",
            (username.strip(),),
        ).fetchone()
        return {"cost": round(float(row["cost"]), 6), "carbon": round(float(row["carbon"]), 6)}

    def set_user_role(self, username: str, role: str) -> None:
        normalized_role = str(role).strip().lower()
        if normalized_role not in {"standard", "admin", "administrador", "usuario"}:
            raise ValidationError("El rol no es valido.")
        cursor = self.connection.execute(
            "UPDATE users SET role = ? WHERE username = ?",
            (role.strip(), username.strip()),
        )
        if cursor.rowcount == 0:
            raise ValidationError("El usuario no existe.")
        self.connection.commit()

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

    def delete_user(self, username: str) -> None:
        cursor = self.connection.execute(
            "DELETE FROM users WHERE username = ?", (username.strip(),)
        )
        if cursor.rowcount == 0:
            raise ValidationError("El usuario no existe.")
        self.connection.commit()

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

    def unlock_user_via_security_questions(self, username: str) -> None:
        """Self-service unlock after answering the account's security questions correctly."""
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
        description_markdown = str(description_markdown)
        sanitize_markdown(description_markdown)
        duplicate = self.connection.execute(
            "SELECT id FROM models WHERE project_id = ? AND lower(name) = lower(?)",
            (project_id, name),
        ).fetchone()
        if duplicate:
            raise ValidationError("Ya existe un modelo con ese nombre en el proyecto.")
        cursor = self.connection.execute(
            "INSERT INTO models(project_id, name, description_markdown) VALUES (?, ?, ?)",
            (project_id, name, description_markdown),
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

    def close_project(self, project_id: int) -> None:
        project = self.connection.execute("SELECT is_active FROM projects WHERE id=?", (project_id,)).fetchone()
        if not project or not project["is_active"]:
            raise ValidationError("El proyecto no existe o esta inactivo.")
        incomplete = self.connection.execute(
            "SELECT COUNT(*) FROM models m WHERE m.project_id=? AND m.is_active=1 "
            "AND NOT EXISTS (SELECT 1 FROM executions e WHERE e.model_id=m.id)",
            (project_id,),
        ).fetchone()[0]
        model_count = self.connection.execute(
            "SELECT COUNT(*) FROM models WHERE project_id=? AND is_active=1", (project_id,)
        ).fetchone()[0]
        if model_count == 0 or incomplete:
            raise ValidationError("Todos los modelos deben tener ejecuciones antes de cerrar la campana.")
        self.connection.execute("UPDATE projects SET state='closed' WHERE id=?", (project_id,))
        self.connection.commit()

    def consolidate_esg(self, project_id: int) -> dict[str, Any]:
        project = self.connection.execute("SELECT name, state FROM projects WHERE id=?", (project_id,)).fetchone()
        if not project:
            raise ValidationError("El proyecto no existe.")
        if project["state"] != "closed":
            raise ValidationError("El certificado ESG requiere una campana completa y cerrada.")
        totals = self.project_totals(project_id)
        count = self.connection.execute(
            "SELECT COUNT(*) FROM executions e JOIN models m ON m.id=e.model_id WHERE m.project_id=?",
            (project_id,),
        ).fetchone()[0]
        return {
            "project_id": project_id,
            "project_name": project["name"],
            "generated_at": utc_iso(),
            "execution_count": count,
            **totals,
        }

    def clear_project(self, project_id: int) -> None:
        project = self.connection.execute(
            "SELECT id FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if not project:
            raise ValidationError("El proyecto no existe.")
        with self.connection:
            self.connection.execute(
                "DELETE FROM executions WHERE model_id IN (SELECT id FROM models WHERE project_id = ?)",
                (project_id,),
            )
            self.connection.execute("DELETE FROM models WHERE project_id = ?", (project_id,))

    def delete_project(self, project_id: int) -> None:
        project = self.connection.execute(
            "SELECT id FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if not project:
            raise ValidationError("El proyecto no existe.")
        with self.connection:
            self.connection.execute(
                "DELETE FROM executions WHERE model_id IN (SELECT id FROM models WHERE project_id = ?)",
                (project_id,),
            )
            self.connection.execute("DELETE FROM models WHERE project_id = ?", (project_id,))
            self.connection.execute("DELETE FROM projects WHERE id = ?", (project_id,))

    def reassign_model(self, model_id: int, target_project_id: int) -> dict[str, Any]:
        target = self.connection.execute(
            "SELECT name, state, is_active FROM projects WHERE id = ?", (target_project_id,)
        ).fetchone()
        if not target or not target["is_active"] or target["state"] != "active":
            raise ValidationError("El proyecto destino no acepta modificaciones.")
        model = self.connection.execute(
            "SELECT m.id, m.name, m.project_id, p.name AS project_name "
            "FROM models m JOIN projects p ON p.id=m.project_id "
            "WHERE m.id=? AND m.is_active=1",
            (model_id,),
        ).fetchone()
        if not model:
            raise ValidationError("El modelo no existe.")
        source_project_id = int(model["project_id"])
        if source_project_id == target_project_id:
            raise ValidationError("El modelo ya pertenece al proyecto destino.")
        before = {
            "source": self.project_totals(source_project_id),
            "target": self.project_totals(target_project_id),
        }
        try:
            with self.connection:
                self.connection.execute(
                    "UPDATE models SET project_id = ? WHERE id = ?", (target_project_id, model_id)
                )
                self.connection.execute(
                    "UPDATE projects SET recalculation_pending=0 WHERE id IN (?, ?)",
                    (source_project_id, target_project_id),
                )
                self._audit(
                    "system", "model_reassigned", target_project_id,
                    f"Modelo {model['name']}: {model['project_name']} -> {target['name']}",
                )
        except sqlite3.DatabaseError:
            try:
                with self.connection:
                    self.connection.execute(
                        "UPDATE projects SET recalculation_pending=1 WHERE id IN (?, ?)",
                        (source_project_id, target_project_id),
                    )
            except sqlite3.DatabaseError:
                pass
            raise
        return {
            "model_id": model_id,
            "model_name": model["name"],
            "source_project_id": source_project_id,
            "source_project_name": model["project_name"],
            "target_project_id": target_project_id,
            "target_project_name": target["name"],
            "before": before,
            "after": {
                "source": self.project_totals(source_project_id),
                "target": self.project_totals(target_project_id),
            },
        }

    def add_emission_factor(self, name: str, gco2eq_kwh: float) -> int:
        normalized_name = str(name).strip()
        try:
            factor = float(gco2eq_kwh)
        except (TypeError, ValueError) as exc:
            raise ValidationError("El factor de emisión debe ser numérico.") from exc
        if not normalized_name:
            raise ValidationError("El nombre de la fuente energética es obligatorio.")
        if not math.isfinite(factor) or factor <= 0:
            raise ValidationError("El factor de emisión debe ser mayor que cero.")
        try:
            cursor = self.connection.execute(
                "INSERT INTO emission_factors(name, gco2eq_kwh, is_factory, created_at) VALUES (?, ?, 0, ?)",
                (normalized_name, factor, utc_iso()),
            )
            self.connection.commit()
        except sqlite3.IntegrityError as exc:
            raise ValidationError("Ya existe una fuente energética con ese nombre.") from exc
        return int(cursor.lastrowid)

    def list_emission_factors(self) -> list[sqlite3.Row]:
        return self.connection.execute(
            "SELECT id, name, gco2eq_kwh, is_factory, created_at FROM emission_factors "
            "ORDER BY is_factory DESC, name COLLATE NOCASE"
        ).fetchall()

    def emission_factor(self, name: str, fallback: float = 475.0) -> tuple[float, bool]:
        row = self.connection.execute(
            "SELECT gco2eq_kwh FROM emission_factors WHERE lower(name)=lower(?)", (str(name).strip(),)
        ).fetchone()
        return (float(row["gco2eq_kwh"]), False) if row else (float(fallback), True)

    def project_totals(self, project_id: int) -> dict[str, float]:
        row = self.connection.execute(
            """SELECT COALESCE(SUM(e.cost), 0) AS cost, COALESCE(SUM(e.carbon), 0) AS carbon,
                      COALESCE(SUM(e.kwh), 0) AS kwh, COALESCE(SUM(e.water), 0) AS water
                 FROM executions e JOIN models m ON m.id = e.model_id
                WHERE m.project_id = ? AND m.is_active = 1""",
            (project_id,),
        ).fetchone()
        return {key: round(float(row[key]), 6) for key in ("cost", "carbon", "kwh", "water")}

    def list_projects(self, include_inactive: bool = False) -> list[sqlite3.Row]:
        if include_inactive:
            return self.connection.execute("SELECT * FROM projects ORDER BY name").fetchall()
        return self.connection.execute(
            "SELECT * FROM projects WHERE is_active = 1 ORDER BY name"
        ).fetchall()

    def list_models(self, project_id: int | None = None) -> list[sqlite3.Row]:
        if project_id is None:
            return self.connection.execute(
                "SELECT * FROM models WHERE is_active = 1 ORDER BY name"
            ).fetchall()
        return self.connection.execute(
            "SELECT * FROM models WHERE project_id = ? AND is_active = 1 ORDER BY name",
            (project_id,),
        ).fetchall()

    def global_totals(self) -> dict[str, Any]:
        """Overview across every active project, for admin-only use."""
        overall = self.connection.execute(
            """SELECT COALESCE(SUM(e.cost), 0) AS cost, COALESCE(SUM(e.carbon), 0) AS carbon,
                      COALESCE(SUM(e.kwh), 0) AS kwh, COALESCE(SUM(e.water), 0) AS water
                 FROM executions e JOIN models m ON m.id = e.model_id
                WHERE m.is_active = 1"""
        ).fetchone()
        by_project = []
        for project in self.list_projects():
            totals = self.project_totals(project["id"])
            by_project.append({"id": project["id"], "name": project["name"], **totals})
        return {
            "totals": {key: round(float(overall[key]), 6) for key in ("cost", "carbon", "kwh", "water")},
            "by_project": by_project,
        }

    def list_history(self, model_id: int | None = None, project_id: int | None = None) -> list[sqlite3.Row]:
        if model_id is not None:
            return self.connection.execute(
                """SELECT e.*, m.name AS model_name, p.name AS project_name FROM executions e
                   JOIN models m ON m.id = e.model_id
                   JOIN projects p ON p.id = m.project_id
                  WHERE e.model_id = ? ORDER BY e.timestamp DESC""",
                (model_id,),
            ).fetchall()
        if project_id is not None:
            return self.connection.execute(
                """SELECT e.*, m.name AS model_name, p.name AS project_name FROM executions e
                   JOIN models m ON m.id = e.model_id
                   JOIN projects p ON p.id = m.project_id
                  WHERE m.project_id = ? ORDER BY e.timestamp DESC""",
                (project_id,),
            ).fetchall()
        return self.connection.execute(
                """SELECT e.*, m.name AS model_name, p.name AS project_name FROM executions e
                    JOIN models m ON m.id = e.model_id
                    JOIN projects p ON p.id = m.project_id ORDER BY e.timestamp DESC"""
        ).fetchall()

    def reconcile_hydro_records(
        self, project_id: int, records: Iterable[dict[str, Any]], source: str = "import",
        max_gap_minutes: float = 60.0,
    ) -> int:
        """Assign validated water readings to the nearest project execution atomically."""
        parsed = parse_hydro_records(records)
        if detect_hydro_desync(parsed, max_gap_minutes=max_gap_minutes):
            raise DataIntegrityError("El historial hídrico contiene brechas o timestamps desordenados.")
        executions = self.connection.execute(
            """SELECT e.id, e.timestamp FROM executions e JOIN models m ON m.id=e.model_id
               WHERE m.project_id=? ORDER BY e.timestamp""",
            (project_id,),
        ).fetchall()
        if not executions:
            raise ValidationError("El proyecto no contiene ejecuciones para conciliar.")
        dated_executions = []
        for execution in executions:
            timestamp = datetime.fromisoformat(str(execution["timestamp"]).replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            dated_executions.append((execution["id"], timestamp))
        allocations = []
        for record in parsed:
            execution_id, execution_time = min(
                dated_executions, key=lambda item: abs((item[1] - record["timestamp"]).total_seconds())
            )
            if abs((execution_time - record["timestamp"]).total_seconds()) > max_gap_minutes * 60:
                raise DataIntegrityError("Una medición hídrica no coincide con ninguna ejecución cercana.")
            allocations.append((execution_id, record))
        with self.connection:
            for execution_id, record in allocations:
                self.connection.execute("UPDATE executions SET water=? WHERE id=?", (record["litres"], execution_id))
                self.connection.execute(
                    "INSERT INTO hydro_readings(execution_id, timestamp, litres, source) VALUES (?, ?, ?, ?)",
                    (execution_id, utc_iso(record["timestamp"]), record["litres"], str(source)),
                )
        return len(allocations)

    def backup(self, destination: str | os.PathLike[str]) -> None:
        """Create a consistent SQLite backup using the online backup API."""
        destination_connection = sqlite3.connect(str(destination))
        try:
            self.connection.backup(destination_connection)
        except sqlite3.Error as exc:
            raise PermissionError(f"No se pudo crear el respaldo: {exc}") from exc
        finally:
            destination_connection.close()

    def restore(self, source: str | os.PathLike[str]) -> None:
        """Validate and atomically restore a SQLite backup, preserving the live DB on failure."""
        source_path = Path(source)
        destination = Path(self.path)
        if self.path == ":memory:":
            raise ValidationError("No se puede restaurar una base en memoria.")
        staged = destination.with_name(f".{destination.name}.{secrets.token_hex(6)}.restore")
        source_connection = None
        staged_connection = None
        try:
            source_connection = sqlite3.connect(f"file:{source_path.resolve()}?mode=ro", uri=True)
            integrity = source_connection.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise DataIntegrityError("El respaldo SQLite esta corrupto.")
            tables = {row[0] for row in source_connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"users", "projects", "models", "executions"}.issubset(tables):
                raise DataIntegrityError("El archivo no es un respaldo de Semaforo IA.")
            staged_connection = sqlite3.connect(staged)
            source_connection.backup(staged_connection)
            staged_connection.close()
            staged_connection = None
            self.connection.close()
            try:
                os.replace(staged, destination)
            except OSError as exc:
                self.connection = sqlite3.connect(self.path)
                self.connection.row_factory = sqlite3.Row
                self.connection.execute("PRAGMA foreign_keys = ON")
                raise PermissionError(f"No se pudo reemplazar la base activa: {exc}") from exc
            self.connection = sqlite3.connect(self.path)
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA foreign_keys = ON")
            self._create_schema()
        except sqlite3.DatabaseError as exc:
            raise DataIntegrityError(f"No se pudo validar el respaldo SQLite: {exc}") from exc
        except OSError as exc:
            raise PermissionError(f"No se pudo leer o preparar el respaldo: {exc}") from exc
        finally:
            if source_connection:
                source_connection.close()
            if staged_connection:
                staged_connection.close()
            try:
                staged.unlink(missing_ok=True)
            except OSError:
                pass

    def add_hardware(self, name: str, category: str, tdp_watts: float, metadata: dict[str, Any] | None = None, is_factory: bool = False) -> int:
        name, category = str(name).strip(), str(category).strip()
        if not name or not category or tdp_watts <= 0:
            raise ValidationError("Nombre, categoria y TDP positivo son obligatorios.")
        try:
            cursor = self.connection.execute(
                "INSERT INTO hardware_catalog(name, category, tdp_watts, metadata_json, is_factory) VALUES (?, ?, ?, ?, ?)",
                (name, category, tdp_watts, json.dumps(metadata or {}, ensure_ascii=True), int(is_factory)),
            )
            self.connection.commit()
            return int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise ValidationError("Ya existe hardware con ese nombre.") from exc

    def update_hardware(self, hardware_id: int, name: str, category: str, tdp_watts: float, metadata: dict[str, Any] | None = None) -> None:
        row = self.connection.execute("SELECT is_factory FROM hardware_catalog WHERE id=?", (hardware_id,)).fetchone()
        if not row:
            raise ValidationError("El hardware no existe.")
        if row["is_factory"]:
            raise PermissionError("El catalogo de fabrica no se puede modificar.")
        if not str(name).strip() or not str(category).strip() or tdp_watts <= 0:
            raise ValidationError("Los datos de hardware no son validos.")
        self.connection.execute(
            "UPDATE hardware_catalog SET name=?, category=?, tdp_watts=?, metadata_json=? WHERE id=?",
            (str(name).strip(), str(category).strip(), tdp_watts, json.dumps(metadata or {}, ensure_ascii=True), hardware_id),
        )
        self.connection.commit()

    def delete_hardware(self, hardware_id: int) -> None:
        row = self.connection.execute("SELECT is_factory FROM hardware_catalog WHERE id=?", (hardware_id,)).fetchone()
        if not row:
            raise ValidationError("El hardware no existe.")
        if row["is_factory"]:
            raise PermissionError("El catalogo de fabrica no se puede eliminar.")
        self.connection.execute("DELETE FROM hardware_catalog WHERE id=?", (hardware_id,))
        self.connection.commit()

    def list_hardware(self) -> list[dict[str, Any]]:
        return [{**dict(row), "metadata": json.loads(row["metadata_json"])} for row in self.connection.execute("SELECT * FROM hardware_catalog ORDER BY name")]

    def add_template(self, name: str, config: dict[str, Any], is_factory: bool = False) -> int:
        if not str(name).strip() or not isinstance(config, dict):
            raise ValidationError("El nombre y la configuracion de la plantilla son obligatorios.")
        try:
            cursor = self.connection.execute(
                "INSERT INTO model_templates(name, config_json, is_factory) VALUES (?, ?, ?)",
                (str(name).strip(), json.dumps(config, ensure_ascii=True), int(is_factory)),
            )
            self.connection.commit()
            return int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise ValidationError("Ya existe una plantilla con ese nombre.") from exc

    def update_template(self, template_id: int, name: str, config: dict[str, Any]) -> None:
        row = self.connection.execute("SELECT is_factory FROM model_templates WHERE id=?", (template_id,)).fetchone()
        if not row:
            raise ValidationError("La plantilla no existe.")
        if row["is_factory"]:
            raise PermissionError("Las plantillas de fabrica no se pueden modificar.")
        self.connection.execute(
            "UPDATE model_templates SET name=?, config_json=? WHERE id=?",
            (str(name).strip(), json.dumps(config, ensure_ascii=True), template_id),
        )
        self.connection.commit()

    def delete_template(self, template_id: int) -> None:
        row = self.connection.execute("SELECT is_factory FROM model_templates WHERE id=?", (template_id,)).fetchone()
        if not row:
            raise ValidationError("La plantilla no existe.")
        if row["is_factory"]:
            raise PermissionError("Las plantillas de fabrica no se pueden eliminar.")
        self.connection.execute("DELETE FROM model_templates WHERE id=?", (template_id,))
        self.connection.commit()

    def soft_delete_template(self, template_id: int) -> None:
        """Hide a custom template while keeping it recoverable in the database."""
        row = self.connection.execute("SELECT is_factory FROM model_templates WHERE id=?", (template_id,)).fetchone()
        if not row:
            raise ValidationError("La plantilla no existe.")
        if row["is_factory"]:
            raise PermissionError("Las plantillas de fabrica no se pueden eliminar.")
        self.connection.execute("UPDATE model_templates SET is_deleted=1 WHERE id=?", (template_id,))
        self.connection.commit()

    def template_linked_projects(self, template_id: int) -> list[str]:
        """Projects referenced by a template config via project_id/project_ids keys."""
        row = self.connection.execute("SELECT config_json FROM model_templates WHERE id=?", (template_id,)).fetchone()
        if not row:
            raise ValidationError("La plantilla no existe.")
        try:
            config = json.loads(row["config_json"])
        except json.JSONDecodeError as exc:
            raise DataIntegrityError("La configuracion de la plantilla esta corrupta.") from exc
        ids = []
        if isinstance(config, dict):
            if config.get("project_id") is not None:
                ids.append(config["project_id"])
            if isinstance(config.get("project_ids"), list):
                ids.extend(config["project_ids"])
        names = []
        for project_id in ids:
            try:
                project = self.connection.execute(
                    "SELECT name FROM projects WHERE id = ? AND is_active = 1", (int(project_id),)
                ).fetchone()
            except (TypeError, ValueError):
                continue
            if project:
                names.append(project["name"])
        return sorted(set(names))

    def list_templates(self, include_deleted: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM model_templates"
        if not include_deleted:
            query += " WHERE is_deleted = 0"
        return [{**dict(row), "config": json.loads(row["config_json"])} for row in self.connection.execute(query + " ORDER BY name")]

    def set_project_quotas(self, project_id: int, budget_usd: float | None, carbon_gco2eq: float | None) -> None:
        if any(value is not None and value <= 0 for value in (budget_usd, carbon_gco2eq)):
            raise ValidationError("Las cuotas deben ser positivas o quedar vacias.")
        if not self.connection.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone():
            raise ValidationError("El proyecto no existe.")
        self.connection.execute(
            "INSERT INTO project_quotas(project_id, budget_usd, carbon_gco2eq) VALUES (?, ?, ?) "
            "ON CONFLICT(project_id) DO UPDATE SET budget_usd=excluded.budget_usd, carbon_gco2eq=excluded.carbon_gco2eq",
            (project_id, budget_usd, carbon_gco2eq),
        )
        self.connection.commit()

    def circuit_breaker_status(self, model_id: int, added_cost: float = 0, added_carbon: float = 0, username: str | None = None) -> dict[str, Any]:
        if added_cost < 0 or added_carbon < 0:
            raise ValidationError("Los consumos proyectados no pueden ser negativos.")
        model = self.connection.execute(
            "SELECT m.project_id, p.state, p.is_active FROM models m JOIN projects p ON p.id=m.project_id WHERE m.id=? AND m.is_active=1",
            (model_id,),
        ).fetchone()
        if not model:
            raise ValidationError("El modelo no existe o esta inactivo.")
        quotas = self.connection.execute("SELECT * FROM project_quotas WHERE project_id = ?", (model["project_id"],)).fetchone()
        totals = self.project_totals(model["project_id"])
        projected = {"cost": totals["cost"] + added_cost, "carbon": totals["carbon"] + added_carbon}
        reasons = []
        codes = []
        if not model["is_active"] or model["state"] != "active":
            reasons.append("El proyecto esta archivado o inactivo.")
            codes.append("ERR_PROJECT_READONLY")
        if quotas and quotas["budget_usd"] is not None and projected["cost"] > quotas["budget_usd"]:
            reasons.append("Se superaria la cuota financiera.")
            codes.append("ERR_QUOTA_FIN")
        if quotas and quotas["carbon_gco2eq"] is not None and projected["carbon"] > quotas["carbon_gco2eq"]:
            reasons.append("Se superaria la cuota ecologica.")
            codes.append("ERR_QUOTA_ECO")
        if username:
            user = self.connection.execute(
                "SELECT budget_usd, budget_co2 FROM users WHERE username = ?", (username.strip(),)
            ).fetchone()
            if user:
                user_totals = self.user_totals(username)
                if user["budget_usd"] is not None and user_totals["cost"] + added_cost > user["budget_usd"]:
                    reasons.append("Se superaria la cuota financiera del usuario.")
                    codes.append("ERR_USER_QUOTA_FIN")
                if user["budget_co2"] is not None and user_totals["carbon"] + added_carbon > user["budget_co2"]:
                    reasons.append("Se superaria la cuota de CO2 del usuario.")
                    codes.append("ERR_USER_QUOTA_ECO")
        return {"allowed": not reasons, "project_id": model["project_id"], "totals": totals, "projected": projected, "reasons": reasons, "codes": codes}

    def create_admin_override(self, project_id: int, username: str, password: str, reason: str, ttl_seconds: int = 300) -> str:
        reason = str(reason).strip()
        if not reason or ttl_seconds < 1 or ttl_seconds > 3600:
            raise ValidationError("El motivo es obligatorio y la vigencia debe ser valida.")
        user = self.connection.execute("SELECT * FROM users WHERE username = ?", (username.strip(),)).fetchone()
        valid = bool(user and not user["is_locked"] and user["role"].lower() in {"admin", "administrador"} and verify_password(password, user["password_hash"]))
        actor = username.strip() or "desconocido"
        if not valid:
            self._audit(actor, "override_denied", project_id, reason)
            self.connection.commit()
            raise PermissionError("Credenciales administrativas invalidas.")
        token = secrets.token_urlsafe(32)
        expires_at = utc_iso(datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds))
        with self.connection:
            self.connection.execute(
                "INSERT INTO admin_overrides(token, project_id, admin_user_id, reason, expires_at) VALUES (?, ?, ?, ?, ?)",
                (token, project_id, user["id"], reason, expires_at),
            )
            self._audit(actor, "override_granted", project_id, reason)
        return token

    def _audit(self, actor: str, action: str, project_id: int | None, details: str) -> None:
        self.connection.execute(
            "INSERT INTO audit_log(timestamp, actor, action, project_id, details) VALUES (?, ?, ?, ?, ?)",
            (utc_iso(), actor, action, project_id, details),
        )

    def add_execution(self, execution: Execution, override_token: str | None = None, username: str | None = None) -> int:
        status = self.circuit_breaker_status(execution.model_id, execution.cost, execution.carbon, username=username)
        override = None
        if status["reasons"] and override_token:
            override = self.connection.execute(
                "SELECT o.*, u.username FROM admin_overrides o JOIN users u ON u.id=o.admin_user_id "
                "WHERE o.token=? AND o.project_id=? AND o.used_at IS NULL AND o.expires_at>=?",
                (override_token, status["project_id"], utc_iso()),
            ).fetchone()
        if status["reasons"] and not override:
            raise CircuitBreakerError(" ".join(status["reasons"]))
        with self.connection:
            cursor = self.connection.execute(
                "INSERT INTO executions(model_id, timestamp, cost, carbon, kwh, water, duration_ms, semaphore, username) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                tuple(asdict(execution).values()) + (username.strip() if username else None,),
            )
            if override:
                self.connection.execute("UPDATE admin_overrides SET used_at=? WHERE token=?", (utc_iso(), override_token))
                self._audit(override["username"], "override_used", status["project_id"], override["reason"])
            try:
                self._record_quota_crossings(status)
            except sqlite3.DatabaseError:
                pass
        return int(cursor.lastrowid)

    def _record_quota_crossings(self, status: dict[str, Any]) -> None:
        quotas = self.connection.execute(
            "SELECT budget_usd, carbon_gco2eq FROM project_quotas WHERE project_id = ?",
            (status["project_id"],),
        ).fetchone()
        if not quotas:
            return
        for metric, quota_key, label in (
            ("cost", "budget_usd", "presupuesto financiero"),
            ("carbon", "carbon_gco2eq", "presupuesto ambiental"),
        ):
            limit = quotas[quota_key]
            if limit is None or limit <= 0:
                continue
            previous_percentage = status["totals"][metric] / limit * 100
            projected_percentage = status["projected"][metric] / limit * 100
            for threshold in (50, 75):
                if previous_percentage < threshold <= projected_percentage:
                    self._audit(
                        "system",
                        "quota_threshold_crossed",
                        status["project_id"],
                        f"Umbral preventivo alcanzado: consumo acumulado al {threshold}% del {label}.",
                    )

    def soft_delete_model(self, model_id: int) -> None:
        self.connection.execute("UPDATE models SET is_active = 0 WHERE id = ?", (model_id,))
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()


def import_records(
    path: str | os.PathLike[str],
    required_fields: Iterable[str] | None = None,
    require_uniform_columns: bool = True,
) -> list[dict[str, Any]]:
    """Read JSON/CSV records and optionally enforce a declared import schema."""
    file_path = Path(path)
    try:
        if file_path.suffix.lower() == ".json":
            data = json.loads(file_path.read_text(encoding="utf-8"))
            if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                raise DataIntegrityError("El JSON debe contener una lista de objetos.")
            records = data
        elif file_path.suffix.lower() == ".csv":
            with file_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            if not rows or not rows[0]:
                raise DataIntegrityError("El CSV no contiene registros o encabezados.")
            records = rows
        else:
            raise DataIntegrityError("Formato no soportado; use JSON o CSV.")
        if not records:
            raise DataIntegrityError("El archivo no contiene registros.")
        schema = tuple(dict.fromkeys(str(field).strip() for field in (required_fields or ())))
        if any(not field for field in schema):
            raise ValidationError("El esquema de importacion contiene campos vacios.")
        if schema:
            expected = set(schema)
            for index, record in enumerate(records, start=1):
                missing = sorted(expected - set(record))
                if missing:
                    raise DataIntegrityError(
                        f"El registro {index} no contiene los campos requeridos: {', '.join(missing)}."
                    )
        keys = set(records[0]) if records else set()
        if require_uniform_columns and any(set(record) != keys for record in records):
            raise DataIntegrityError("Todos los registros deben usar las mismas columnas.")
        return records
    except (OSError, UnicodeError, json.JSONDecodeError, csv.Error) as exc:
        raise DataIntegrityError(f"No se pudo leer el archivo: {exc}") from exc


def export_records(records: Iterable[dict[str, Any]], path: str | os.PathLike[str]) -> None:
    destination = Path(path)
    temporary_path: Path | None = None
    try:
        rows = list(records)
        suffix = destination.suffix.lower()
        if suffix not in {".json", ".csv"}:
            raise DataIntegrityError("Formato de exportacion no soportado; use JSON o CSV.")
        if suffix == ".csv" and not rows:
            raise DataIntegrityError("No hay registros para exportar.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", dir=destination.parent,
            prefix=f".{destination.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            if suffix == ".json":
                json.dump(rows, handle, ensure_ascii=True, indent=2)
            else:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, destination)
        temporary_path = None
    except MemoryError as exc:
        raise MemoryError("No hay memoria suficiente para preparar la exportacion.") from exc
    except (OSError, csv.Error) as exc:
        raise PermissionError(f"No se pudo escribir {destination}: {exc}") from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


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
            store.add_hashed_user(
                username, password_hash, profile.get("role", "standard"),
                bool(profile.get("force_password_change", False)),
            )
    return store
