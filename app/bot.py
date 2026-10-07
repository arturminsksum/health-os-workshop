"""Telegram-бот «доктор»: отвечает на вопросы по медкарте — текстом и графиком.

Работает на стандартном Python, без сторонних библиотек: опрашивает Telegram и отвечает.
Первый, кто напишет боту /start, становится его владельцем — остальным бот не отвечает.
"""
import json
import threading
import time
import urllib.parse
import urllib.request
import uuid

import ask
import config

API = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}"


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


def owner():
    return config.OWNER_FILE.read_text().strip() if config.OWNER_FILE.exists() else None


def is_owner(chat_id):
    current = owner()
    if current is None:
        config.OWNER_FILE.parent.mkdir(exist_ok=True)
        config.OWNER_FILE.write_text(str(chat_id))
        return True
    return current == str(chat_id)


WELCOME = ("Я веду твою медкарту и отвечаю по ней.\n\n"
           "Задай вопрос обычными словами — например, «как менялся мой холестерин?». "
           "Я отвечу по твоим анализам и пришлю график.")


# ---------- сообщения ----------

def handle(msg):
    chat_id = msg["chat"]["id"]
    text = msg.get("text", "")
    if text.startswith("/start"):
        if is_owner(chat_id):
            send(chat_id, WELCOME)
        return
    if not is_owner(chat_id):
        return
    if "photo" in msg or "document" in msg:
        return send(chat_id, "Принимать анализы я научусь на следующем шаге.")
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
    me = call("getMe")
    print(f"Бот @{me['username']} запущен. Напиши ему /start в Telegram.")
    offset = None
    while True:
        try:
            updates = call("getUpdates", _wait=40, offset=offset, timeout=25)  # ждём новые сообщения до 25 с
        except Exception as e:
            print("Telegram недоступен:", e)
            time.sleep(5)
            continue
        for u in updates:
            offset = u["update_id"] + 1
            if "message" in u:
                try:
                    handle(u["message"])
                except Exception as e:
                    print("ошибка обработки:", e)
