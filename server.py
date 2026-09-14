import http.server
import socketserver
import json
import base64
import hashlib
import hmac
import sqlite3
import time
from urllib.parse import urlparse

from hardware_info import get_hardware_info
import os
from app_paths import writable_path
from functional_core import ValidationError, bootstrap_store


MAX_REQUEST_BYTES = 64 * 1024
SESSION_TTL_SECONDS = 8 * 60 * 60


def load_config():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(base_dir, "config.json")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"users": []}


def get_store():
    store = bootstrap_store(load_config(), writable_path("semaforo.sqlite3"))
    return store


def _token_secret():
    hashes = sorted(
        str(user.get("password_hash", ""))
        for user in load_config().get("users", [])
        if user.get("password_hash")
    )
    return hashlib.sha256("|".join(hashes).encode("utf-8")).digest()


def create_session_token(username, scope="session"):
    payload = json.dumps(
        {"username": username, "scope": scope, "expires": int(time.time()) + SESSION_TTL_SECONDS},
        separators=(",", ":"),
    ).encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    signature = hmac.new(_token_secret(), encoded.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def validate_session_token(token, required_scope="session"):
    if not isinstance(token, str) or "." not in token:
        return False
    encoded, signature = token.split(".", 1)
    expected = hmac.new(_token_secret(), encoded.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return False
    try:
        padding = "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode((encoded + padding).encode("ascii")))
        if not isinstance(payload, dict) or int(payload["expires"]) <= int(time.time()):
            return None
        if payload.get("scope", "session") != required_scope:
            return None
        return payload
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def authenticate_request(username, password):
    """Authenticate against the same SQLite store used by the desktop app."""
    if not isinstance(username, str) or not isinstance(password, str):
        return None, "Credenciales invalidas", 401
    username = username.strip()
    if not username or len(username) > 128 or len(password) > 256:
        return None, "Credenciales invalidas", 401
    store = get_store()
    try:
        authenticated = store.authenticate(username, password)
        if authenticated:
            return {
                "username": authenticated["username"],
                "role": authenticated["role"],
                "force_password_change": bool(authenticated["force_password_change"]),
            }, None, 200
        if store.is_user_locked(username):
            return None, "Usuario bloqueado", 423
        return None, "Credenciales invalidas", 401
    finally:
        store.close()


class SimpleHandler(http.server.BaseHTTPRequestHandler):
    server_version = "SemaforoIA/1.0"

    def _send_json(self, status, payload):
        encoded = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def do_POST(self):
        parsed_path = urlparse(self.path)
        if parsed_path.path == '/login':
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                self._send_json(415, {"error": "Content-Type debe ser application/json"})
                return
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                if content_length <= 0 or content_length > MAX_REQUEST_BYTES:
                    self._send_json(413, {"error": "Solicitud demasiado grande"})
                    return
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))
                if not isinstance(data, dict):
                    self._send_json(400, {"error": "El cuerpo debe ser un objeto JSON"})
                    return
                user, error, status = authenticate_request(data.get("username"), data.get("password"))
                if error:
                    self._send_json(status, {"error": error})
                    return
                if user["force_password_change"]:
                    self._send_json(status, {
                        "status": "password_change_required", "user": user,
                        "password_change_token": create_session_token(user["username"], "password_change"),
                    })
                else:
                    self._send_json(status, {"status": "ok", "user": user, "token": create_session_token(user["username"])})
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
                self._send_json(400, {"error": "JSON invalido"})
            except OSError:
                self._send_json(503, {"error": "Servicio de autenticacion no disponible"})
        elif parsed_path.path == '/change-password':
            authorization = self.headers.get("Authorization", "")
            token = authorization.removeprefix("Bearer ").strip()
            payload = validate_session_token(token, "password_change")
            if not payload:
                self._send_json(401, {"error": "Token de cambio invalido o expirado"})
                return
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                if content_length <= 0 or content_length > MAX_REQUEST_BYTES:
                    self._send_json(413, {"error": "Solicitud demasiado grande"})
                    return
                data = json.loads(self.rfile.read(content_length).decode("utf-8"))
                password = data.get("password") if isinstance(data, dict) else None
                store = get_store()
                try:
                    store.set_user_password(payload["username"], password)
                finally:
                    store.close()
                self._send_json(200, {
                    "status": "ok", "token": create_session_token(payload["username"]),
                })
            except ValidationError as exc:
                self._send_json(400, {"error": str(exc)})
            except (OSError, sqlite3.DatabaseError):
                self._send_json(503, {"error": "No se pudo guardar la nueva contraseña"})
            except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
                self._send_json(400, {"error": "Solicitud invalida"})
        else:
            self._send_json(404, {"error": "Ruta no encontrada"})

    def do_GET(self):
        parsed_path = urlparse(self.path)
        if parsed_path.path == '/hardware':
            authorization = self.headers.get("Authorization", "")
            token = authorization.removeprefix("Bearer ").strip()
            if not validate_session_token(token, "session"):
                self._send_json(401, {"error": "Autenticacion requerida"})
                return
            try:
                self._send_json(200, get_hardware_info())
            except OSError:
                self._send_json(503, {"error": "Hardware no disponible"})
        else:
            self._send_json(404, {"error": "Ruta no encontrada"})

    def log_message(self, format, *args):
        """Avoid logging credentials or request bodies to the console."""
        super().log_message("%s", format % args)


def run():
    config = load_config()
    port = int(config.get("server_port", 6767))
    if not 1 <= port <= 65535:
        raise ValueError("server_port debe estar entre 1 y 65535")
    server_address = ("0.0.0.0", port)

    class ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
        allow_reuse_address = True
        daemon_threads = True

    httpd = ThreadingTCPServer(server_address, SimpleHandler)
    print(f"Servidor corriendo en el puerto {port}")
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()


if __name__ == '__main__':
    run()
