#!/usr/bin/env python3
"""Генератор вымышленных данных часов (в стиле Garmin) для учебного пациента.

Запуск:  python3 dev/generate_garmin.py
Результат: data/garmin.json — 90 дней, заканчивая 2026-10-06, плюс личные нормы (p25–p75).
Только стандартная библиотека, результат детерминирован (фиксированный seed).

История в данных:
  - по будням сон короче, по выходным длиннее;
  - два раза в неделю — поздний отход ко сну: короче сон, утром ниже HRV и выше пульс покоя;
  - 5 дней простуды около 2026-09-10: пульс покоя +6, HRV -12, плохой сон, без тренировок;
  - в остальном — постепенный рост формы: пульс покоя за 90 дней снижается примерно на 2 уд/мин.
"""
import json
import random
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "garmin.json"

END = date(2026, 10, 6)
DAYS = 90
COLD = {date(2026, 9, 8) + timedelta(days=i) for i in range(5)}  # 8–12 сентября


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def percentile(values, q):
    s = sorted(values)
    pos = (len(s) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def main() -> None:
    rng = random.Random(20261006)
    start = END - timedelta(days=DAYS - 1)
    days = [start + timedelta(days=i) for i in range(DAYS)]

    # две «поздние ночи» в неделю (утро записи — вторник…воскресенье), без дней простуды
    late = set()
    week_start = start
    while week_start <= END:
        cand = [week_start + timedelta(days=i) for i in range(7)]
        cand = [d for d in cand if start <= d <= END and d.weekday() in (1, 2, 3, 4, 5, 6) and d not in COLD]
        late.update(rng.sample(cand, min(2, len(cand))))
        week_start += timedelta(days=7)

    records = []
    for i, d in enumerate(days):
        progress = i / (DAYS - 1)           # 0..1 — рост формы
        weekend = d.weekday() >= 5          # утро субботы/воскресенья
        is_late = d in late
        is_cold = d in COLD

        sleep = rng.gauss(7.5 if weekend else 6.8, 0.25)
        rhr = 60.3 - 2.2 * progress + rng.gauss(0, 0.9)
        hrv = 46 + 5 * progress + rng.gauss(0, 3.5)
        score_bonus = 0.0

        if is_late:
            sleep -= rng.uniform(0.7, 1.1)
            rhr += rng.uniform(2.0, 3.5)
            hrv -= rng.uniform(6, 10)
            score_bonus -= 8
        if is_cold:
            sleep -= rng.uniform(0.2, 0.6)
            rhr += 6
            hrv -= 12
            score_bonus -= 18
        # день после болезни — ещё не в форме
        if d - timedelta(days=1) in COLD and d not in COLD:
            rhr += 2
            hrv -= 5

        sleep = clamp(sleep, 5.4, 8.1)
        score = clamp(round(74 + (sleep - 6.8) * 14 + (hrv - 46) * 0.6 + score_bonus + rng.gauss(0, 3)), 22, 96)
        deep = round(sleep * 60 * clamp(rng.gauss(0.17, 0.02), 0.11, 0.22) * (0.8 if is_cold else 1))
        rem = round(sleep * 60 * clamp(rng.gauss(0.21, 0.025), 0.14, 0.27))
        rhr = clamp(rhr, 53, 70)
        hrv = clamp(hrv, 28, 64)
        battery = clamp(round(score * 0.85 - 8 + (hrv - 45) * 0.5 + rng.gauss(0, 4)), 12, 100)

        # тренировки: дни простуды — отдых; иначе ~4 раза в неделю
        if is_cold:
            train = 0
        elif d.weekday() in (0, 2, 4, 5) and rng.random() < 0.9 or (d.weekday() == 6 and rng.random() < 0.3):
            train = round(rng.gauss(48 + 8 * progress, 13) / 5) * 5
        else:
            train = 0
        steps = int(rng.gauss(7800 if not weekend else 8800, 1600)) + train * 55
        if is_cold:
            steps = int(steps * 0.45)
        steps = max(1800, round(steps / 10) * 10)

        records.append({
            "date": d.isoformat(),
            "sleepHours": round(sleep, 1),
            "sleepScore": int(score),
            "deepSleepMin": deep,
            "remSleepMin": rem,
            "restingHR": int(round(rhr)),
            "hrvMs": int(round(hrv)),
            "bodyBatteryMorning": int(battery),
            "steps": steps,
            "trainingMinutes": int(train),
        })

    metrics = ["sleepHours", "sleepScore", "deepSleepMin", "remSleepMin", "restingHR",
               "hrvMs", "bodyBatteryMorning", "steps", "trainingMinutes"]
    norms = {}
    for m in metrics:
        vals = [r[m] for r in records]
        norms[m] = {"p25": round(percentile(vals, 0.25), 1), "p75": round(percentile(vals, 0.75), 1)}

    out = {
        "device": "Часы (вымышленные данные)",
        "from": records[0]["date"],
        "to": records[-1]["date"],
        "norms": norms,
        "days": records,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Готово: {len(records)} дней -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
