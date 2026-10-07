#!/usr/bin/env python3
"""Сборка дашборда из data/health-record.json (только стандартная библиотека).

Запуск из любой папки:  python3 dashboard/build.py

Результат:
  dashboard/data.js               - данные для index.html (window.HEALTH_DATA = {...};),
                                    включая window.HEALTH_DATA.garmin, если есть data/garmin.json
  dashboard/health-dashboard.html - один самодостаточный файл: Chart.js и данные внутри,
                                    его можно отправить документом в Telegram и открыть офлайн.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RECORD = ROOT / "data" / "health-record.json"
GARMIN = ROOT / "data" / "garmin.json"  # необязательно: данные часов (dev/generate_garmin.py)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_record() -> dict:
    """Читает свод медкарты (+ данные часов, если есть) — только чтение, без записи."""
    record = json.loads(read(RECORD))
    if GARMIN.exists():
        record["garmin"] = json.loads(read(GARMIN))
    return record


def build_data_js(record: dict) -> str:
    # '</' экранируем, чтобы данные не могли закрыть тег <script> при вставке в html
    payload = json.dumps(record, ensure_ascii=False).replace("</", "<\\/")
    return f"window.HEALTH_DATA = {payload};\n"


def render_html() -> str:
    """Собирает самодостаточный HTML страницы в памяти (без записи файлов)."""
    record = load_record()
    data_js = build_data_js(record)

    html = read(HERE / "index.html")
    chart_js = read(HERE / "chart.umd.min.js").replace("</script", "<\\/script")
    html = html.replace('<script src="chart.umd.min.js"></script>', f"<script>{chart_js}</script>")
    html = html.replace('<script src="data.js"></script>', f"<script>{data_js}</script>")
    assert 'src="' not in html.split("<style>")[0], "остались внешние скрипты"
    return html


def main() -> None:
    record = load_record()

    data_js = build_data_js(record)
    (HERE / "data.js").write_text(data_js, encoding="utf-8")

    html = render_html()
    out = HERE / "health-dashboard.html"
    out.write_text(html, encoding="utf-8")

    print(
        f"Готово: {len(record['biomarkers'])} показателей, {len(record['visits'])} визитов, "
        f"{len(record['reminders'])} напоминаний, "
        f"{len(record['garmin']['days']) if 'garmin' in record else 0} дней часов -> {out.name} ({out.stat().st_size // 1024} КБ)"
    )


if __name__ == "__main__":
    main()
