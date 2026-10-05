#!/usr/bin/env python3
"""Генератор документов вымышленного пациента: PDF лабораторий, скрины приложения, фото заключения.

Источник правды — patient.py. Рендер — headless Chrome (HTML в PDF/PNG), «фото» — Pillow.
Выход: samples/history/ (уже разобранная история) и samples/new/ (то, что прилетает на уроке).

Запуск: python3 dev/generate_documents.py
"""
import html
import random
import shutil
import subprocess
import tempfile
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

import patient as P

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "dev" / "generated"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
TMP = Path(tempfile.mkdtemp(prefix="howk-"))


def esc(s):
    return html.escape(str(s))


def d_ru(iso):
    y, m, d = iso.split("-")
    return f"{d}.{m}.{y}"


def age_at(iso):
    b = date.fromisoformat(P.PATIENT["birth"])
    t = date.fromisoformat(iso)
    return t.year - b.year - ((t.month, t.day) < (b.month, b.day))


def flag(code, v_si):
    m = P.MARKERS[code]
    if "hi" in m and v_si > m["hi"]:
        return "H"
    if "lo" in m and v_si < m["lo"]:
        return "L"
    return ""


def fmt(v):
    return f"{v:g}" if isinstance(v, int) or float(v).is_integer() else f"{v:.2f}".rstrip("0").rstrip(".")


def pl_value(code, v_si):
    """Польская лаба печатает липиды и глюкозу в mg/dl, остальное как есть."""
    m = P.MARKERS[code]
    if "mgdl_k" in m:
        return str(round(v_si * m["mgdl_k"])), "mg/dl", m["ref_mgdl"]
    return fmt(v_si), m.get("si_pl", m["si"]), m["ref_si"]


def chrome(args):
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-sandbox", *args],
                   check=True, capture_output=True, timeout=120)


def to_pdf(html_text, out):
    src = TMP / (out.stem + ".html")
    src.write_text(html_text, encoding="utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    chrome(["--no-pdf-header-footer", f"--print-to-pdf={out}", src.as_uri()])


def to_png(html_text, out, w, h, scale=2):
    src = TMP / (out.stem + ".html")
    src.write_text(html_text, encoding="utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    chrome([f"--window-size={w},{h}", f"--force-device-scale-factor={scale}", "--hide-scrollbars",
            f"--screenshot={out}", src.as_uri()])


BASE_CSS = """
@page { size: A4; margin: 16mm 14mm; }
body { font-family: Arial, Helvetica, sans-serif; font-size: 10.5pt; color: #111; }
table { width: 100%; border-collapse: collapse; margin-top: 10px; }
th, td { padding: 5px 6px; border-bottom: 1px solid #ccc; text-align: left; }
th { background: #eee; font-size: 9pt; }
.H, .L { font-weight: bold; }
.small { font-size: 8.5pt; color: #444; }
"""


# ---------- русскоязычная лаборатория ----------
def lab_ru(rec):
    rows = ""
    for code, v in rec["values"].items():
        m = P.MARKERS[code]
        f = flag(code, v)
        arrow = {"H": "↑", "L": "↓"}.get(f, "")
        rows += (f"<tr><td>{esc(m['ru'])}</td><td class='{f}'>{fmt(v)} {arrow}</td>"
                 f"<td>{esc(m['si'])}</td><td>{esc(m['ref_si'])}</td></tr>")
    pt = P.PATIENT
    return f"""<html><head><meta charset="utf-8"><style>{BASE_CSS}
    .hdr {{ border-bottom: 3px solid #1b6b3a; padding-bottom: 8px; display:flex; justify-content:space-between; }}
    .logo {{ font-size: 16pt; font-weight: bold; color: #1b6b3a; }}
    </style></head><body>
    <div class="hdr"><div><div class="logo">МЕДЛАБ-ЦЕНТР</div>
      <div class="small">{esc(P.LAB_RU['name'])}<br>{esc(P.LAB_RU['addr'])} · {esc(P.LAB_RU['phone'])}</div></div>
      <div class="small" style="text-align:right">Заказ № {esc(rec['order'])}<br>Дата взятия: {d_ru(rec['date'])}<br>
      Дата выдачи: {d_ru(rec['date'])}</div></div>
    <h3>Результаты лабораторных исследований</h3>
    <div>Пациент: <b>{esc(pt['name_ru'])}</b> · Пол: {pt['sex']} · Дата рождения: {d_ru(pt['birth'])}
      ({age_at(rec['date'])} лет) · Карта: {esc(pt['id_ru'])}</div>
    <div class="small">Биоматериал: кровь венозная, натощак</div>
    <table><tr><th>Исследование</th><th>Результат</th><th>Единицы</th><th>Референсные значения</th></tr>
    {rows}</table>
    <p class="small">↑ — выше референса, ↓ — ниже референса. Результаты не являются диагнозом и требуют
    интерпретации врачом.</p>
    <p class="small" style="margin-top:30px">Врач клинической лабораторной диагностики: Петрова Н. И. ______</p>
    </body></html>"""


# ---------- польская лаборатория (PDF) ----------
def lab_pl(rec):
    rows = ""
    for code, v in rec["values"].items():
        m = P.MARKERS[code]
        val, unit, ref = pl_value(code, v)
        f = flag(code, v)
        rows += (f"<tr><td>{esc(m['pl'])}</td><td class='{f}'>{val}</td><td>{f}</td>"
                 f"<td>{esc(unit)}</td><td>{esc(ref)}</td></tr>")
    pt = P.PATIENT
    return f"""<html><head><meta charset="utf-8"><style>{BASE_CSS}
    .hdr {{ background:#0d3b66; color:#fff; padding:10px 12px; display:flex; justify-content:space-between; }}
    .logo {{ font-size: 15pt; font-weight: bold; letter-spacing: 1px; }}
    .box {{ border:1px solid #bbb; padding:8px; margin-top:10px; display:grid; grid-template-columns:1fr 1fr; gap:4px; }}
    </style></head><body>
    <div class="hdr"><div><div class="logo">WISŁA</div><div style="font-size:8.5pt">{esc(P.LAB_PL['name'])}</div></div>
      <div style="font-size:8.5pt;text-align:right">{esc(P.LAB_PL['addr'])}<br>tel. {esc(P.LAB_PL['phone'])}</div></div>
    <h3>SPRAWOZDANIE Z BADAŃ LABORATORYJNYCH</h3>
    <div class="box"><div>Pacjent: <b>{esc(pt['name_pl'])}</b></div><div>PESEL: {pt['pesel']}</div>
      <div>Data urodzenia: {d_ru(pt['birth'])}</div><div>Płeć: M</div>
      <div>Nr zlecenia: {esc(rec['order'])}</div><div>Data pobrania: {d_ru(rec['date'])} 07:42</div></div>
    <table><tr><th>Badanie</th><th>Wynik</th><th>Flaga</th><th>Jednostka</th><th>Zakres referencyjny</th></tr>
    {rows}</table>
    <p class="small">H — wynik powyżej zakresu, L — wynik poniżej zakresu. Materiał: krew żylna (surowica).</p>
    <p class="small" style="margin-top:30px">Autoryzował: mgr Anna Kowalska, diagnosta laboratoryjny</p>
    </body></html>"""


# ---------- англоязычная лаборатория ----------
def lab_en(rec):
    rows = ""
    for code, v in rec["values"].items():
        m = P.MARKERS[code]
        f = flag(code, v)
        rows += (f"<tr><td>{esc(m['en'])}</td><td class='{f}'>{fmt(v)}</td><td>{f or 'Normal'}</td>"
                 f"<td>{esc(m.get('si_en', m.get('si_pl', m['si'])))}</td><td>{esc(m['ref_si'])}</td></tr>")
    pt = P.PATIENT
    return f"""<html><head><meta charset="utf-8"><style>{BASE_CSS}
    body {{ font-family: Georgia, serif; }}
    .hdr {{ border-bottom: 2px solid #7a1f3d; padding-bottom: 8px; }}
    .logo {{ font-size: 17pt; color: #7a1f3d; }}
    </style></head><body>
    <div class="hdr"><div class="logo">Northbridge</div>
      <div class="small">{esc(P.LAB_EN['name'])} · {esc(P.LAB_EN['addr'])} · {esc(P.LAB_EN['phone'])}</div></div>
    <h3>Laboratory Report</h3>
    <div>Patient: <b>{esc(pt['name_en'])}</b> · DOB: {date.fromisoformat(pt['birth']).strftime('%d %b %Y')}
      · Sex: Male<br>Accession: {esc(rec['order'])} · Collected: {date.fromisoformat(rec['date']).strftime('%d %b %Y')}</div>
    <table><tr><th>Test</th><th>Result</th><th>Flag</th><th>Units</th><th>Reference range</th></tr>
    {rows}</table>
    <p class="small">Reported by: Dr J. Ellison, Consultant Clinical Biochemist.</p>
    </body></html>"""


# ---------- скрины мобильного приложения польской лабы ----------
def app_screen(rec, codes, title):
    pt = P.PATIENT
    cards = ""
    for code in codes:
        v = rec["values"][code]
        m = P.MARKERS[code]
        val, unit, ref = pl_value(code, v)
        f = flag(code, v)
        color = {"H": "#d64545", "L": "#e08a1e"}.get(f, "#2e9e5b")
        badge = {"H": "Powyżej normy", "L": "Poniżej normy"}.get(f, "W normie")
        cards += f"""<div class="card"><div class="row"><div class="nm">{esc(m['pl'])}</div>
          <div class="badge" style="background:{color}22;color:{color}">{badge}</div></div>
          <div class="val">{val} <span>{esc(unit)}</span></div>
          <div class="ref">Norma: {esc(ref)} {esc(unit)}</div>
          <div class="bar"><div style="width:{60 if not f else (88 if f=='H' else 18)}%;background:{color}"></div></div></div>"""
    return f"""<html><head><meta charset="utf-8"><style>
    body {{ margin:0; font-family: -apple-system, 'SF Pro Text', Helvetica, sans-serif; background:#f2f4f7; width:390px; }}
    .sb {{ height:44px; display:flex; justify-content:space-between; align-items:center; padding:0 22px;
          font-weight:600; font-size:15px; background:#0d3b66; color:#fff; }}
    .top {{ background:#0d3b66; color:#fff; padding:6px 18px 18px; }}
    .top .t {{ font-size:22px; font-weight:700; }} .top .s {{ font-size:13px; opacity:.8; margin-top:4px; }}
    .card {{ background:#fff; margin:12px 14px; border-radius:14px; padding:14px 16px; box-shadow:0 1px 3px #0001; }}
    .row {{ display:flex; justify-content:space-between; align-items:center; }}
    .nm {{ font-size:15px; font-weight:600; }} .badge {{ font-size:11px; padding:3px 8px; border-radius:10px; font-weight:600; }}
    .val {{ font-size:26px; font-weight:700; margin-top:6px; }} .val span {{ font-size:14px; color:#666; font-weight:500; }}
    .ref {{ font-size:12px; color:#777; margin-top:2px; }}
    .bar {{ height:6px; background:#e6e9ee; border-radius:3px; margin-top:10px; }} .bar div {{ height:6px; border-radius:3px; }}
    .tab {{ position:fixed; bottom:0; width:390px; height:70px; background:#fff; border-top:1px solid #ddd;
           display:flex; justify-content:space-around; align-items:center; font-size:11px; color:#888; }}
    .tab b {{ color:#0d3b66; }}
    </style></head><body>
    <div class="sb"><span>9:41</span><span>●●●● 5G ▮</span></div>
    <div class="top"><div class="s">‹ Wyniki</div><div class="t">{esc(title)}</div>
      <div class="s">{esc(pt['name_pl'])} · pobranie {d_ru(rec['date'])} · zlec. {esc(rec['order'])}</div></div>
    {cards}
    <div class="tab"><b>Wyniki</b><span>Wizyty</span><span>Sklep</span><span>Profil</span></div>
    </body></html>"""


# ---------- бумажное заключение врача ----------
def visit_html(v):
    pt = P.PATIENT
    recs = "".join(f"<li>{esc(r)}</li>" for r in v["recs"])
    return f"""<html><head><meta charset="utf-8"><style>
    body {{ margin:0; width:820px; background:#fdfcf7; font-family: 'Times New Roman', serif; font-size:17px; color:#1a1a1a; }}
    .pg {{ padding:50px 60px; position:relative; }}
    .clinic {{ text-align:center; font-weight:bold; font-size:19px; }} .sub {{ text-align:center; font-size:13px; }}
    h2 {{ text-align:center; font-size:20px; margin:26px 0 18px; letter-spacing:1px; }}
    p {{ margin:7px 0; line-height:1.4; }} b {{ font-weight:bold; }}
    .stamp {{ position:absolute; right:90px; bottom:60px; width:150px; height:150px; border:3px solid #3550a8;
             border-radius:50%; color:#3550a8; font-size:12px; display:flex; align-items:center; justify-content:center;
             text-align:center; transform:rotate(-14deg); opacity:.75; font-family:Arial; }}
    .sig {{ font-family:'Snell Roundhand','Apple Chancery',cursive; font-size:30px; color:#1d2f7a; margin-left:20px; }}
    </style></head><body><div class="pg">
    <div class="clinic">{esc(v['clinic'])}</div>
    <div class="sub">ул. Примерная, 22 · тел. +000 00 000-00-00 · лицензия № 00000</div>
    <h2>КОНСУЛЬТАТИВНОЕ ЗАКЛЮЧЕНИЕ</h2>
    <p>Дата приёма: <b>{d_ru(v['date'])}</b></p>
    <p>Пациент: <b>{esc(pt['name_ru'])}</b>, {d_ru(pt['birth'])} г. р. ({age_at(v['date'])} лет)</p>
    <p>Врач: {esc(v['doctor'])}</p>
    <p><b>Жалобы:</b> {esc(v['complaints'])}</p>
    <p><b>Объективно:</b> {esc(v['findings'])}</p>
    <p><b>Диагноз:</b> {esc(v['diagnosis'])}</p>
    <p><b>Рекомендации:</b></p><ol>{recs}</ol>
    <p style="margin-top:40px">Врач: ____________ <span class="sig">{esc(v['doctor'].split()[1])}</span></p>
    <div class="stamp">{esc(v['clinic'])}<br>ДЛЯ<br>ДОКУМЕНТОВ</div>
    </div></body></html>"""


def photo_effect(src_png, out_jpg, seed=7):
    """Плоский рендер в «фото с телефона»: лист на столе, перспектива, тень, неровный свет, шум."""
    rnd = random.Random(seed)
    doc = Image.open(src_png).convert("RGB")
    W, H = doc.size
    canvas_w, canvas_h = int(W * 1.25), int(H * 1.18)
    # стол: тёплый тёмный фон с лёгкой фактурой
    bg = Image.new("RGB", (canvas_w, canvas_h), (92, 70, 52))
    px = bg.load()
    for y in range(0, canvas_h, 2):
        tone = int(10 * ((y / 37) % 1))
        for x in range(0, canvas_w, 3):
            r, g, b = px[x, y]
            px[x, y] = (r + tone, g + tone // 2, b)
    bg = bg.filter(ImageFilter.GaussianBlur(3))
    # перспектива: углы листа сдвинуты, как при съёмке под углом
    ox, oy = (canvas_w - W) // 2, (canvas_h - H) // 2
    quad = [(ox + rnd.randint(30, 60), oy + rnd.randint(10, 30)),
            (ox + W - rnd.randint(0, 20), oy + rnd.randint(40, 70)),
            (ox + W + rnd.randint(10, 30), oy + H - rnd.randint(0, 20)),
            (ox - rnd.randint(0, 20), oy + H - rnd.randint(30, 50))]
    coeffs = _perspective_coeffs(quad, [(0, 0), (W, 0), (W, H), (0, H)])
    warped = doc.transform((canvas_w, canvas_h), Image.PERSPECTIVE, coeffs, Image.BICUBIC)
    mask = Image.new("L", (W, H), 255).transform((canvas_w, canvas_h), Image.PERSPECTIVE, coeffs, Image.BICUBIC)
    shadow = mask.filter(ImageFilter.GaussianBlur(18))
    bg.paste((30, 22, 15), (14, 18), shadow)
    bg.paste(warped, (0, 0), mask)
    # неровный свет: затемнение по диагонали
    light = Image.new("L", (canvas_w, canvas_h))
    ld = ImageDraw.Draw(light)
    for i in range(canvas_h):
        ld.line([(0, i), (canvas_w, i)], fill=int(70 * i / canvas_h))
    bg = Image.composite(Image.new("RGB", bg.size, (0, 0, 0)), bg, light.point(lambda v: v // 2))
    # шум и лёгкая нерезкость
    noise = Image.effect_noise(bg.size, 18).convert("RGB")
    bg = Image.blend(bg, noise, 0.04).filter(ImageFilter.GaussianBlur(0.8))
    bg = bg.resize((canvas_w * 3 // 4, canvas_h * 3 // 4), Image.LANCZOS)
    out_jpg.parent.mkdir(parents=True, exist_ok=True)
    bg.save(out_jpg, "JPEG", quality=78)


def _perspective_coeffs(dst, src):
    import numpy as np
    A, B = [], []
    for (x, y), (u, v) in zip(dst, src):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); B.append(u)
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y]); B.append(v)
    return np.linalg.solve(np.array(A, float), np.array(B, float)).tolist()


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    made = []
    for rec in P.LABS:
        stage_dir = OUT / ("history" if rec["stage"] == "history" else "new")
        if rec.get("format") == "app-screens":
            to_png(app_screen(rec, ["ldl", "tc", "hdl", "tg"], "Lipidogram"),
                   stage_dir / f"{rec['date']}-wisla-app-screen-1.png", 390, 844, 3)
            to_png(app_screen(rec, ["glu", "fer", "vitd"], "Glukoza, ferrytyna, wit. D"),
                   stage_dir / f"{rec['date']}-wisla-app-screen-2.png", 390, 844, 3)
            made += ["screen-1", "screen-2"]
            continue
        builder, slug = {"ru": (lab_ru, "medlab"), "pl": (lab_pl, "wisla"), "en": (lab_en, "northbridge")}[rec["lab"]]
        out = stage_dir / f"{rec['date']}-{slug}.pdf"
        to_pdf(builder(rec), out)
        made.append(out.name)
    for v in P.VISITS:
        stage_dir = OUT / ("history" if v["stage"] == "history" else "new")
        png = TMP / f"visit-{v['date']}.png"
        to_png(visit_html(v), png, 820, 1160, 2)
        if v["stage"] == "live":
            photo_effect(png, stage_dir / f"{v['date']}-zaklyuchenie-terapevta-foto.jpg")
        else:
            photo_effect(png, stage_dir / f"{v['date']}-zaklyuchenie-kardiologa-foto.jpg", seed=3)
        made.append(f"visit {v['date']}")
    print("готово:", len(made), "документов →", OUT)


if __name__ == "__main__":
    main()
