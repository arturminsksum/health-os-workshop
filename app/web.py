"""Страница медкарты в браузере, под паролем. Отдаёт один готовый html-файл."""
import base64
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import config
import medcard


class Handler(BaseHTTPRequestHandler):
    def _authorized(self):
        if not config.WEB_PASSWORD:
            return True
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            _, password = base64.b64decode(header[6:]).decode().split(":", 1)
        except Exception:
            return False
        return hmac.compare_digest(password, config.WEB_PASSWORD)

    def do_GET(self):
        if not self._authorized():
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="Health OS"')
            self.end_headers()
            return
        if not config.PAGE.exists():
            medcard.rebuild_page()
        body = config.PAGE.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def serve():
    server = ThreadingHTTPServer(("0.0.0.0", config.WEB_PORT), Handler)
    print(f"Страница: http://<адрес-сервера>:{config.WEB_PORT}  (логин любой, пароль из WEB_PASSWORD)")
    server.serve_forever()
