"""Integracion real con un servidor MLflow Tracking.

Todas las funciones de este modulo hacen llamadas de red reales contra el servidor
configurado por el usuario (config.json -> "mlflow_tracking_uri"). No hay datos ni
corridas simuladas: si el servidor no responde o no esta configurado, se propaga la
excepcion real en vez de devolver un resultado falso.
"""
import atexit
import os
import signal
import subprocess
import sys
import time
import urllib.request

import mlflow
from mlflow.tracking import MlflowClient

from app_paths import writable_path
from functional_core import ApiKeyError, decrypt_api_key

MLFLOW_TOKEN_KEY_PATH = writable_path("secrets", "mlflow_token.key")
EXPERIMENT_PREFIX = "semaforo_ia"
DEFAULT_LOCAL_URI = "http://127.0.0.1:5000"

_local_server_process = None


class MlflowConfigError(RuntimeError):
    """Raised when MLflow is not configured (missing Tracking URI)."""


def get_tracking_uri(config: dict) -> str:
    return str(config.get("mlflow_tracking_uri") or "").strip()


def get_decrypted_token(config: dict) -> str:
    """Returns the plaintext token, or '' if none is stored or it can't be decrypted."""
    token_encrypted = config.get("mlflow_token_encrypted", "")
    if not token_encrypted:
        return ""
    try:
        return decrypt_api_key(token_encrypted, MLFLOW_TOKEN_KEY_PATH)
    except ApiKeyError:
        return ""


def configure(config: dict) -> str:
    """Points the mlflow client at the configured server; raises if unconfigured."""
    uri = get_tracking_uri(config)
    if not uri:
        raise MlflowConfigError("No hay una Tracking URI de MLflow configurada (ver Ajustes).")
    mlflow.set_tracking_uri(uri)
    token = get_decrypted_token(config)
    if token:
        os.environ["MLFLOW_TRACKING_TOKEN"] = token
    else:
        os.environ.pop("MLFLOW_TRACKING_TOKEN", None)
    return uri


def get_client(config: dict) -> MlflowClient:
    configure(config)
    return MlflowClient()


def test_connection(config: dict) -> None:
    """Performs a real request against the MLflow server; raises on any failure."""
    client = get_client(config)
    client.search_experiments(max_results=1)


def _experiment_name(project_name: str) -> str:
    return f"{EXPERIMENT_PREFIX}/{project_name}"


def get_or_create_experiment(config: dict, project_name: str) -> str:
    client = get_client(config)
    name = _experiment_name(project_name)
    experiment = client.get_experiment_by_name(name)
    if experiment is not None and experiment.lifecycle_stage == "active":
        return experiment.experiment_id
    return client.create_experiment(name)


def log_execution_run(
    config: dict,
    *,
    project_name: str,
    model_name: str,
    hardware: str,
    provider: str,
    region: str,
    cost: float,
    carbon: float,
    kwh: float,
    water: float,
    duration_ms: int,
    semaphore: str,
) -> str:
    """Logs one real execution as an MLflow run and returns its run_id."""
    configure(config)
    experiment_id = get_or_create_experiment(config, project_name)
    with mlflow.start_run(experiment_id=experiment_id, run_name=model_name) as run:
        mlflow.log_params({
            "model": model_name,
            "hardware": hardware,
            "cloud_provider": provider,
            "cloud_region": region,
        })
        mlflow.log_metrics({
            "cost_usd": float(cost),
            "carbon_gco2eq": float(carbon),
            "energy_kwh": float(kwh),
            "water_l": float(water),
            "duration_ms": float(duration_ms),
        })
        mlflow.set_tags({"semaphore": semaphore, "project": project_name})
        return run.info.run_id


def list_runs(config: dict, project_name: str, max_results: int = 50):
    """Returns real runs logged for a project's experiment (empty if none exist yet)."""
    client = get_client(config)
    experiment = client.get_experiment_by_name(_experiment_name(project_name))
    if experiment is None:
        return []
    return client.search_runs(
        [experiment.experiment_id], max_results=max_results, order_by=["attributes.start_time DESC"]
    )


def _is_reachable(uri: str, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(f"{uri.rstrip('/')}/health", timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False


def _is_local_uri(uri: str) -> bool:
    return "127.0.0.1" in uri or "localhost" in uri


def start_local_server_if_needed(config: dict, save_config_callback=None, wait_seconds: float = 45) -> str:
    """Auto-arranca un MLflow Tracking Server local real si no hay ninguno accesible.

    No reemplaza una Tracking URI remota configurada explicitamente (aunque este
    inalcanzable en este momento): en ese caso se respeta la configuracion del usuario
    y no se levanta nada local en su lugar. `save_config_callback(uri)` se invoca solo
    cuando el servidor local recien arrancado (o ya corriendo) responde de verdad.
    """
    global _local_server_process

    configured_uri = get_tracking_uri(config)
    if configured_uri and _is_reachable(configured_uri):
        return configured_uri
    if configured_uri and not _is_local_uri(configured_uri):
        return configured_uri

    if _is_reachable(DEFAULT_LOCAL_URI):
        if save_config_callback is not None:
            save_config_callback(DEFAULT_LOCAL_URI)
        return DEFAULT_LOCAL_URI

    if _local_server_process is None or _local_server_process.poll() is not None:
        mlflow_home = writable_path("mlflow_data")
        os.makedirs(mlflow_home, exist_ok=True)
        db_path = os.path.join(mlflow_home, "mlflow.db").replace("\\", "/")
        artifacts_path = os.path.join(mlflow_home, "artifacts").replace("\\", "/")
        popen_kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if os.name == "nt":
            popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        else:
            # Su propio grupo de procesos, para poder matar el arbol completo al cerrar la app.
            popen_kwargs["start_new_session"] = True
        try:
            _local_server_process = subprocess.Popen(
                [
                    sys.executable, "-m", "mlflow", "server",
                    "--backend-store-uri", f"sqlite:///{db_path}",
                    "--default-artifact-root", artifacts_path,
                    "--host", "127.0.0.1",
                    "--port", "5000",
                ],
                **popen_kwargs,
            )
            atexit.register(stop_local_server)
        except OSError:
            return configured_uri or ""

    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if _is_reachable(DEFAULT_LOCAL_URI):
            if save_config_callback is not None:
                save_config_callback(DEFAULT_LOCAL_URI)
            return DEFAULT_LOCAL_URI
        time.sleep(0.5)
    return configured_uri or ""


def stop_local_server() -> None:
    """Terminates the server this process started, if any. No-ops for external servers.

    mlflow (via uvicorn) forks worker subprocesses on top of the main one; a plain
    terminate()/kill() only kills that main PID and leaves the workers running (they
    keep the port bound). We tear down the whole process tree instead.
    """
    global _local_server_process
    process = _local_server_process
    if process is not None and process.poll() is None:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )
        else:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except OSError:
                process.kill()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
    _local_server_process = None
