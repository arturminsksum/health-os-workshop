"""Ответы на вопросы по медкарте: вся карта и последние дни часов уходят модели как контекст."""
import json

import config
import llm
import medcard

SYSTEM = ("Ты — внимательный помощник по личной медкарте. Отвечай по-русски, коротко и по делу. "
          "Не ставь диагнозов и не назначай лечение; если вопрос требует врача — так и скажи.\n\n"
          "Сначала пойми, какой это вопрос, и отвечай по правилу:\n"
          "1) Про свои данные (анализы, динамика, сон, пульс, напоминания) — отвечай по медкарте с цифрами и датами, "
          "сравнивай с нормой и прошлыми значениями; в charts перечисли ключи показателей для графика.\n"
          "2) Общий медицинский (что такое ЛПНП, чем опасен низкий витамин D) — объясни простыми словами в 2–3 "
          "строки и привяжи к цифрам пользователя, если они есть.\n"
          "3) Нужен интернет (где пройти обследование, какая клиника или лаборатория, цены, адреса, расписание) — "
          "честно скажи одной фразой, что искать в интернете ты пока не умеешь, и сразу дай полезное из медкарты: "
          "что стоит сделать или сдать (просроченные и ближайшие напоминания, что давно не сдавалось, "
          "стандартный набор по возрасту и полу).\n"
          "4) Не про здоровье — одной-двумя строками скажи, что помогаешь с медкартой, и предложи пример вопроса; "
          "медкарту в такой ответ не тяни.\n"
          "Даты пиши по-человечески: «15 сентября 2026», а не 2026-09-15.\n"
          "Если в медкарте нет данных для ответа — честно скажи, чего не хватает.\n\n"
          "Ответ уходит в Telegram и читается с телефона: 2–6 коротких строк, без цепочек цифр через стрелки — "
          "историю значений покажет график. Главные цифры выдели **так**, другой разметки не используй. "
          "Если вопрос не про анализы — charts оставь пустым.")

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["text", "charts"],
          "properties": {"text": {"type": "string"}, "charts": {"type": "array", "items": {"type": "string"}}}}

HISTORY = {}  # chat_id -> последние реплики, чтобы бот понимал «а что было до этого?»


def _garmin_brief():
    if not config.GARMIN.exists():
        return None
    g = json.loads(config.GARMIN.read_text(encoding="utf-8"))
    days = g.get("days") or g.get("daily") or []
    return {"norms": g.get("norms"), "last_30_days": days[-30:]}


def answer(question, chat_id=None):
    from datetime import date
    context = {"today": date.today().isoformat(), "medcard": medcard.load(), "garmin": _garmin_brief()}
    past = HISTORY.get(chat_id, [])
    dialog = "".join(f"{who}: {text}\n" for who, text in past[-6:])
    prefix = "Переписка до этого:\n" + dialog if dialog else ""  # без «\n» внутри f-строки: Python 3.10 на старых Ubuntu
    prompt = (f"Медкарта и данные часов (JSON):\n{json.dumps(context, ensure_ascii=False)}\n\n"
              f"{prefix}Вопрос: {question}")
    res = llm.ask(prompt, system=SYSTEM, schema=SCHEMA)
    if chat_id is not None:
        HISTORY[chat_id] = (past + [("Пользователь", question), ("Ты", res["text"])])[-6:]
    by_key = {b["key"]: b for b in context["medcard"]["biomarkers"]}
    res["charts"] = [by_key[k] for k in res["charts"] if k in by_key][:4]
    return res
