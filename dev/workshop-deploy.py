#!/usr/bin/env python3
"""Приём заливки на учебном сервере: агент участника присылает проект с ноутбука одной командой.

Работает от root на порту 8700. Вход — номер участника и пароль (userN / os86NN).
  POST /deploy          тело — архив проекта (.tar.gz или .zip). Код заменяется, данные медкарты
                        (data/, medcard/, inbox/) остаются серверные: их меняют бот и команды ниже.
                        Из присланного .env берётся только TELEGRAM_BOT_TOKEN.
  POST /run?cmd=add&file=<путь>[&file=…]   добавить документ в медкарту (python3 run.py add …);
                        параметры можно и в теле: curl … --data-urlencode "file=new-documents/<файл>"
  POST /run?cmd=ct&file=ct-disk-copy       достать кадры КТ с диска
  POST /run?cmd=ask&q=<вопрос>             спросить по медкарте
  POST /run?cmd=check                      проверить настройки
  GET  /status                             что запущено и последние строки журналов
  GET  /data                               архив серверных данных (data/, medcard/) — забрать к себе
"""
import base64
import io
import subprocess
import tarfile
import time
import urllib.parse
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 8700
USERS = range(1, 16)
MAX_BYTES = 80 * 1024 * 1024
KEEP = ("data/", "medcard/", "inbox/", ".git/", "__pycache__/")  # серверное, из архива не берём
KEEP_FILES = {".env", "bot.log", "health-os.log", "dashboard/data.js", "dashboard/health-dashboard.html"}


def project(user):
    return Path(f"/home/{user}/health-os")


def sh(args, timeout=60):
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    return (r.stdout + r.stderr).strip()


def as_user(user, args, timeout=300):
    return subprocess.run(["/usr/sbin/runuser", "-u", user, "--", *args], cwd=project(user), capture_output=True,
                          text=True, timeout=timeout,
                          env={"PATH": "/usr/bin:/bin", "HOME": f"/home/{user}", "LANG": "C.UTF-8",
                               "PYTHONIOENCODING": "utf-8"})


def members(blob):
    """Список (путь, байты) из архива; общий верхний каталог (health-os-workshop/…) срезается."""
    items = []
    if blob[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            for i in z.infolist():
                if not i.is_dir():
                    items.append((i.filename.replace("\\", "/"), z.read(i)))
    else:
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:*") as t:
            for m in t.getmembers():
                if m.isfile():
                    items.append((m.name.replace("\\", "/"), t.extractfile(m).read()))
    items = [(n[2:] if n.startswith("./") else n, b) for n, b in items]
    if not any(n == "run.py" for n, _ in items):  # проект упакован вместе с папкой — срезаем её
        roots = sorted({n.rsplit("/", 1)[0] for n, _ in items if n.endswith("/run.py")}, key=len)
        if roots:
            items = [(n[len(roots[0]) + 1:], b) for n, b in items if n.startswith(roots[0] + "/")]
    return items


def token_of(env_text):
    for line in env_text.splitlines():
        if line.strip().startswith("TELEGRAM_BOT_TOKEN=") and line.split("=", 1)[1].strip().strip('"'):
            return line.split("=", 1)[1].strip().strip('"')
    return None


def deploy(user, blob):
    items = members(blob)
    if not any(n == "run.py" for n, _ in items):
        return 400, "В архиве нет run.py — упакуй саму папку проекта (где лежат run.py и app/)."
    root = project(user)
    token, written = None, 0
    for name, data in items:
        if name.startswith("/") or ".." in name.split("/"):
            continue
        if name == ".env":
            token = token_of(data.decode("utf-8", "ignore"))
            continue
        if (name in KEEP_FILES or name.startswith(KEEP) or "/__pycache__/" in name or name.endswith(".pyc")
                or name.rsplit("/", 1)[-1].startswith("._") or name.endswith(".DS_Store")):  # служебное macOS
            continue
        dst = root / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        written += 1
    sh(["chown", "-R", f"{user}:{user}", str(root)])
    log = [f"Залито файлов: {written}. Данные медкарты на сервере не тронуты."]
    env = root / ".env"
    if token:
        lines = [l for l in env.read_text().splitlines() if not l.startswith("TELEGRAM_BOT_TOKEN=")]
        env.write_text("\n".join(lines + [f"TELEGRAM_BOT_TOKEN={token}"]) + "\n")
        log.append("Токен бота записан на сервер.")
    build = as_user(user, ["python3", "dashboard/build.py"], 120)
    log.append("Страница пересобрана." if build.returncode == 0 else
               "ОШИБКА при сборке страницы:\n" + (build.stdout + build.stderr)[-3000:])
    sh(["systemctl", "restart", f"healthos-web@{user}"])
    if (root / "app" / "bot.py").exists():
        if token_of(env.read_text()):
            sh(["systemctl", "enable", "-q", f"healthos-bot@{user}"])
            sh(["systemctl", "restart", f"healthos-bot@{user}"])
            log.append("Бот перезапущен.")
        else:
            log.append("Бот есть в коде, но токена нет: впиши TELEGRAM_BOT_TOKEN в .env и залей ещё раз.")
    time.sleep(3)
    log.append(status(user))
    return 200, "\n".join(log)


def status(user):
    n = int(user[4:])
    out = [f"Страница: http://2.31.18.229:{8600 + n}  (пароль os{8600 + n})"]
    for unit, label in ((f"healthos-web@{user}", "страница"), (f"healthos-bot@{user}", "бот")):
        state = sh(["systemctl", "is-active", unit])
        out.append(f"{label}: {'работает' if state == 'active' else state}")
        if state not in ("active", "inactive"):
            out.append(sh(["journalctl", "-u", unit, "-n", "15", "--no-pager", "-o", "cat"]))
    botlog = project(user) / "bot.log"
    if botlog.exists() and sh(["systemctl", "is-active", f"healthos-bot@{user}"]) != "inactive":
        out.append("Последние строки журнала бота:\n" + "\n".join(botlog.read_text(errors="ignore").splitlines()[-8:]))
    return "\n".join(out)


def run(user, q):
    cmd = (q.get("cmd") or [""])[0]
    if cmd == "add":
        args = ["add", *q.get("file", [])]
    elif cmd == "ct":
        args = ["ct", (q.get("file") or ["ct-disk-copy"])[0]]
    elif cmd == "ask":
        args = ["ask", (q.get("q") or [""])[0]]
    elif cmd == "check":
        args = ["check"]
    else:
        return 400, "Неизвестная команда. Можно: add, ct, ask, check."
    for a in args[1:]:
        if cmd != "ask" and (a.startswith("/") or ".." in a):
            return 400, "Пути — только внутри проекта, например new-documents/<файл>."
    r = as_user(user, ["python3", "run.py", *args], 600)
    if cmd in ("add", "ct"):
        as_user(user, ["python3", "dashboard/build.py"], 120)
    return 200, (r.stdout + r.stderr).strip()[-6000:] or "(команда ничего не вывела)"


def data_archive(user):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for part in ("data", "medcard"):
            p = project(user) / part
            if p.exists():
                t.add(p, arcname=part, filter=lambda ti: None if ti.name.endswith(".bot-owner") else ti)
    return buf.getvalue()


class H(BaseHTTPRequestHandler):
    def user(self):
        try:
            u, p = base64.b64decode(self.headers.get("Authorization", "").split(" ", 1)[1]).decode().split(":", 1)
            n = int(u.removeprefix("user"))
        except Exception:
            return None
        return u if n in USERS and u == f"user{n}" and p == f"os{8600 + n}" else None

    def reply(self, code, text, ctype="text/plain; charset=utf-8"):
        body = text if isinstance(text, bytes) else (text + "\n").encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def guard(self):
        user = self.user()
        if not user:
            self.reply(401, "Нужен номер и пароль, например: -u user7:os8607")
        return user

    def url(self):  # русские буквы, присланные без %-кодирования, приходят как latin-1
        try:
            return urllib.parse.urlparse(self.path.encode("latin-1").decode("utf-8"))
        except UnicodeError:
            return urllib.parse.urlparse(self.path)

    def do_GET(self):
        url = self.url()
        if url.path == "/":
            return self.reply(200, __doc__)
        user = self.guard()
        if not user:
            return
        if url.path == "/status":
            return self.reply(200, status(user))
        if url.path == "/data":
            return self.reply(200, data_archive(user), "application/gzip")
        self.reply(404, "Нет такого адреса. Есть: /deploy, /run, /status, /data")

    def do_POST(self):
        url = self.url()
        user = self.guard()
        if not user:
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BYTES:
            return self.reply(413, "Архив больше 80 МБ — не клади в него .git и лишнее.")
        blob = self.rfile.read(length)
        try:
            if url.path == "/deploy":
                if not blob:
                    return self.reply(400, "Пустое тело: пришли архив проекта (--data-binary @health-os.tar.gz).")
                code, text = deploy(user, blob)
            elif url.path == "/run":
                q = urllib.parse.parse_qs(url.query)
                for k, v in urllib.parse.parse_qs(blob.decode("utf-8", "ignore")).items():  # --data-urlencode
                    q.setdefault(k, []).extend(v)
                code, text = run(user, q)
            else:
                code, text = 404, "Нет такого адреса. Есть: /deploy, /run, /status, /data"
        except Exception as e:
            code, text = 500, f"Ошибка на сервере: {e}"
        print(user, url.path, code, flush=True)
        self.reply(code, text)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
