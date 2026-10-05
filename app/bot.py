"""Telegram-бот «доктор»: отвечает по медкарте, принимает анализы, напоминает о пересдаче.

Работает на стандартном Python, без сторонних библиотек: опрашивает Telegram и отвечает.
Первый, кто напишет боту /start, становится его владельцем — остальным бот не отвечает.
"""
import json
import threading
import time
import urllib.parse
import urllib.request
import uuid
from datetime import date, datetime, timedelta

import ask
import config
import medcard

API = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}"
ALBUM_WAIT = 3  # секунд ждём остальные скрины, если человек прислал несколько файлов разом


def call(method, _wait=60, **params):
    data = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}).encode()
    with urllib.request.urlopen(f"{API}/{method}", data=data, timeout=_wait) as r:
        return json.load(r)["result"]


def send(chat_id, text):
    for i in range(0, len(text), 4000):
        call("sendMessage", chat_id=chat_id, text=text[i:i + 4000])


def to_html(text):
    """**жирный** из ответа модели в HTML Telegram; всё остальное экранируем («< 5.2» не ломает разметку)."""
    import html
    import re
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html.escape(text))


def send_photo(chat_id, png, caption):
    boundary = uuid.uuid4().hex
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
             for k, v in (("chat_id", str(chat_id)), ("caption", caption), ("parse_mode", "HTML"))]
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="chart.png"\r\n'
                 f"Content-Type: image/png\r\n\r\n".encode() + png + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(f"{API}/sendPhoto", data=b"".join(parts),
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    urllib.request.urlopen(req, timeout=120).read()


def send_document(chat_id, path, caption):
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in (("chat_id", str(chat_id)), ("caption", caption)):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="{path.name}"\r\n'
                 f"Content-Type: text/html\r\n\r\n".encode() + path.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(f"{API}/sendDocument", data=b"".join(parts),
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    urllib.request.urlopen(req, timeout=120).read()


def download(file_id, name):
    info = call("getFile", file_id=file_id)
    config.INBOX.mkdir(exist_ok=True)
    dst = config.INBOX / name
    url = f"https://api.telegram.org/file/bot{config.TELEGRAM_BOT_TOKEN}/{info['file_path']}"
    with urllib.request.urlopen(url, timeout=120) as r:
        dst.write_bytes(r.read())
    return dst


def owner():
    return config.OWNER_FILE.read_text().strip() if config.OWNER_FILE.exists() else None


def is_owner(chat_id):
    current = owner()
    if current is None:
        config.OWNER_FILE.parent.mkdir(exist_ok=True)
        config.OWNER_FILE.write_text(str(chat_id))
        return True
    return current == str(chat_id)


HELP = ("Я — доктор твоей медкарты.\n"
        "• Спроси текстом: «как менялся мой холестерин?», «как я спал на этой неделе?»\n"
        "• Пришли фото, скриншот или PDF анализа или заключения врача — разберу и добавлю в карту.\n"
        "• /page — пришлю страницу медкарты одним файлом\n"
        "• /remind — проверю напоминания прямо сейчас")


# ---------- напоминания ----------

def due_reminders(days_ahead=None):
    days_ahead = config.REMIND_DAYS_AHEAD if days_ahead is None else days_ahead
    limit = date.today() + timedelta(days=days_ahead)
    out = []
    for r in medcard.load().get("reminders", []):
        if r.get("status") == "planned" and date.fromisoformat(r["due"]) <= limit:
            late = (date.today() - date.fromisoformat(r["due"])).days
            when = f"просрочено на {late} дн" if late > 0 else f"до {r['due']}"
            why = r.get("why", "").rstrip(".")
            out.append(f"• {r['what']} — {when}" + (f" ({why})" if why else ""))
    return out


def remind(chat_id, manual=False):
    items = due_reminders()
    if items:
        send(chat_id, "Пора пересдать:\n" + "\n".join(items))
    elif manual:
        send(chat_id, f"Ближайшие {config.REMIND_DAYS_AHEAD} дней ничего пересдавать не нужно.")


def reminder_loop():
    """Раз в день в REMIND_HOUR бот сам пишет владельцу, если подходит срок пересдачи."""
    last_day = None
    while True:
        now = datetime.now()
        if now.hour == config.REMIND_HOUR and last_day != now.date() and owner():
            last_day = now.date()
            try:
                remind(owner())
            except Exception as e:
                print("напоминания:", e)
        time.sleep(60)


# ---------- сообщения ----------

def handle_files(chat_id, files):
    work = Working(chat_id, f"📄 Принял {len(files)} файл(а), читаю документ — секунд 10…")
    try:
        reply = medcard.ingest(files)
        if config.PUBLIC_URL:
            reply += f"\n\nСтраница медкарты: {config.PUBLIC_URL}"
    except Exception as e:
        reply = f"Не получилось разобрать: {e}"
    work.finish()
    send(chat_id, reply)


def handle(msg, albums):
    chat_id = msg["chat"]["id"]
    text = msg.get("text", "")
    if text.startswith("/start"):
        if is_owner(chat_id):
            send(chat_id, HELP)
        return
    if not is_owner(chat_id):
        return
    if text.startswith("/page"):
        medcard.rebuild_page()
        send_document(chat_id, config.PAGE, "Открой файл — это вся медкарта, работает без интернета.")
        return
    if text.startswith("/remind"):
        remind(chat_id, manual=True)
        return
    if "photo" in msg or "document" in msg:
        if "photo" in msg:
            path = download(msg["photo"][-1]["file_id"], f"photo-{msg['message_id']}.jpg")
        else:
            doc = msg["document"]
            path = download(doc["file_id"], doc.get("file_name") or f"file-{msg['message_id']}")
        key = msg.get("media_group_id") or f"single-{msg['message_id']}"
        albums.setdefault(key, {"chat": chat_id, "files": [], "at": time.time()})
        albums[key]["files"].append(path)
        albums[key]["at"] = time.time()
        return
    if text:
        threading.Thread(target=reply_text, args=(chat_id, text), daemon=True).start()


class Working:
    """Пока модель думает: сразу пишем «смотрю…» и держим «печатает…», потом служебное сообщение убираем."""

    def __init__(self, chat_id, text):
        self.chat_id, self.done = chat_id, threading.Event()
        self.msg_id = call("sendMessage", chat_id=chat_id, text=text)["message_id"]
        threading.Thread(target=self._typing, daemon=True).start()

    def _typing(self):
        while not self.done.is_set():
            try:
                call("sendChatAction", chat_id=self.chat_id, action="typing")
            except Exception:
                pass
            self.done.wait(4)

    def finish(self):
        self.done.set()
        try:
            call("deleteMessage", chat_id=self.chat_id, message_id=self.msg_id)
        except Exception:
            pass


def reply_text(chat_id, text):
    """Отвечаем в отдельном потоке: пока модель думает, бот принимает следующие сообщения."""
    work = Working(chat_id, "🔎 Смотрю медкарту…")
    try:
        res = ask.answer(text, chat_id)
        body = to_html(res["text"])
        png = None
        if res["charts"]:
            try:
                import charts
                png = charts.render(res["charts"])
            except ImportError:
                print("графики выключены: нет Pillow (sudo apt install python3-pil)")
        if png and len(body) <= 1000:
            send_photo(chat_id, png, body)
        else:
            if png:
                send_photo(chat_id, png, "")
            call("sendMessage", chat_id=chat_id, text=body, parse_mode="HTML")
    except Exception as e:
        send(chat_id, f"Не получилось ответить: {e}")
    finally:
        work.finish()


def run():
    if not config.TELEGRAM_BOT_TOKEN:
        print("Бот не запущен: нет TELEGRAM_BOT_TOKEN в .env (возьми токен у @BotFather)")
        return
    threading.Thread(target=reminder_loop, daemon=True).start()
    me = call("getMe")
    print(f"Бот @{me['username']} запущен. Напиши ему /start в Telegram.")
    offset, albums = None, {}
    while True:
        try:
            poll = 1 if albums else 25  # ждём новые сообщения до 25 с, но не держим недособранный альбом
            updates = call("getUpdates", _wait=poll + 15, offset=offset, timeout=poll)
        except Exception as e:
            print("Telegram недоступен:", e)
            time.sleep(5)
            continue
        for u in updates:
            offset = u["update_id"] + 1
            if "message" in u:
                try:
                    handle(u["message"], albums)
                except Exception as e:
                    print("ошибка обработки:", e)
        for key in [k for k, a in albums.items() if time.time() - a["at"] > ALBUM_WAIT]:
            a = albums.pop(key)
            threading.Thread(target=handle_files, args=(a["chat"], a["files"]), daemon=True).start()
