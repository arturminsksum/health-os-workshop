"""Медкарта: чтение, запись и приём новых документов (анализы и заключения врачей).

Модель только читает документ и возвращает, что в нём написано. Пересчёт единиц, флаги «выше/ниже
нормы», раскладка по папкам и итоговый ответ человеку — делает код, чтобы цифры не выдумывались.
"""
import json
import re
import shutil
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import config
import llm
from markers import MARKERS, catalog_text, flag, to_si

FLAG_RU = {"high": "выше нормы", "low": "ниже нормы", "ok": "в норме"}

SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["documents"],
    "properties": {"documents": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["doc_type", "date", "source_name", "language", "markers", "visit", "reminders"],
        "properties": {
            "doc_type": {"type": "string", "enum": ["analysis", "visit", "other"]},
            "date": {"type": "string", "description": "дата взятия анализа или приёма, YYYY-MM-DD"},
            "source_name": {"type": "string", "description": "лаборатория или клиника"},
            "language": {"type": "string"},
            "markers": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["key", "name", "value", "unit", "ref", "flag"],
                "properties": {
                    "key": {"type": "string", "description": "ключ из справочника или пустая строка"},
                    "name": {"type": "string", "description": "название по-русски"},
                    "value": {"type": "number", "description": "число ровно как в документе"},
                    "unit": {"type": "string", "description": "единицы ровно как в документе"},
                    "ref": {"type": "string", "description": "норма как в документе"},
                    "flag": {"type": "string", "enum": ["high", "low", "ok"]}}}},
            "visit": {"type": "object", "additionalProperties": False,
                      "required": ["doctor", "specialty", "clinic", "complaints", "findings", "diagnosis", "recs"],
                      "properties": {k: {"type": "string"} for k in
                                     ("doctor", "specialty", "clinic", "complaints", "findings", "diagnosis")}
                      | {"recs": {"type": "array", "items": {"type": "string"}}}},
            "reminders": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["what", "why", "due", "markers"],
                "properties": {"what": {"type": "string"}, "why": {"type": "string"},
                               "due": {"type": "string", "description": "YYYY-MM-DD"},
                               "markers": {"type": "array", "items": {"type": "string"}}}}}}}}}}

PROMPT = """Ты читаешь медицинские документы пользователя: PDF, скриншоты, фото бумажек. Язык любой.
Несколько скринов одной даты и одной лаборатории — это ОДИН документ. Разные документы — разные элементы.

Для анализа (doc_type=analysis) перепиши каждый показатель: key — из справочника ниже, если это он
(иначе пустая строка), name — по-русски, value и unit — РОВНО как в документе, без пересчёта.
Для заключения врача (doc_type=visit) заполни visit; рекомендации с контролем («повторить через
3 месяца», «контроль в марте») переведи в reminders с конкретной датой due от даты приёма и списком
ключей показателей, которые надо пересдать. Для анализа visit заполни пустыми строками.
Никогда не выдумывай значения: не видно цифру — не включай показатель.

Справочник показателей (key: названия):
{catalog}
"""


def load():
    return json.loads(config.RECORD.read_text(encoding="utf-8"))


def save(record):
    record["generated"] = date.today().isoformat()
    config.RECORD.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rebuild_page():
    subprocess.run([sys.executable, str(config.ROOT / "dashboard" / "build.py")], cwd=config.ROOT,
                   capture_output=True, check=False)


def _safe(s):
    return re.sub(r'[\\/:*?"<>|]+', " ", s).strip()


def _store_originals(paths, folder: Path, stem: str):
    folder.mkdir(parents=True, exist_ok=True)
    stored = []
    for i, p in enumerate(paths, 1):
        suffix = f" ({i})" if len(paths) > 1 else ""
        dst = folder / f"{stem}{suffix}{p.suffix.lower()}"
        shutil.copy(p, dst)
        stored.append(dst)
    return stored


def _event(record, kind, doc_date, title, lines, markers, source):
    """Лента «Что нового»: когда и что добавилось — страница подсвечивает это, пока не посмотрели."""
    record.setdefault("events", []).append({
        "added": datetime.now().isoformat(timespec="seconds"), "kind": kind, "date": doc_date,
        "title": title, "lines": [x.lstrip("• ") for x in lines], "markers": markers, "source": source})


def _add_analysis(record, doc, paths):
    stem = _safe(f"{doc['date']} анализ, {doc['source_name']}")
    stored = _store_originals(paths, config.MEDCARD / doc["date"][:4], stem)
    src = str(stored[0].relative_to(config.ROOT))
    lines, rows = [], []
    by_key = {b["key"]: b for b in record["biomarkers"]}
    for m in doc["markers"]:
        key = m["key"] if m["key"] in MARKERS else "x-" + _safe(m["name"]).lower().replace(" ", "-")
        if key in MARKERS:
            value, unit, ref, fl = to_si(key, m["value"], m["unit"]), MARKERS[key]["si"], MARKERS[key]["ref_si"], None
            fl = flag(key, value)
        else:
            value, unit, ref, fl = m["value"], m["unit"], m["ref"], m["flag"]
        orig = f" ({m['value']:g} {m['unit']})" if value != m["value"] else ""
        b = by_key.get(key)
        if b is None:
            info = MARKERS.get(key, {})
            b = {"key": key, "name": info.get("short", m["name"]), "fullName": info.get("ru", m["name"]),
                 "group": info.get("group", "Другое"), "unit": unit, "ref": ref,
                 "low": info.get("lo"), "high": info.get("hi"), "series": []}
            record["biomarkers"].append(b)
            by_key[key] = b
        prev = [p for p in b["series"] if p["date"] < doc["date"]]
        b["series"] = [p for p in b["series"] if p["date"] != doc["date"]]
        b["series"].append({"date": doc["date"], "value": value, "flag": fl, "lab": doc["source_name"], "source": src})
        b["series"].sort(key=lambda p: p["date"])
        was = f", было {prev[-1]['value']:g} ({prev[-1]['date']})" if prev else ""
        lines.append(f"• {b['name']}: {value:g} {unit}{orig} — {FLAG_RU[fl]}{was}")
        rows.append(f"| {b['name']} | {value:g}{orig} | {unit} | {ref} | {FLAG_RU[fl]} |")
    md = (f"# {doc['date']} — анализ, {doc['source_name']}\n\nОригинал: {', '.join(p.name for p in stored)}\n\n"
          "| Показатель | Значение | Единицы | Норма | Флаг |\n|---|---|---|---|---|\n" + "\n".join(rows) + "\n")
    (stored[0].parent / f"{stem}.md").write_text(md, encoding="utf-8")
    keys = {by_key[k]["key"] for k in by_key if any(p["date"] == doc["date"] for p in by_key[k]["series"])}
    closed = []
    for r in record["reminders"]:
        if r.get("status") == "planned" and set(r.get("markers", [])) & keys:
            r["status"] = "done"
            closed.append(r["what"])
    _event(record, "analysis", doc["date"], f"Анализ, {doc['source_name']}", lines, sorted(keys), src)
    head = f"Добавил анализ от {doc['date']} ({doc['source_name']}):"
    tail = f"\nЗакрыл напоминание: {', '.join(closed)}." if closed else ""
    return head + "\n" + "\n".join(lines) + tail


def _add_visit(record, doc, paths):
    v = doc["visit"]
    stem = _safe(f"{doc['date']} {v['specialty'] or 'врач'}, {v['clinic'] or doc['source_name']}")
    stored = _store_originals(paths, config.MEDCARD / "визиты к врачам", stem)
    src = str(stored[0].relative_to(config.ROOT))
    record["visits"] = [x for x in record["visits"] if x["date"] != doc["date"]]
    record["visits"].append({"date": doc["date"], "doctor": f"{v['specialty']} {v['doctor']}".strip(),
                             "clinic": v["clinic"], "diagnosis": v["diagnosis"], "findings": v["findings"],
                             "recs": v["recs"], "source": src})
    record["visits"].sort(key=lambda x: x["date"])
    added = []
    for i, r in enumerate(doc["reminders"], 1):
        record["reminders"].append({"id": f"{doc['date']}-{i}", "what": r["what"], "why": r["why"],
                                    "due": r["due"], "status": "planned", "markers": r["markers"]})
        added.append(f"• {r['what']} — до {r['due']}")
    recs = "\n".join(f"{i}. {x}" for i, x in enumerate(v["recs"], 1))
    md = (f"# {doc['date']} — {v['specialty']} {v['doctor']}, {v['clinic']}\n\nОригинал: "
          f"{', '.join(p.name for p in stored)}\n\n**Жалобы:** {v['complaints']}\n\n**Осмотр:** {v['findings']}\n\n"
          f"**Диагноз:** {v['diagnosis']}\n\n**Рекомендации:**\n\n{recs}\n")
    (stored[0].parent / f"{stem}.md").write_text(md, encoding="utf-8")
    _event(record, "visit", doc["date"], f"Визит: {v['specialty']} {v['doctor'].rstrip('.')}".strip(),
           [f"• Диагноз: {v['diagnosis']}"] + added, [k for r in doc["reminders"] for k in r["markers"]], src)
    text = f"Добавил визит от {doc['date']}: {v['specialty']} {v['doctor'].rstrip('.')}.\nДиагноз: {v['diagnosis']}"
    if added:
        text += "\nНовые напоминания:\n" + "\n".join(added)
    return text


def _refresh_status(record):
    """Короткий статус наверху страницы — переписываем после каждого нового документа."""
    brief = {"biomarkers": [{"key": b["key"], "name": b["name"], "unit": b["unit"], "ref": b["ref"],
                             "last": b["series"][-3:]} for b in record["biomarkers"]],
             "reminders": [r for r in record["reminders"] if r.get("status") == "planned"]}
    schema = {"type": "object", "additionalProperties": False, "required": ["items"],
              "properties": {"items": {"type": "array", "items": {
                  "type": "object", "additionalProperties": False, "required": ["level", "text", "markers"],
                  "properties": {"level": {"type": "string", "enum": ["warn", "ok"]}, "text": {"type": "string"},
                                 "markers": {"type": "array", "items": {"type": "string"}}}}}}}
    res = llm.ask("Напиши 2–4 коротких пункта статуса медкарты по-русски: что изменилось в последних анализах, "
                  "что в норме, на что смотреть. С цифрами и годами. Без диагнозов и назначений. "
                  "В markers — ключи показателей, о которых пункт.\n\n"
                  + json.dumps(brief, ensure_ascii=False), schema=schema)
    record["tldr"] = res["items"]


def ingest(paths):
    """Разобрать файлы и обновить медкарту. Возвращает ответ человеку."""
    paths = [Path(p) for p in paths]
    result = llm.ask(PROMPT.format(catalog=catalog_text()), files=paths, schema=SCHEMA)
    record = load()
    answers = []
    docs = []
    for doc in result["documents"]:  # скрины одного анализа модель иногда отдаёт раздельно — склеиваем
        same = next((d for d in docs if d["doc_type"] == doc["doc_type"] == "analysis"
                     and d["date"] == doc["date"]), None)
        if same:
            same["markers"] += doc["markers"]
        else:
            docs.append(doc)
    for doc in docs:
        if doc["doc_type"] == "analysis" and doc["markers"]:
            answers.append(_add_analysis(record, doc, paths))
        elif doc["doc_type"] == "visit":
            answers.append(_add_visit(record, doc, paths))
    if not answers:
        return "Не нашёл в файле ни анализа, ни заключения врача. Пришли более чёткое фото или PDF."
    _refresh_status(record)
    save(record)
    rebuild_page()
    for p in paths:
        if config.INBOX in p.parents:
            p.unlink(missing_ok=True)
    return "\n\n".join(answers)
