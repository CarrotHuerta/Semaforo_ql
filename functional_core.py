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
    if not rows:
        return None
    try:
        first = datetime.fromisoformat(str(rows[0]["timestamp"]).replace("Z", "+00:00"))
        total = sum(float(row[metric]) for row in rows)
    except (KeyError, TypeError, ValueError) as exc:
        raise DataIntegrityError("El historial no permite calcular una proyeccion.") from exc
    if total < 0:
        raise DataIntegrityError("El historial contiene valores negativos.")
    current = as_of or datetime.now(timezone.utc)
    if first.tzinfo is None:
        first = first.replace(tzinfo=timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    if total >= limit:
        return current.astimezone(timezone.utc)
    elapsed_days = max((current - first).total_seconds() / 86400, 1.0)
    daily_rate = total / elapsed_days
    if daily_rate <= 0:
        return None
    return current.astimezone(timezone.utc) + timedelta(days=(limit - total) / daily_rate)


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
            CREATE TABLE IF NOT EXISTS project_quotas (
                project_id INTEGER PRIMARY KEY, budget_usd REAL, carbon_gco2eq REAL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
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
                """SELECT e.*, m.name AS model_name FROM executions e
                   JOIN models m ON m.id = e.model_id
                  WHERE e.model_id = ? ORDER BY e.timestamp DESC""",
                (model_id,),
            ).fetchall()
        if project_id is not None:
            return self.connection.execute(
                """SELECT e.*, m.name AS model_name FROM executions e
                   JOIN models m ON m.id = e.model_id
                  WHERE m.project_id = ? ORDER BY e.timestamp DESC""",
                (project_id,),
            ).fetchall()
        return self.connection.execute(
            """SELECT e.*, m.name AS model_name FROM executions e
               JOIN models m ON m.id = e.model_id ORDER BY e.timestamp DESC"""
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

    def list_templates(self) -> list[dict[str, Any]]:
        return [{**dict(row), "config": json.loads(row["config_json"])} for row in self.connection.execute("SELECT * FROM model_templates ORDER BY name")]

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

    def circuit_breaker_status(self, model_id: int, added_cost: float = 0, added_carbon: float = 0) -> dict[str, Any]:
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
        if not model["is_active"] or model["state"] != "active":
            reasons.append("El proyecto esta archivado o inactivo.")
        if quotas and quotas["budget_usd"] is not None and projected["cost"] > quotas["budget_usd"]:
            reasons.append("Se superaria la cuota financiera.")
        if quotas and quotas["carbon_gco2eq"] is not None and projected["carbon"] > quotas["carbon_gco2eq"]:
            reasons.append("Se superaria la cuota ecologica.")
        return {"allowed": not reasons, "project_id": model["project_id"], "totals": totals, "projected": projected, "reasons": reasons}

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

    def add_execution(self, execution: Execution, override_token: str | None = None) -> int:
        status = self.circuit_breaker_status(execution.model_id, execution.cost, execution.carbon)
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
                "INSERT INTO executions(model_id, timestamp, cost, carbon, kwh, water, duration_ms, semaphore) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                tuple(asdict(execution).values()),
            )
            if override:
                self.connection.execute("UPDATE admin_overrides SET used_at=? WHERE token=?", (utc_iso(), override_token))
                self._audit(override["username"], "override_used", status["project_id"], override["reason"])
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
    destination = Path(path)
    try:
        rows = list(records)
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
    except MemoryError as exc:
        raise MemoryError("No hay memoria suficiente para preparar la exportacion.") from exc
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
