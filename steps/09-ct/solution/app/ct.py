"""Кадры КТ/МРТ с диска клиники: ищет DICOM-файлы в папке, собирает объём, сохраняет 18 кадров.

  python3 run.py ct <папка с копией диска>

Нужны pydicom, numpy и Pillow (на сервере стоят системными пакетами python3-pydicom, python3-numpy, python3-pil).
Код работает и с pydicom 2.4, и с pydicom 3.
"""
import base64
import io
import json
import os
import re
import shutil
import warnings
from pathlib import Path

import config

try:
    import numpy as np
    import pydicom
    from PIL import Image
except ImportError as e:
    raise SystemExit(f"Не хватает библиотеки ({e.name}). Поставь: sudo apt install python3-pydicom python3-numpy python3-pil "
                     f"(или pip install pydicom numpy pillow)")

AXIAL_COUNT = 16          # осевых кадров на обследование
EDGE = 0.05               # отрезаем по 5% объёма сверху и снизу — там обычно пусто
JPEG_QUALITY = 85
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
MODALITY_RU = {"CT": "КТ", "MR": "МРТ", "CR": "Рентген", "DX": "Рентген", "US": "УЗИ", "PT": "ПЭТ"}


def is_dicom(path):
    """Признак DICOM — байты DICM со 128-го байта (расширение не смотрим: у среза его часто нет)."""
    try:
        with open(path, "rb") as f:
            f.seek(128)
            return f.read(4) == b"DICM"
    except OSError:
        return False


def read(path, headers_only=False):
    with warnings.catch_warnings():   # диски клиник нарушают формат полей, pydicom ворчит на каждый файл
        warnings.simplefilter("ignore")
        return pydicom.dcmread(str(path), stop_before_pixels=headers_only, force=True)


def find_dicom(folder):
    found = []
    for root, _dirs, files in os.walk(folder):
        for name in sorted(files):
            p = Path(root) / name
            if p.stat().st_size > 132 and is_dicom(p):
                found.append(p)
    return found


def _num(x, default=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _frames_count(ds):
    n = _num(ds.get("NumberOfFrames"), 1)
    return max(int(n), 1)


def _group_value(item, group, attr):
    seq = item.get(group)
    if seq and len(seq) and attr in seq[0]:
        return seq[0][attr].value
    return None


def _per_frame_info(ds, i):
    """Положение среза, ориентация и рескейл кадра i многокадрового файла: покадровые группы, затем общие, затем верх файла."""
    shared = ds.get("SharedFunctionalGroupsSequence")
    per = ds.get("PerFrameFunctionalGroupsSequence")
    items = []
    if per and i < len(per):
        items.append(per[i])
    if shared and len(shared):
        items.append(shared[0])

    def pick(group, attr):
        for it in items:
            v = _group_value(it, group, attr)
            if v is not None:
                return v
        return None

    pos = pick("PlanePositionSequence", "ImagePositionPatient")
    ori = pick("PlaneOrientationSequence", "ImageOrientationPatient")
    slope = pick("PixelValueTransformationSequence", "RescaleSlope")
    icpt = pick("PixelValueTransformationSequence", "RescaleIntercept")
    spacing = pick("PixelMeasuresSequence", "PixelSpacing")
    return (
        [float(v) for v in pos] if pos is not None else None,
        [float(v) for v in ori] if ori is not None else None,
        _num(slope, _num(ds.get("RescaleSlope"), 1.0)),
        _num(icpt, _num(ds.get("RescaleIntercept"), 0.0)),
        [float(v) for v in spacing] if spacing is not None else None,
    )


def _to_hu(arr, slope, icpt):
    """Рескейл в реальные единицы (HU для КТ). Целые значения храним в int16 — объём из сотен срезов не раздувается."""
    if slope == 1.0 and float(icpt).is_integer():
        out = arr.astype(np.int32) + int(icpt)
        return np.clip(out, -32768, 32767).astype(np.int16)
    return (arr.astype(np.float32) * slope + icpt).astype(np.float32)


def _slice_position(pos, ori):
    """Положение среза вдоль нормали к плоскости (не по номеру файла: номера бывают перепутаны)."""
    if pos is None:
        return None
    if ori and len(ori) == 6:
        r, c = np.array(ori[:3]), np.array(ori[3:])
        n = np.cross(r, c)
        return float(np.dot(n, pos))
    return pos[2]


def load_volume(files):
    """Один набор файлов (одна серия или один многокадровый файл) -> объём [срез, строка, столбец] + шаги по осям в мм."""
    slices = []   # (позиция вдоль нормали | None, InstanceNumber, порядок появления, 2D-массив в HU)
    spacing_xy = None
    mono1 = False
    shape_count = {}
    order = 0
    for f in files:
        ds = read(f)
        try:
            arr = ds.pixel_array
        except Exception as e:   # сжатый снимок без нужной библиотеки и т. п.
            raise RuntimeError(f"не удалось прочитать пиксели {Path(f).name}: {e}. "
                               f"Для сжатых снимков поставь: sudo apt install python3-gdcm (или pip install pylibjpeg pylibjpeg-libjpeg pylibjpeg-openjpeg)")
        mono1 = str(ds.get("PhotometricInterpretation", "")) == "MONOCHROME1"
        if arr.ndim == 2:
            arr = arr[None]
        if arr.ndim != 3:
            continue   # цветные кадры (RGB) сюда не берём
        n = arr.shape[0]
        multi = _frames_count(ds) > 1 or n > 1
        for i in range(n):
            if multi and ds.get("PerFrameFunctionalGroupsSequence"):
                pos, ori, slope, icpt, sp = _per_frame_info(ds, i)
            else:
                pos = [float(v) for v in ds.get("ImagePositionPatient")] if ds.get("ImagePositionPatient") is not None else None
                ori = [float(v) for v in ds.get("ImageOrientationPatient")] if ds.get("ImageOrientationPatient") is not None else None
                slope = _num(ds.get("RescaleSlope"), 1.0)
                icpt = _num(ds.get("RescaleIntercept"), 0.0)
                sp = [float(v) for v in ds.get("PixelSpacing")] if ds.get("PixelSpacing") is not None else None
            if sp and spacing_xy is None:
                spacing_xy = sp
            fr = _to_hu(arr[i], slope, icpt)
            shape_count[fr.shape] = shape_count.get(fr.shape, 0) + 1
            inst = _num(ds.get("InstanceNumber"), 0.0)
            slices.append((_slice_position(pos, ori), inst, order, fr))
            order += 1
    if not slices:
        raise RuntimeError("в файлах нет кадров")
    main_shape = max(shape_count, key=shape_count.get)   # посторонние кадры другого размера (например, обзорные) отбрасываем
    slices = [s for s in slices if s[3].shape == main_shape]
    if all(s[0] is not None for s in slices) and len({round(s[0], 3) for s in slices}) > 1:
        slices.sort(key=lambda s: (s[0], s[1], s[2]))     # по положению среза: от нижнего к верхнему
        positions = [s[0] for s in slices]
        dz = float(np.median(np.abs(np.diff(positions)))) if len(positions) > 1 else None
    else:
        slices.sort(key=lambda s: (s[1], s[2]))           # положения нет — по InstanceNumber, дальше по порядку в файле
        dz = None
    vol = np.stack([s[3] for s in slices])
    if mono1:   # MONOCHROME1: ноль = белый, переворачиваем, чтобы кости были светлыми
        vol = (float(vol.max()) + float(vol.min()) - vol.astype(np.float32)).astype(np.float32)
    dy = spacing_xy[0] if spacing_xy else 1.0
    dx = spacing_xy[1] if spacing_xy else dy
    return vol, (dz or dy, dy, dx)


def window(vol):
    """Окно яркости по процентилям объёма (1% и 99.5%).

    У снимков с диска вокруг круглого поля обзора бывает «заливка» — значение, которое повторяется в миллионах
    вокселей (здесь -2048). Если считать процентили вместе с ней, нижняя граница уезжает в неё, и кадр блёклый.
    Поэтому заливку (самое малое значение, если оно занимает больше 1% объёма) в расчёт не берём.
    """
    sample = vol.ravel()[::max(vol.size // 4_000_000, 1)]
    lo_val = sample.min()
    if (sample == lo_val).mean() > 0.01:
        sample = sample[sample > lo_val]
    lo, hi = np.percentile(sample, [1, 99.5])
    if hi <= lo:
        hi = lo + 1
    return float(lo), float(hi)


def to_image(slice2d, lo, hi, aspect=1.0):
    """Срез -> 8-битная картинка по окну; aspect — во сколько раз растянуть по высоте (для коронарного и сагиттального)."""
    a = np.clip((slice2d.astype(np.float32) - lo) / (hi - lo), 0, 1)
    img = Image.fromarray((a * 255).round().astype(np.uint8), "L")
    if abs(aspect - 1.0) > 0.01:
        img = img.resize((img.width, max(int(round(img.height * aspect)), 1)), Image.LANCZOS)
    return img


def jpeg_bytes(img):
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=JPEG_QUALITY)
    return buf.getvalue()


def make_frames(vol, steps):
    """16 осевых кадров равномерно по объёму + центральные коронарный и сагиттальный срезы."""
    lo, hi = window(vol)
    n, h, w = vol.shape
    a, b = int(round(n * EDGE)), int(round(n * (1 - EDGE))) - 1   # границы без пустых краёв
    a, b = (a, b) if b > a else (0, n - 1)
    count = min(AXIAL_COUNT, b - a + 1)
    idx = [int(round(a + (b - a) * k / (count - 1))) for k in range(count)] if count > 1 else [a]
    frames = []
    for k, i in enumerate(idx, 1):
        frames.append((f"osevoy-{k:02d}", f"Осевой срез {k} из {count}", to_image(vol[i], lo, hi)))
    dz, dy, dx = steps
    # верх кадра — верх тела: срезы отсортированы снизу вверх, поэтому по вертикали переворачиваем
    cor = vol[::-1, h // 2, :]
    sag = vol[::-1, :, w // 2]
    frames.append(("koronarny", "Коронарный срез", to_image(cor, lo, hi, dz / dx)))
    frames.append(("sagittalny", "Сагиттальный срез", to_image(sag, lo, hi, dz / dy)))
    return frames, (lo, hi)


def nice_date(d):
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", str(d or ""))
    if not m:
        return None, None
    y, mo, da = map(int, m.groups())
    if not 1 <= mo <= 12:
        return None, None
    return f"{y:04d}-{mo:02d}-{da:02d}", f"{da} {MONTHS[mo - 1]} {y}"


def _safe(s):
    return re.sub(r'[\\/:*?"<>|]+', " ", s).strip()


def run(folder):
    folder = Path(folder).expanduser()
    if not folder.is_dir():
        return print(f"Папки {folder} нет. Укажи папку с копией диска: python3 run.py ct <папка>")
    print(f"Ищу DICOM-файлы в {folder} …")
    files = find_dicom(folder)
    if not files:
        return print("DICOM-файлов (с байтами DICM со 128-го байта) в папке нет. Это точно копия диска со снимками?")

    # серии: группируем по SeriesInstanceUID, внутри обследования берём самую большую (без обзорных и вспомогательных)
    series = {}
    for f in files:
        try:
            ds = read(f, headers_only=True)
        except Exception:
            continue
        if "Rows" not in ds or "SOPClassUID" not in ds or str(ds.SOPClassUID).startswith("1.2.840.10008.1.3"):
            continue   # DICOMDIR и прочее без картинки
        if _num(ds.get("SamplesPerPixel"), 1) != 1:
            continue
        key = (str(ds.get("StudyInstanceUID", "")), str(ds.get("SeriesInstanceUID", f.parent)))
        s = series.setdefault(key, {"files": [], "frames": 0, "ds": ds})
        s["files"].append(f)
        s["frames"] += _frames_count(ds)
    if not series:
        return print("DICOM-файлы нашлись, но снимков (серий картинок) в них нет.")
    print(f"Нашёл DICOM-файлов: {len(files)}, серий со снимками: {len(series)}")

    by_study = {}
    for (study, _ser), s in series.items():
        by_study.setdefault(study, []).append(s)

    imaging_path = config.ROOT / "data" / "imaging.json"
    exams = json.loads(imaging_path.read_text(encoding="utf-8")) if imaging_path.exists() else []
    made = 0
    for study, group in by_study.items():
        group.sort(key=lambda s: -s["frames"])
        best = group[0]
        if best["frames"] < 3:
            print(f"  пропускаю обследование: в нём меньше 3 кадров")
            continue
        ds = best["ds"]
        modality = str(ds.get("Modality", "CT"))
        mod_ru = MODALITY_RU.get(modality, modality)
        date_iso, date_ru = nice_date(ds.get("StudyDate") or ds.get("SeriesDate") or ds.get("AcquisitionDate") or ds.get("ContentDate"))
        title = f"{mod_ru}, {date_ru}" if date_ru else mod_ru
        what = best["files"][0].name if len(best["files"]) == 1 else f"серия из {len(best['files'])} файлов"
        print(f"- {mod_ru} {date_ru or 'без даты'}: {what} ({best['frames']} кадров, {ds.Columns}x{ds.Rows})")
        if len(group) > 1:
            print(f"  другие серии этого обследования пропущены: {len(group) - 1} (беру самую большую)")
        try:
            vol, steps = load_volume(sorted(best["files"]))
        except RuntimeError as e:
            print(f"  ПРОПУСК: {e}")
            continue
        frames, (lo, hi) = make_frames(vol, steps)

        out_dir = config.ROOT / "medcard" / "обследования" / _safe(f"{date_iso or 'без даты'} {mod_ru}")
        if out_dir.exists():
            shutil.rmtree(out_dir)   # повторный запуск заменяет кадры, а не дублирует
        out_dir.mkdir(parents=True)
        rec_frames = []
        for name, label, img in frames:
            data = jpeg_bytes(img)
            (out_dir / f"{name}.jpg").write_bytes(data)
            rec_frames.append({"name": f"{name}.jpg", "label": label, "b64": base64.b64encode(data).decode("ascii")})
        exams = [e for e in exams if not (e.get("date") == date_iso and e.get("modality") == modality)]
        exams.append({"date": date_iso or "", "title": title, "modality": modality, "frames": rec_frames})
        made += 1
        print(f"  объём {vol.shape[2]}x{vol.shape[1]}x{vol.shape[0]}, окно яркости {lo:.0f}…{hi:.0f}")
        print(f"  сохранил {len(rec_frames)} кадров: {out_dir}")

    if not made:
        return print("Кадров не получилось. Проверь, что в папке есть снимки КТ/МРТ.")
    exams.sort(key=lambda e: e["date"], reverse=True)
    imaging_path.write_text(json.dumps(exams, ensure_ascii=False), encoding="utf-8")
    import medcard
    medcard.rebuild_page()
    print(f"Записал {imaging_path.relative_to(config.ROOT)}, страница пересобрана — открой раздел «Обследования».")
