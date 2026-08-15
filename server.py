import http.server
import socketserver
import json
import urllib.parse
from hardware_info import get_hardware_info
import os

def load_config():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(base_dir, "config.json")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"users": []}

class SimpleHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/login':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data.decode('utf-8'))
                username = data.get('username')
                password = data.get('password')

                config = load_config()
                users = config.get('users', [])
                user = next((u for u in users if u['username'] == username), None)

                if not user:
                    self.send_response(401)
                    self.end_headers()
                    self.wfile.write(json.dumps({'error': 'Usuario no encontrado'}).encode('utf-8'))
                    return

                if str(user.get('password')) != str(password):
                    self.send_response(401)
                    self.end_headers()
                    self.wfile.write(json.dumps({'error': 'Contraseña incorrecta'}).encode('utf-8'))
                    return

                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'ok', 'user': user}).encode('utf-8'))
            except Exception as e:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        if self.path == '/hardware':
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
