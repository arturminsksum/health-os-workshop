#!/usr/bin/env python3
"""Стартовая медкарта вымышленного пациента: то, что «уже разобрано» до урока.

Берёт документы из dev/generated/ (их рисует generate_documents.py) и раскладывает так, чтобы
человек понял всё по именам файлов:
  medcard/<год>/<дата> анализ крови, <лаборатория> (<язык>).pdf  + рядом .md с разбором
  medcard/визиты к врачам/<дата> <врач>, <клиника> (фото).jpg     + рядом .md с разбором
  new-documents/                                                   — то, что приходит на уроке
  data/health-record.json                                          — машинный свод для страницы и бота

Запуск: python3 dev/build_records.py   (после python3 dev/generate_documents.py)
"""
import json
import shutil
import sys
from pathlib import Path

import patient as P

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
from markers import MARKERS, flag  # noqa: E402

GEN = ROOT / "dev" / "generated"
MEDCARD = ROOT / "medcard"
NEW = ROOT / "new-documents"
LAB = {"ru": ("Медлаб-Центр", "русский"), "pl": ("WISŁA", "польский, mg-dl"), "en": ("Northbridge", "английский")}
SLUG = {"ru": "medlab", "pl": "wisla", "en": "northbridge"}
FLAG_RU = {"high": "выше нормы", "low": "ниже нормы", "ok": ""}


def orig(code, v, lab):
    m = MARKERS[code]
    if lab == "pl" and "mgdl_k" in m:
        return f"{v:g} ({round(v * m['mgdl_k'])} mg/dl)"
    return f"{v:g}"


def table(rows):
    cols = ["Показатель", "Значение", "Единицы", "Норма", "Флаг"]
    w = [max(len(c), *(len(r[i]) for r in rows)) for i, c in enumerate(cols)]
    line = lambda r: "| " + " | ".join(x.ljust(w[i]) for i, x in enumerate(r)) + " |"
    return "\n".join([line(cols), "| " + " | ".join("-" * x for x in w) + " |", *map(line, rows)])


def lab_doc(rec):
    name, lang = LAB[rec["lab"]]
    folder = MEDCARD / rec["date"][:4]
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{rec['date']} анализ крови, {name} ({lang})"
    src = folder / f"{stem}.pdf"
    shutil.copy(GEN / "history" / f"{rec['date']}-{SLUG[rec['lab']]}.pdf", src)
    rows, notes = [], []
    for code, v in rec["values"].items():
        m, f = MARKERS[code], flag(code, v)
        rows.append([m["short"], orig(code, v, rec["lab"]), m["si"], m["ref_si"], FLAG_RU[f]])
        if f != "ok":
            notes.append(f"{m['short']} {FLAG_RU[f]}: {v:g} {m['si']} (норма {m['ref_si']}).")
    body = f"# {rec['date']} — анализ крови, {name}\n\nОригинал: {src.name}\n\n{table(rows)}\n"
    if notes:
        body += "\n## Что вне нормы\n\n" + "\n".join(f"- {n}" for n in notes) + "\n"
    (folder / f"{stem}.md").write_text(body, encoding="utf-8")
    return str(src.relative_to(ROOT))


def visit_doc(v):
    folder = MEDCARD / "визиты к врачам"
    folder.mkdir(parents=True, exist_ok=True)
    spec = v["doctor"].split()[0].lower()
    clinic = v["clinic"].replace("Медицинский центр ", "")
    stem = f"{v['date']} {spec}, {clinic} (фото заключения)"
    src = folder / f"{stem}.jpg"
    gen_name = f"{v['date']}-zaklyuchenie-{'kardiologa' if spec == 'кардиолог' else 'terapevta'}-foto.jpg"
    shutil.copy(GEN / "history" / gen_name, src)
    recs = "\n".join(f"{i}. {r}" for i, r in enumerate(v["recs"], 1))
    body = (f"# {v['date']} — {v['doctor']}, {v['clinic']}\n\nОригинал: {src.name}\n\n"
            f"**Жалобы:** {v['complaints']}\n\n**Осмотр:** {v['findings']}\n\n"
            f"**Диагноз:** {v['diagnosis']}\n\n**Рекомендации:**\n\n{recs}\n")
    (folder / f"{stem}.md").write_text(body, encoding="utf-8")
    return str(src.relative_to(ROOT))


def copy_new_documents():
    NEW.mkdir(exist_ok=True)
    names = {
        "2026-08-18-northbridge.pdf": "2026-08-18 анализ крови, Northbridge (английский).pdf",
        "2026-09-24-wisla-app-screen-1.png": "2026-09-24 скриншот приложения WISŁA, экран 1.png",
        "2026-09-24-wisla-app-screen-2.png": "2026-09-24 скриншот приложения WISŁA, экран 2.png",
        "2026-09-29-zaklyuchenie-terapevta-foto.jpg": "2026-09-29 фото заключения терапевта.jpg",
    }
    for src, dst in names.items():
        shutil.copy(GEN / "new" / src, NEW / dst)


def main():
    for d in (MEDCARD, NEW):
        if d.exists():
            shutil.rmtree(d)
    series = {}
    for rec in [r for r in P.LABS if r["stage"] == "history"]:
        src = lab_doc(rec)
        for code, v in rec["values"].items():
            series.setdefault(code, []).append({"date": rec["date"], "value": v, "flag": flag(code, v),
                                                "lab": LAB[rec["lab"]][0], "source": src})
    biomarkers = [{"key": k, "name": m["short"], "fullName": m["ru"], "group": m["group"], "unit": m["si"],
                   "ref": m["ref_si"], "low": m.get("lo"), "high": m.get("hi"), "series": series[k]}
                  for k, m in MARKERS.items() if k in series]
    visits = [dict(date=v["date"], doctor=v["doctor"], clinic=v["clinic"], diagnosis=v["diagnosis"],
                   findings=v["findings"], recs=v["recs"], source=visit_doc(v))
              for v in P.VISITS if v["stage"] == "history"]
    copy_new_documents()
    record = {
        "generated": "2026-09-01",
        "profile": {"name": P.PATIENT["name_ru"], "birth": P.PATIENT["birth"], "sex": "М",
                    "diagnoses": ["Повышенный холестерин (с 2023), без лекарств — питание и нагрузка"],
                    "meds": ["Витамин D3 — зимой, нерегулярно"],
                    "notes": ["Живёт в Варшаве с 2021; до этого анализы в русскоязычной лаборатории",
                              "Польская лаборатория печатает липиды и глюкозу в mg/dl — в карте пересчитано в ммоль/л"]},
        "tldr": [
            {"level": "warn", "text": "LDL снижается после пика 4.3 в 2023, но последний 3.2 всё ещё выше нормы < 3.0.", "markers": ["ldl", "tc"]},
            {"level": "warn", "text": "Витамин D каждую зиму падает ниже 20 нг/мл, летом в норме.", "markers": ["vitd"]},
            {"level": "ok", "text": "Ферритин восстановлен: 18 в 2021, 70 в 2025.", "markers": ["fer"]},
        ],
        "biomarkers": biomarkers,
        "visits": visits,
        "events": [{"added": "2026-09-01T10:00:00", "kind": "import", "date": "2026-09-01",
                    "title": "Загружена медкарта", "markers": [], "source": "medcard/",
                    "lines": [f"{sum(len(s) for s in series.values())} значений из 7 анализов за 2020–2025",
                              "Заключение кардиолога от 2023-03-20",
                              "Данные часов за 90 дней"]}],
        "reminders": [
            {"id": "lipids-2026", "what": "Липидограмма", "why": "Контроль LDL раз в год по рекомендации кардиолога",
             "due": "2026-09-15", "status": "planned", "markers": ["ldl", "tc", "hdl", "tg"]},
            {"id": "vitd-winter", "what": "Витамин D (25-OH)", "why": "Зимой стабильно ниже нормы — проверить на фоне D3",
             "due": "2026-11-01", "status": "planned", "markers": ["vitd"]},
            {"id": "tsh-2026", "what": "ТТГ", "why": "Последний раз в 2020, норма — повторять раз в несколько лет",
             "due": "2026-12-01", "status": "planned", "markers": ["tsh"]},
        ],
    }
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data" / "health-record.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("медкарта:", len(biomarkers), "показателей,", sum(len(s) for s in series.values()), "точек,",
          len(visits), "визитов; новых документов:", len(list(NEW.iterdir())))


if __name__ == "__main__":
    main()
