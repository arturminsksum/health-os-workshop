"""Страница медкарты в браузере. Вход — одно поле «Пароль», браузер запоминает вход на месяц."""
import hashlib
import hmac
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import config
import medcard

COOKIE = "healthos"

LOGIN_PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Health OS — вход</title>
<style>
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#f3f5f9;
font-family:-apple-system,"Segoe UI",Roboto,Arial,sans-serif;color:#1f2430}
form{background:#fff;padding:36px 32px;border-radius:16px;box-shadow:0 6px 24px #0001;width:min(340px,86vw)}
h1{margin:0 0 6px;font-size:24px}h1 b{color:#2f6fed}p{margin:0 0 22px;color:#6b7280;font-size:14px}
input{width:100%;box-sizing:border-box;font-size:18px;padding:12px 14px;border:1px solid #d6dbe4;border-radius:10px}
button{margin-top:14px;width:100%;font-size:17px;padding:12px;border:0;border-radius:10px;background:#2f6fed;
color:#fff;cursor:pointer}.err{color:#d64545;font-size:14px;margin-top:10px}
</style></head><body><form method="post" action="/login">
<h1>Health <b>OS</b></h1><p>Личная карта здоровья</p>
<input type="password" name="password" placeholder="Пароль" autofocus>
<button>Войти</button>{error}</form></body></html>"""


def _token():
    return hashlib.sha256(("healthos:" + config.WEB_PASSWORD).encode()).hexdigest()[:32]


class Handler(BaseHTTPRequestHandler):
    def _authorized(self):
        if not config.WEB_PASSWORD:
            return True
        cookies = dict(c.strip().split("=", 1) for c in self.headers.get("Cookie", "").split(";") if "=" in c)
        return hmac.compare_digest(cookies.get(COOKIE, ""), _token())

    def _send(self, code, body, ctype="text/html; charset=utf-8", headers=()):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        form = urllib.parse.parse_qs(self.rfile.read(length).decode())
        password = (form.get("password") or [""])[0].strip()
        if config.WEB_PASSWORD and hmac.compare_digest(password, config.WEB_PASSWORD):
            cookie = f"{COOKIE}={_token()}; Max-Age=2592000; Path=/; HttpOnly; SameSite=Lax"
            return self._send(303, "", headers=(("Location", "/"), ("Set-Cookie", cookie)))
        self._send(200, LOGIN_PAGE.replace("{error}", '<div class="err">Неверный пароль</div>'))

    def do_GET(self):
        if not self._authorized():
            return self._send(200, LOGIN_PAGE.replace("{error}", ""))
        if not config.PAGE.exists():
            medcard.rebuild_page()
        self._send(200, config.PAGE.read_bytes())

    def log_message(self, *args):
        pass


def serve():
    server = ThreadingHTTPServer(("0.0.0.0", config.WEB_PORT), Handler)
    print(f"Страница: http://<адрес-сервера>:{config.WEB_PORT}  (пароль из WEB_PASSWORD)")
    server.serve_forever()
