"""External billing, carbon-factor and on-premise telemetry adapters."""

from __future__ import annotations

import json
import hashlib
import os
import random
import tempfile
import threading
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Callable

import requests


class ExternalServiceError(RuntimeError):
    pass


class TelemetryError(ExternalServiceError):
    pass


def _atomic_json_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except OSError as exc:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise PermissionError(f"No se pudo actualizar la cache {path}: {exc}") from exc


def _read_cache(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ExternalServiceError(f"La cache local no esta disponible o esta corrupta: {exc}") from exc


def _snapshot_cache(path: Path) -> Path | None:
    if not path.is_file():
        return None
    payload = _read_cache(path)
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    stamp = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    snapshot = path.parent / f"{path.stem}_history" / f"{stamp}_{hashlib.sha256(encoded).hexdigest()[:8]}.json"
    if not snapshot.exists():
        _atomic_json_write(snapshot, payload)
    return snapshot


def list_cache_snapshots(path: str | os.PathLike[str]) -> list[Path]:
    cache = Path(path)
    history = cache.parent / f"{cache.stem}_history"
    return sorted(history.glob("*.json"), reverse=True) if history.is_dir() else []


def restore_cache_snapshot(path: str | os.PathLike[str], snapshot_name: str) -> Any:
    cache = Path(path)
    snapshots = {item.name: item for item in list_cache_snapshots(cache)}
    snapshot = snapshots.get(Path(snapshot_name).name)
    if snapshot is None:
        raise ExternalServiceError("La versión histórica seleccionada no existe.")
    payload = _read_cache(snapshot)
    _snapshot_cache(cache)
    _atomic_json_write(cache, payload)
    return payload


def _placeholder_payload(url: str, *, provider: str | None = None) -> Any:
    if not url.startswith("placeholder://"):
        return None
    host = url.replace("placeholder://", "", 1).split("/", 1)[0].strip().lower() or (provider or "demo")
    if host in {"aws", "azure", "gcp"}:
        examples = {
            "aws": [{"instance": "placeholder-g5.xlarge", "region": "us-east-1", "hourly_usd": 0.12}, {"instance": "placeholder-m6i.large", "region": "us-east-1", "hourly_usd": 0.09}],
            "azure": [{"instance": "placeholder-D8s_v5", "region": "eastus", "hourly_usd": 0.14}, {"instance": "placeholder-D4s_v5", "region": "eastus", "hourly_usd": 0.07}],
            "gcp": [{"instance": "placeholder-n2-standard-8", "region": "us-central1", "hourly_usd": 0.13}, {"instance": "placeholder-e2-standard-2", "region": "us-central1", "hourly_usd": 0.06}],
        }
        return {"rates": examples.get(host, examples["aws"])}
    return {
        "factors": [
            {"region": "us-east-1", "gco2eq_kwh": 0.42, "updated_at": "2026-09-08T00:00:00Z"},
            {"region": "us-west-1", "gco2eq_kwh": 0.35, "updated_at": "2026-09-08T00:00:00Z"},
        ]
    }


class CachedJsonClient:
    def __init__(
        self,
        cache_path: str | os.PathLike[str],
        timeout: float = 8.0,
        session: requests.Session | None = None,
        retries: int = 2,
        backoff_seconds: float = 0.2,
    ):
        if timeout <= 0:
            raise ValueError("El timeout debe ser positivo.")
        if retries < 0 or backoff_seconds < 0:
            raise ValueError("Los reintentos y el backoff no pueden ser negativos.")
        self.cache_path = Path(cache_path)
        self.timeout = timeout
        self.session = session or requests.Session()
        self.retries = retries
        self.backoff_seconds = backoff_seconds

    def fetch(self, url: str, parser: Callable[[Any], Any], headers: dict[str, str] | None = None) -> tuple[Any, bool]:
        if url.startswith("placeholder://"):
            payload = _placeholder_payload(url, provider=(headers or {}).get("X-Provider") or None)
            parsed = parser(payload)
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            _snapshot_cache(self.cache_path)
            _atomic_json_write(self.cache_path, parsed)
            return parsed, False

        network_error = None
        for attempt in range(self.retries + 1):
            try:
                response = self.session.get(url, timeout=self.timeout, headers=headers or {"Accept": "application/json"})
                response.raise_for_status()
                parsed = parser(response.json())
                _snapshot_cache(self.cache_path)
                _atomic_json_write(self.cache_path, parsed)
                return parsed, False
            except (requests.RequestException, ValueError, TypeError, KeyError, PermissionError) as exc:
                network_error = exc
                if attempt < self.retries:
                    delay = self.backoff_seconds * (2 ** attempt)
                    if delay:
                        time.sleep(delay)
        try:
            if network_error is None:
                raise ExternalServiceError("La sincronizacion no produjo una respuesta valida.")
            return parser(_read_cache(self.cache_path)), True
        except (ExternalServiceError, ValueError, TypeError, KeyError) as cache_error:
            raise ExternalServiceError(
                f"Fallo la sincronizacion ({network_error}) y no existe un fallback valido ({cache_error})."
            ) from network_error


class BillingCloudClient(CachedJsonClient):
    """Normalize provider billing payloads into auditable hourly rates."""

    def sync(self, provider: str, url: str, api_key: str | None = None) -> tuple[list[dict[str, Any]], bool]:
        provider = provider.strip().lower()
        if provider not in {"aws", "azure", "gcp"}:
            raise ValueError("Proveedor cloud no soportado.")
        headers = {"Accept": "application/json", "X-Provider": provider}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return self.fetch(url, lambda payload: self._parse(provider, payload), headers)

    @staticmethod
    def _parse(provider: str, payload: Any) -> list[dict[str, Any]]:
        rows = payload.get("rates") if isinstance(payload, dict) else payload
        if not isinstance(rows, list) or not rows:
            raise ValueError("La respuesta de billing no contiene tarifas.")
        normalized = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("Una tarifa cloud no es un objeto.")
            instance = str(row.get("instance") or row.get("sku") or "").strip()
            region = str(row.get("region") or "").strip()
            try:
                hourly = float(row.get("hourly_usd", row.get("price")))
            except (TypeError, ValueError) as exc:
                raise ValueError("Una tarifa cloud tiene precio invalido.") from exc
            if not instance or not region or hourly < 0:
                raise ValueError("Una tarifa cloud esta incompleta.")
            normalized.append({"provider": provider, "instance": instance, "region": region, "hourly_usd": hourly})
        return normalized


class CarbonFactorClient(CachedJsonClient):
    def sync(self, url: str) -> tuple[list[dict[str, Any]], bool]:
        return self.fetch(url, self._parse)

    @staticmethod
    def _parse(payload: Any) -> list[dict[str, Any]]:
        rows = payload.get("factors") if isinstance(payload, dict) else payload
        if not isinstance(rows, list) or not rows:
            raise ValueError("La fuente oficial no contiene factores.")
        normalized = []
        for row in rows:
            try:
                region = str(row["region"]).strip()
                factor = float(row["gco2eq_kwh"])
                updated_at = str(row["updated_at"]).strip()
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("Un factor de emision es invalido.") from exc
            if not region or factor < 0 or not updated_at:
                raise ValueError("Un factor de emision esta incompleto.")
            normalized.append({"region": region, "gco2eq_kwh": factor, "updated_at": updated_at})
        return normalized


def _apply_loss_factor(watts: float, loss_factor: float) -> float:
    if watts < 0 or not 1.0 <= loss_factor <= 1.5:
        raise TelemetryError("La lectura o el factor de perdidas no es valido.")
    return round(watts * loss_factor, 3)


class SimulatedTelemetryClient:
    def __init__(self, minimum_watts: float = 100, maximum_watts: float = 500, seed: int | None = None):
        if minimum_watts < 0 or maximum_watts <= minimum_watts:
            raise ValueError("El rango del simulador no es valido.")
        self.minimum_watts = minimum_watts
        self.maximum_watts = maximum_watts
        self.random = random.Random(seed)

    def read_watts(self, loss_factor: float = 1.0, cancel_event: threading.Event | None = None) -> float:
        if cancel_event and cancel_event.is_set():
            raise TelemetryError("Lectura cancelada.")
        return _apply_loss_factor(self.random.uniform(self.minimum_watts, self.maximum_watts), loss_factor)


class ModbusTelemetryClient:
    def __init__(self, host: str, register: int, port: int = 502, unit_id: int = 1, timeout: float = 3.0, scale: float = 1.0):
        self.host, self.register, self.port = host, register, port
        self.unit_id, self.timeout, self.scale = unit_id, timeout, scale

    def read_watts(self, loss_factor: float = 1.0, cancel_event: threading.Event | None = None) -> float:
        if cancel_event and cancel_event.is_set():
            raise TelemetryError("Lectura cancelada.")
        try:
            from pymodbus.client import ModbusTcpClient
        except ImportError as exc:
            raise TelemetryError("Instale pymodbus para usar telemetria Modbus TCP.") from exc
        client = ModbusTcpClient(self.host, port=self.port, timeout=self.timeout)
        try:
            if not client.connect():
                raise TelemetryError("No se pudo conectar al dispositivo Modbus TCP.")
            result = client.read_holding_registers(self.register, count=1, device_id=self.unit_id)
            if result.isError() or not result.registers:
                raise TelemetryError("El dispositivo Modbus devolvio una lectura invalida.")
            return _apply_loss_factor(float(result.registers[0]) * self.scale, loss_factor)
        except (OSError, TimeoutError) as exc:
            raise TelemetryError(f"Fallo la lectura Modbus TCP: {exc}") from exc
        finally:
            client.close()


class SnmpTelemetryClient:
    def __init__(self, host: str, oid: str, community: str = "public", port: int = 161, timeout: float = 3.0):
        self.host, self.oid, self.community = host, oid, community
        self.port, self.timeout = port, timeout

    def read_watts(self, loss_factor: float = 1.0, cancel_event: threading.Event | None = None) -> float:
        if cancel_event and cancel_event.is_set():
            raise TelemetryError("Lectura cancelada.")
        try:
            import asyncio
            from pysnmp.hlapi.v3arch.asyncio import CommunityData, ContextData, ObjectIdentity, ObjectType, SnmpEngine, UdpTransportTarget, get_cmd
        except ImportError as exc:
            raise TelemetryError("Instale pysnmp para usar telemetria SNMP.") from exc

        async def query():
            target = await UdpTransportTarget.create(
                (self.host, self.port), timeout=self.timeout, retries=0,
            )
            return await get_cmd(
                SnmpEngine(), CommunityData(self.community), target,
                ContextData(), ObjectType(ObjectIdentity(self.oid)),
            )

        try:
            error_indication, error_status, _, bindings = asyncio.run(query())
        except (OSError, RuntimeError, TimeoutError) as exc:
            raise TelemetryError(f"Fallo la lectura SNMP: {exc}") from exc
        if error_indication or error_status or not bindings:
            raise TelemetryError(f"El dispositivo SNMP no respondio: {error_indication or error_status}")
        try:
            return _apply_loss_factor(float(bindings[0][1]), loss_factor)
        except (TypeError, ValueError) as exc:
            raise TelemetryError("El OID SNMP no contiene una lectura numerica.") from exc
