"""Картинки-графики показателей для Telegram: линия по датам, зелёная полоса нормы, цветные точки.

Нужна библиотека Pillow: на Ubuntu ставится системным пакетом `sudo apt install python3-pil`.
"""
import io
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_PATHS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"]
BOLD_PATHS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"]
COLOR = {"high": (214, 69, 69), "low": (224, 138, 30), "ok": (46, 158, 91)}
W, H = 1000, 520
PAD_L, PAD_R, PAD_T, PAD_B = 110, 50, 140, 75


def _font(paths, size):
    for p in paths:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _t(d):
    x = date.fromisoformat(d)
    return x.year + (x.timetuple().tm_yday - 1) / 365


def _panel(b):
    img = Image.new("RGB", (W, H), "white")
    g = ImageDraw.Draw(img)
    f, fb, fs = _font(FONT_PATHS, 32), _font(BOLD_PATHS, 44), _font(FONT_PATHS, 28)
    s = b["series"]
    last = s[-1]
    g.text((PAD_L, 22), b["name"], font=fb, fill=(20, 20, 20))
    status = {"high": "выше нормы", "low": "ниже нормы", "ok": "в норме"}[last["flag"]]
    g.text((PAD_L, 80), f"сейчас {last['value']:g} {b['unit']} — {status} · норма {b['ref']}",
           font=f, fill=COLOR[last["flag"]])
    xs, ys = [_t(p["date"]) for p in s], [p["value"] for p in s]
    lo, hi = b.get("low"), b.get("high")
    y_min = min(ys + [v for v in (lo, hi) if v is not None])
    y_max = max(ys + [v for v in (lo, hi) if v is not None])
    span = (y_max - y_min) or 1
    y_min, y_max = y_min - span * 0.15, y_max + span * 0.15
    x_min, x_max = (min(xs) - 0.3, max(xs) + 0.3) if len(xs) > 1 else (xs[0] - 1, xs[0] + 1)
    px = lambda x: PAD_L + (x - x_min) / (x_max - x_min) * (W - PAD_L - PAD_R)
    py = lambda y: H - PAD_B - (y - y_min) / (y_max - y_min) * (H - PAD_T - PAD_B)
    band_lo = lo if lo is not None else y_min
    band_hi = hi if hi is not None else y_max
    g.rectangle([PAD_L, py(band_hi), W - PAD_R, py(band_lo)], fill=(226, 244, 232))
    for i in range(5):  # сетка и подписи значений
        v = y_min + (y_max - y_min) * i / 4
        g.line([PAD_L, py(v), W - PAD_R, py(v)], fill=(235, 235, 235))
        g.text((10, py(v) - 16), f"{v:.1f}" if span < 20 else f"{v:.0f}", font=fs, fill=(130, 130, 130))
    for year in range(int(x_min) + 1, int(x_max) + 1):
        g.text((px(year) - 32, H - PAD_B + 18), str(year), font=fs, fill=(130, 130, 130))
    pts = [(px(x), py(y)) for x, y in zip(xs, ys)]
    if len(pts) > 1:
        g.line(pts, fill=(59, 110, 220), width=5)
    for (x, y), p in zip(pts, s):
        g.ellipse([x - 12, y - 12, x + 12, y + 12], fill=COLOR[p["flag"]], outline="white", width=2)
        g.text((x - 24, y - 50), f"{p['value']:g}", font=fs, fill=(60, 60, 60))
    return img


def render(biomarkers):
    """Один PNG со столбиком графиков по переданным показателям."""
    panels = [_panel(b) for b in biomarkers if b.get("series")]
    if not panels:
        return None
    img = Image.new("RGB", (W, H * len(panels)), "white")
    for i, p in enumerate(panels):
        img.paste(p, (0, i * H))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()
