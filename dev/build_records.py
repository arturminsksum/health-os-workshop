#!/usr/bin/env python3
"""Стартовая медкарта вымышленного пациента: то, что «уже разобрано» до урока.

Из patient.py берутся только документы стадии history; документы стадии live участники
добавляют сами через агента или бота. Выход:
  data/analyses/YYYY-MM-DD-slug.md  — по файлу на документ (факты + флаги, без интерпретации)
  data/health-record.json            — машинный свод для дашборда и бота

Запуск: python3 dev/build_records.py
"""
import json
from pathlib import Path

import patient as P

ROOT = Path(__file__).resolve().parent.parent
LAB_NAME = {"ru": "Медлаб-Центр", "pl": "WISŁA", "en": "Northbridge"}
LAB_SLUG = {"ru": "medlab", "pl": "wisla", "en": "northbridge"}
GROUP = {"tc": "Липиды", "ldl": "Липиды", "hdl": "Липиды", "tg": "Липиды", "glu": "Обмен веществ",
         "alt": "Печень", "ast": "Печень", "fer": "Железо и витамины", "vitd": "Железо и витамины",
         "tsh": "Щитовидная железа", "ft4": "Щитовидная железа", "hb": "Кровь"}
SHORT = {"tc": "Холестерин", "ldl": "LDL", "hdl": "HDL", "tg": "Триглицериды", "glu": "Глюкоза",
         "alt": "ALT", "ast": "AST", "fer": "Ферритин", "vitd": "Витамин D", "tsh": "ТТГ",
         "ft4": "Т4 св.", "hb": "Гемоглобин"}
FLAG_RU = {"high": "выше нормы", "low": "ниже нормы", "ok": ""}


def flag(code, v):
    m = P.MARKERS[code]
    if "hi" in m and v > m["hi"]:
        return "high"
    if "lo" in m and v < m["lo"]:
        return "low"
    return "ok"


def orig(code, v, lab):
    """Польская лаба печатала mg/dl — оригинал в скобках, как требует канон единиц."""
    m = P.MARKERS[code]
    if lab == "pl" and "mgdl_k" in m:
        return f"{v:g} ({round(v * m['mgdl_k'])} mg/dl)"
    return f"{v:g}"


def table(rows):
    cols = ["Маркер", "Значение", "Единицы", "Референс", "Флаг"]
    w = [max(len(c), *(len(r[i]) for r in rows)) for i, c in enumerate(cols)]
    line = lambda r: "| " + " | ".join(x.ljust(w[i]) for i, x in enumerate(r)) + " |"
    return "\n".join([line(cols), "| " + " | ".join("-" * x for x in w) + " |", *map(line, rows)])


def write_lab(rec):
    slug = f"{rec['date']}-{LAB_SLUG[rec['lab']]}-analizy"
    rows, notes = [], []
    for code, v in rec["values"].items():
        m, f = P.MARKERS[code], flag(code, v)
        rows.append([SHORT[code], orig(code, v, rec["lab"]), m["si"], m["ref_si"], FLAG_RU[f]])
        if f != "ok":
            notes.append(f"{SHORT[code]} {FLAG_RU[f]}: {v:g} {m['si']} (референс {m['ref_si']}).")
    src = f"samples/history/{rec['date']}-{LAB_SLUG[rec['lab']]}.pdf"
    body = (f"---\ndate: {rec['date']}\nlab: {LAB_NAME[rec['lab']]}\ntype: анализ крови\n"
            f"source: {src}\n---\n\n# Анализ крови {rec['date']} — {LAB_NAME[rec['lab']]}\n\n"
            f"{table(rows)}\n")
    if notes:
        body += "\n## Заметки\n\n" + "\n".join(f"- {n}" for n in notes) + "\n"
    (ROOT / "data" / "analyses" / f"{slug}.md").write_text(body, encoding="utf-8")
    return src


def write_visit(v):
    spec = v["doctor"].split()[0].lower()
    slug = f"{v['date']}-zaklyuchenie-{'kardiologa' if spec == 'кардиолог' else 'terapevta'}"
    src = f"samples/history/{slug}-foto.jpg"
    recs = "\n".join(f"{i}. {r}" for i, r in enumerate(v["recs"], 1))
    body = (f"---\ndate: {v['date']}\nclinic: {v['clinic']}\ntype: заключение врача\n"
            f"doctor: {v['doctor']}\nsource: {src}\n---\n\n# Заключение: {v['doctor']}, {v['date']}\n\n"
            f"**Жалобы:** {v['complaints']}\n\n**Объективно:** {v['findings']}\n\n"
            f"**Диагноз:** {v['diagnosis']}\n\n**Рекомендации:**\n\n{recs}\n")
    (ROOT / "data" / "analyses" / f"{slug}.md").write_text(body, encoding="utf-8")
    return src


def main():
    (ROOT / "data" / "analyses").mkdir(parents=True, exist_ok=True)
    for old in (ROOT / "data" / "analyses").glob("*.md"):
        old.unlink()
    series = {}
    for rec in [r for r in P.LABS if r["stage"] == "history"]:
        src = write_lab(rec)
        for code, v in rec["values"].items():
            series.setdefault(code, []).append({"date": rec["date"], "value": v, "flag": flag(code, v),
                                                "lab": LAB_NAME[rec["lab"]], "source": src})
    biomarkers = []
    for code in P.MARKERS:
        if code not in series:
            continue
        m = P.MARKERS[code]
        biomarkers.append({"key": code, "name": SHORT[code], "fullName": m["ru"], "group": GROUP[code],
                           "unit": m["si"], "ref": m["ref_si"], "low": m.get("lo"), "high": m.get("hi"),
                           "series": series[code]})
    visits = []
    for v in [v for v in P.VISITS if v["stage"] == "history"]:
        src = write_visit(v)
        visits.append({"date": v["date"], "doctor": v["doctor"], "clinic": v["clinic"],
                       "diagnosis": v["diagnosis"], "findings": v["findings"], "recs": v["recs"], "source": src})
    record = {
        "generated": "2026-09-01",
        "profile": {"name": P.PATIENT["name_ru"], "birth": P.PATIENT["birth"], "sex": "М",
                    "diagnoses": ["Гиперхолестеринемия (с 2023), без лекарств — питание и нагрузка"],
                    "meds": ["Витамин D3 — зимой, нерегулярно"],
                    "notes": ["Живёт в Варшаве с 2021; до этого анализы в русскоязычной лаборатории",
                              "Польская лаборатория печатает липиды и глюкозу в mg/dl — в карте пересчитано в ммоль/л"]},
        "tldr": [
            {"level": "warn", "text": "LDL снижается после пика 4.3 в 2023, но последний 3.2 всё ещё выше цели < 3.0."},
            {"level": "warn", "text": "Витамин D каждую зиму проваливается ниже 20 нг/мл, летом в норме."},
            {"level": "ok", "text": "Ферритин восстановлен: 18 в 2021, 70 в 2025."},
        ],
        "biomarkers": biomarkers,
        "visits": visits,
        "reminders": [
            {"id": "lipids-2026", "what": "Липидограмма", "why": "Контроль LDL раз в год по рекомендации кардиолога",
             "due": "2026-09-15", "status": "planned"},
            {"id": "vitd-winter", "what": "Витамин D (25-OH)", "why": "Зимой стабильно ниже нормы — проверить на фоне D3",
             "due": "2026-11-01", "status": "planned"},
            {"id": "tsh-2026", "what": "ТТГ", "why": "Последний раз в 2020, норма — повторять раз в несколько лет",
             "due": "2026-12-01", "status": "planned"},
        ],
    }
    (ROOT / "data" / "health-record.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("карта:", len(biomarkers), "маркеров,", sum(len(s) for s in series.values()), "точек,",
          len(visits), "заключений,", len(list((ROOT / "data" / "analyses").glob("*.md"))), "файлов записей")


if __name__ == "__main__":
    main()
