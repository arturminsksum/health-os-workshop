"""Настройки из файла .env в корне проекта (пример — .env.example)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RECORD = ROOT / "data" / "health-record.json"
GARMIN = ROOT / "data" / "garmin.json"
MEDCARD = ROOT / "medcard"
INBOX = ROOT / "inbox"
PAGE = ROOT / "dashboard" / "health-dashboard.html"
OWNER_FILE = ROOT / "data" / ".bot-owner"


def _load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


_load_env()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-6-luna")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
WEB_PORT = int(os.environ.get("WEB_PORT", "8080"))
WEB_PASSWORD = os.environ.get("WEB_PASSWORD", "")
PUBLIC_URL = os.environ.get("PUBLIC_URL", "")          # адрес страницы, который бот присылает в ответах
REMIND_HOUR = int(os.environ.get("REMIND_HOUR", "9"))  # во сколько бот проверяет напоминания
REMIND_DAYS_AHEAD = int(os.environ.get("REMIND_DAYS_AHEAD", "14"))
