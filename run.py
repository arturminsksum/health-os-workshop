#!/usr/bin/env python3
"""Запуск Health OS.

  python3 run.py                    — страница медкарты + Telegram-бот (обычный режим)
  python3 run.py check              — проверить настройки: ключ, бот, порт
  python3 run.py ask "вопрос"       — спросить по медкарте без Telegram
  python3 run.py add файл [файл…]   — добавить анализ или заключение без Telegram
"""
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "app"))

import config  # noqa: E402


def check():
    import json
    import urllib.request
    ok = True
    print(f"Python {sys.version.split()[0]}", "— ок" if sys.version_info >= (3, 10) else "— нужен 3.10 или новее")
    if config.OPENAI_API_KEY:
        try:
            req = urllib.request.Request("https://api.openai.com/v1/models",
                                         headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"})
            urllib.request.urlopen(req, timeout=20).read()
            print("Ключ OpenAI — работает")
        except Exception as e:
            ok = False
            print("Ключ OpenAI — НЕ работает:", e)
    else:
        ok = False
        print("Ключ OpenAI — не вписан в .env (OPENAI_API_KEY)")
    if config.TELEGRAM_BOT_TOKEN:
        try:
            url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getMe"
            me = json.load(urllib.request.urlopen(url, timeout=20))["result"]
            print(f"Бот @{me['username']} — работает")
        except Exception as e:
            ok = False
            print("Токен бота — НЕ работает:", e)
    else:
        print("Токен бота — не вписан (TELEGRAM_BOT_TOKEN); страница будет работать и без бота")
    print(f"Страница — порт {config.WEB_PORT}, пароль {'задан' if config.WEB_PASSWORD else 'НЕ задан (WEB_PASSWORD)'}")
    print("Всё готово, запускай: python3 run.py" if ok else "Поправь пункты выше и запусти проверку ещё раз")


def main():
    args = sys.argv[1:]
    if args[:1] == ["check"]:
        return check()
    if args[:1] == ["ask"]:
        import ask
        return print(ask.answer(" ".join(args[1:])))
    if args[:1] == ["add"]:
        import medcard
        return print(medcard.ingest(args[1:]))
    import bot
    import medcard
    import web
    medcard.rebuild_page()
    threading.Thread(target=web.serve, daemon=True).start()
    bot.run()
    if not config.TELEGRAM_BOT_TOKEN:  # без бота держим работающей хотя бы страницу
        threading.Event().wait()


if __name__ == "__main__":
    main()
