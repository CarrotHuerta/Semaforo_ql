"""External billing, carbon-factor and on-premise telemetry adapters."""

from __future__ import annotations

import json
import os
import random
import tempfile
import threading
from pathlib import Path
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


class CachedJsonClient:
    def __init__(self, cache_path: str | os.PathLike[str], timeout: float = 8.0, session: requests.Session | None = None):
        if timeout <= 0:
            raise ValueError("El timeout debe ser positivo.")
        self.cache_path = Path(cache_path)
        self.timeout = timeout
        self.session = session or requests.Session()

    def fetch(self, url: str, parser: Callable[[Any], Any], headers: dict[str, str] | None = None) -> tuple[Any, bool]:
        try:
            response = self.session.get(url, timeout=self.timeout, headers=headers or {"Accept": "application/json"})
            response.raise_for_status()
            parsed = parser(response.json())
            _atomic_json_write(self.cache_path, parsed)
            return parsed, False
        except (requests.RequestException, ValueError, TypeError, KeyError, PermissionError) as network_error:
            try:
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
        headers = {"Accept": "application/json"}
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
