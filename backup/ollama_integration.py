"""Integracion real con un servidor Ollama local, sin datos ni metricas simuladas.

Todas las funciones hacen llamadas HTTP reales contra el servidor Ollama configurado
(por defecto http://127.0.0.1:11434). Si Ollama no esta instalado/corriendo o el
modelo no esta descargado, se propaga el error real en vez de inventar un resultado.
"""
import json
import os
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request

DEFAULT_OLLAMA_URI = "http://127.0.0.1:11434"
DEFAULT_TEST_MODEL = "llama3.2"
DEFAULT_TEST_PROMPT = "Responde en una sola frase breve: ¿que es la eficiencia energetica en IA?"

_local_server_process = None


class OllamaError(RuntimeError):
    """Raised for any real failure talking to Ollama (unreachable, model missing, etc.)."""


class OllamaCancelledError(OllamaError):
    pass


def is_reachable(uri: str = DEFAULT_OLLAMA_URI, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(f"{uri.rstrip('/')}/api/version", timeout=timeout):
            return True
    except Exception:
        return False


def start_local_server_if_needed(uri: str = DEFAULT_OLLAMA_URI, wait_seconds: float = 15) -> bool:
    """Intenta levantar `ollama serve` si el binario esta instalado y nada responde aun.

    No inventa nada si el binario `ollama` no esta instalado: devuelve False y el error
    real se ve al intentar usar la API (mensaje que indica instalar Ollama).
    """
    global _local_server_process
    if is_reachable(uri):
        return True

    ollama_bin = shutil.which("ollama")
    if not ollama_bin:
        return False

    if _local_server_process is None or _local_server_process.poll() is not None:
        popen_kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if os.name == "nt":
            popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        else:
            popen_kwargs["start_new_session"] = True
        try:
            _local_server_process = subprocess.Popen([ollama_bin, "serve"], **popen_kwargs)
        except OSError:
            return False

    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if is_reachable(uri):
            return True
        time.sleep(0.5)
    return False


def stop_local_server() -> None:
    """Terminates the server this process started, if any. No-ops for external servers."""
    global _local_server_process
    process = _local_server_process
    if process is not None and process.poll() is None:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )
        else:
            import signal
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except OSError:
                process.kill()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
    _local_server_process = None


def list_local_models(uri: str = DEFAULT_OLLAMA_URI) -> list:
    try:
        with urllib.request.urlopen(f"{uri.rstrip('/')}/api/tags", timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise OllamaError(f"No se pudo consultar los modelos locales de Ollama: {exc}") from exc
    return [item.get("name", "") for item in data.get("models", [])]


def ensure_model_available(uri: str, model: str, progress_callback=None, cancel_event: threading.Event | None = None) -> None:
    """Descarga el modelo via un pull real (streaming) si todavia no esta local."""
    existing = list_local_models(uri)
    if any(name == model or name.startswith(f"{model}:") for name in existing):
        return
    payload = json.dumps({"name": model, "stream": True}).encode("utf-8")
    request = urllib.request.Request(
        f"{uri.rstrip('/')}/api/pull", data=payload, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=900) as response:
            for raw_line in response:
                if cancel_event and cancel_event.is_set():
                    response.close()
                    raise OllamaCancelledError("Descarga cancelada por el usuario.")
                if not raw_line.strip():
                    continue
                event = json.loads(raw_line.decode("utf-8"))
                if event.get("error"):
                    raise OllamaError(event["error"])
                if progress_callback is not None:
                    progress_callback(event)
    except urllib.error.URLError as exc:
        raise OllamaError(f"No se pudo descargar el modelo '{model}': {exc}") from exc


def run_inference(uri: str, model: str, prompt: str, timeout: float = 120) -> dict:
    """Ejecuta una generacion real y devuelve las metricas reales que informa Ollama."""
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode("utf-8")
    request = urllib.request.Request(
        f"{uri.rstrip('/')}/api/generate", data=payload, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise OllamaError(f"No se pudo ejecutar el modelo '{model}': {exc}") from exc
    if data.get("error"):
        raise OllamaError(data["error"])

    eval_count = data.get("eval_count", 0)
    eval_duration_ms = data.get("eval_duration", 0) / 1e6
    tokens_per_second = (eval_count / (eval_duration_ms / 1000)) if eval_duration_ms else 0.0

    return {
        "response_text": data.get("response", ""),
        "total_duration_ms": data.get("total_duration", 0) / 1e6,
        "load_duration_ms": data.get("load_duration", 0) / 1e6,
        "prompt_eval_count": data.get("prompt_eval_count", 0),
        "prompt_eval_duration_ms": data.get("prompt_eval_duration", 0) / 1e6,
        "eval_count": eval_count,
        "eval_duration_ms": eval_duration_ms,
        "tokens_per_second": round(tokens_per_second, 2),
    }


def run_chat(
    uri: str,
    model: str,
    messages: list,
    timeout: float = 120,
    cancel_event: threading.Event | None = None,
) -> dict:
    """Ejecuta un turno real de chat (POST /api/chat) y devuelve las metricas reales.

    `messages` es la lista completa de turnos previos + el nuevo mensaje del usuario,
    con el formato de Ollama: [{"role": "user"|"assistant"|"system", "content": str}, ...].
    """
    payload = json.dumps({"model": model, "messages": messages, "stream": True}).encode("utf-8")
    request = urllib.request.Request(
        f"{uri.rstrip('/')}/api/chat", data=payload, method="POST",
        headers={"Content-Type": "application/json"},
    )
    content = []
    data = {}
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            for raw_line in response:
                if cancel_event and cancel_event.is_set():
                    response.close()
                    raise OllamaCancelledError("Ejecucion cancelada por el usuario.")
                if not raw_line.strip():
                    continue
                event = json.loads(raw_line.decode("utf-8"))
                if event.get("error"):
                    raise OllamaError(event["error"])
                content.append(event.get("message", {}).get("content", ""))
                if event.get("done"):
                    data = event
    except urllib.error.URLError as exc:
        raise OllamaError(f"No se pudo ejecutar el modelo '{model}': {exc}") from exc
    except json.JSONDecodeError as exc:
        raise OllamaError("Ollama devolvio una respuesta corrupta.") from exc
    if cancel_event and cancel_event.is_set():
        raise OllamaCancelledError("Ejecucion cancelada por el usuario.")
    if not data.get("done"):
        raise OllamaError("Ollama cerro la conexion antes de completar la respuesta.")

    eval_count = data.get("eval_count", 0)
    eval_duration_ms = data.get("eval_duration", 0) / 1e6
    tokens_per_second = (eval_count / (eval_duration_ms / 1000)) if eval_duration_ms else 0.0

    return {
        "response_text": "".join(content),
        "total_duration_ms": data.get("total_duration", 0) / 1e6,
        "load_duration_ms": data.get("load_duration", 0) / 1e6,
        "prompt_eval_count": data.get("prompt_eval_count", 0),
        "prompt_eval_duration_ms": data.get("prompt_eval_duration", 0) / 1e6,
        "eval_count": eval_count,
        "eval_duration_ms": eval_duration_ms,
        "tokens_per_second": round(tokens_per_second, 2),
    }

