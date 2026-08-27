import http.server
import socketserver
import json
from urllib.parse import urlparse

from hardware_info import get_hardware_info
import os
from app_paths import writable_path
from functional_core import bootstrap_store


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


class SimpleHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        parsed_path = urlparse(self.path)
        if parsed_path.path == '/login':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            store = None
            try:
                data = json.loads(post_data.decode('utf-8'))
                username = data.get('username')
                password = data.get('password')

                store = get_store()
                authenticated = store.authenticate(str(username or ""), str(password or ""))
                if not authenticated:
                    locked = store.connection.execute(
                        "SELECT is_locked FROM users WHERE username = ?", (str(username or ""),)
                    ).fetchone()
                    self.send_response(401)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    message = 'Usuario bloqueado' if locked and locked['is_locked'] else 'Credenciales invalidas'
                    self.wfile.write(json.dumps({'error': message}).encode('utf-8'))
                    return

                config = load_config()
                user = next((u for u in config.get('users', []) if str(u.get('username')) == str(username)), {})
                user = {key: value for key, value in user.items() if key != 'password_hash'}
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'ok', 'user': user}).encode('utf-8'))
            except Exception:
                self.send_response(400)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'Error interno de autenticacion'}).encode('utf-8'))
            finally:
                if store is not None:
                    store.close()
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        parsed_path = urlparse(self.path)
        if parsed_path.path == '/hardware':
            info = get_hardware_info()
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(info).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()


def run():
    config = load_config()
    port = config.get("server_port", 8000)
    server_address = ('0.0.0.0', port)
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(server_address, SimpleHandler)
    print(f"Servidor corriendo en el puerto {port}")
    httpd.serve_forever()


if __name__ == '__main__':
    run()
