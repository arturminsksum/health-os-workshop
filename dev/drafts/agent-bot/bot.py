#!/usr/bin/env python3
"""Telegram-бот «доктор» для учебной Health OS.

Что умеет:
  - вопрос текстом            — отвечает по медкарте (data/health-record.json);
  - фото / скрин / PDF        — кладёт во inbox/ и просит агента разобрать по правилам CLAUDE.md;
  - /dashboard                — присылает дашборд одним html-файлом.

Мозг — агент, который уже стоит на сервере и залогинен по подписке: Claude Code или Codex.
API-ключ не нужен. Запасной мозг для вопросов — OpenAI по ключу (OPENAI_API_KEY), если подписка
упёрлась в лимит.

Настройки — в bot/.env (пример: bot/.env.example). Запуск: python3 bot/bot.py
Проверка без Telegram:  python3 bot/bot.py --ask "как менялся LDL"
                        python3 bot/bot.py --ingest samples/new/2026-09-24-wisla-app-screen-1.png
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INBOX = ROOT / "inbox"
OWNER_FILE = ROOT / "bot" / ".owner"
DASHBOARD = ROOT / "dashboard" / "health-dashboard.html"
AGENT_TIMEOUT = 600


def load_env():
    env_file = ROOT / "bot" / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


load_env()
BRAIN = os.environ.get("BRAIN", "auto")              # auto | claude | codex
CODEX_MODEL = os.environ.get("CODEX_MODEL", "gpt-5.5")  # на подписке ChatGPT модель надо назвать явно


def pick_brain():
    if BRAIN in ("claude", "codex"):
        return BRAIN
    for name in ("claude", "codex"):
        if shutil.which(name):
            return name
    return None


ASK_PROMPT = ("Ты — помощник по личной медкарте. Ответь на вопрос пользователя по данным из "
              "data/health-record.json (при необходимости смотри data/analyses/). Коротко, по-русски, "
              "с цифрами и датами. Не ставь диагнозов и не назначай лечение.\n\nВопрос: {q}")

INGEST_PROMPT = ("В папку inbox/ пришли новые файлы: {files}. Обработай их строго по разделу "
                 "«Главная задача» из CLAUDE.md (скрины одной даты и лаборатории — один анализ). "
                 "Для PDF без картинки можно использовать pdftotext. В конце ответь пользователю "
                 "коротко, как требует шаг 8.")


def run_agent(prompt, write=False, images=()):
    """Запускает агента в папке репозитория и возвращает его финальный ответ текстом."""
    brain = pick_brain()
    if brain is None:
        return "На сервере не найден ни Claude Code, ни Codex — сначала поставь и залогинь агента."
    if brain == "claude":
        tools = "Read Edit Write Bash(python3 dashboard/build.py) Bash(mv:*) Bash(mkdir:*) Bash(pdftotext:*)" \
            if write else "Read"
        cmd = ["claude", "-p", prompt, "--allowedTools", tools]
        if write:
            cmd += ["--permission-mode", "acceptEdits"]
        out_file = None
    else:
        out_file = Path(tempfile.mkstemp(suffix=".txt")[1])
        cmd = ["codex", "exec", "-m", CODEX_MODEL, "--skip-git-repo-check",
               "--sandbox", "workspace-write" if write else "read-only", "-o", str(out_file)]
        for img in images:
            cmd += ["-i", str(img)]
        cmd += ["--", prompt]  # без «--» Codex принимает текст задания за ещё одну картинку
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=AGENT_TIMEOUT,
                           encoding="utf-8")
    except subprocess.TimeoutExpired:
        return "Агент не уложился в 10 минут — попробуй ещё раз."
    text = out_file.read_text(encoding="utf-8").strip() if out_file and out_file.exists() else r.stdout.strip()
    if out_file:
        out_file.unlink(missing_ok=True)
    if r.returncode != 0 or not text:
        err = (r.stderr or r.stdout).strip().splitlines()[-3:]
        if os.environ.get("OPENAI_API_KEY") and not write:
            return ask_openai(prompt)
        return f"Агент ({brain}) не ответил:\n" + "\n".join(err)
    return text


def ask_openai(prompt):
    """Запасной мозг для вопросов: вся медкарта в контекст, ответ одной моделью по ключу."""
    record = (ROOT / "data" / "health-record.json").read_text(encoding="utf-8")
    body = {"model": os.environ.get("OPENAI_MODEL", "gpt-5-mini"),
            "messages": [{"role": "system", "content": "Медкарта пользователя (JSON):\n" + record},
                         {"role": "user", "content": prompt}]}
    req = urllib.request.Request("https://api.openai.com/v1/chat/completions",
                                 data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": "Bearer " + os.environ["OPENAI_API_KEY"],
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)["choices"][0]["message"]["content"].strip()


def ingest(paths):
    names = ", ".join(p.name for p in paths)
    images = [p for p in paths if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
    return run_agent(INGEST_PROMPT.format(files=names), write=True, images=images)


# ---------------- Telegram ----------------

def is_owner(update):
    """Первый, кто написал боту /start, становится владельцем; остальным бот не отвечает."""
    uid = str(update.effective_user.id)
    if not OWNER_FILE.exists():
        OWNER_FILE.write_text(uid, encoding="utf-8")
        return True
    return OWNER_FILE.read_text(encoding="utf-8").strip() == uid


async def reply_long(msg, text):
    for i in range(0, len(text), 4000):
        await msg.reply_text(text[i:i + 4000])


async def on_start(update, context):
    if not is_owner(update):
        return
    await update.message.reply_text(
        "Привет! Я доктор твоей медкарты.\n"
        "• Спроси текстом: «как менялся мой холестерин?»\n"
        "• Пришли фото, скрин или PDF анализа — разберу и добавлю в карту.\n"
        "• /dashboard — пришлю дашборд одним файлом.")


async def on_text(update, context):
    if not is_owner(update):
        return
    await update.message.chat.send_action("typing")
    answer = await asyncio.to_thread(run_agent, ASK_PROMPT.format(q=update.message.text))
    await reply_long(update.message, answer)


PENDING = {}  # chat_id -> список файлов, пришедших пачкой (альбом скринов)


async def on_file(update, context):
    if not is_owner(update):
        return
    msg = update.message
    if msg.photo:
        tg_file, name = await msg.photo[-1].get_file(), f"photo-{msg.message_id}.jpg"
    else:
        tg_file, name = await msg.document.get_file(), msg.document.file_name or f"file-{msg.message_id}"
    INBOX.mkdir(exist_ok=True)
    path = INBOX / name
    await tg_file.download_to_drive(path)
    chat = msg.chat_id
    first = chat not in PENDING
    PENDING.setdefault(chat, []).append(path)
    if not first:
        return
    await msg.reply_text("Принял, жду остальные файлы пару секунд и начинаю разбор…")
    await asyncio.sleep(4)  # альбом из нескольких скринов приходит отдельными сообщениями
    batch = PENDING.pop(chat)
    await msg.chat.send_action("typing")
    answer = await asyncio.to_thread(ingest, batch)
    await reply_long(msg, answer)


async def on_dashboard(update, context):
    if not is_owner(update):
        return
    subprocess.run([sys.executable, str(ROOT / "dashboard" / "build.py")], cwd=ROOT, check=False)
    if DASHBOARD.exists():
        with DASHBOARD.open("rb") as f:
            await update.message.reply_document(f, filename="health-dashboard.html",
                                                caption="Открой файл — это весь дашборд, работает без интернета.")
    else:
        await update.message.reply_text("Дашборд не собрался — проверь dashboard/build.py.")


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--ask":
        print(run_agent(ASK_PROMPT.format(q=" ".join(sys.argv[2:]))))
        return
    if len(sys.argv) > 2 and sys.argv[1] == "--ingest":
        INBOX.mkdir(exist_ok=True)
        paths = []
        for src in sys.argv[2:]:
            dst = INBOX / Path(src).name
            shutil.copy(src, dst)
            paths.append(dst)
        print(ingest(paths))
        return
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        sys.exit("Нет TELEGRAM_BOT_TOKEN: возьми токен у @BotFather и впиши в bot/.env")
    from telegram.ext import Application, CommandHandler, MessageHandler, filters
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(CommandHandler("dashboard", on_dashboard))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, on_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    print(f"Бот запущен, мозг: {pick_brain()}. Напиши ему /start в Telegram.")
    app.run_polling()


if __name__ == "__main__":
    main()
