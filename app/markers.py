"""Справочник показателей: как называется на разных языках, в чём мерить, какая норма.

По нему код сопоставляет «Cholesterol LDL», «ЛПНП» и «LDL cholesterol» с одним показателем,
пересчитывает mg/dl в ммоль/л и ставит флаг «выше/ниже нормы». Нового показателя нет в списке —
модель вернёт его как есть, и он попадёт в медкарту со своими единицами.
"""

MARKERS = {
    "tc":   {"short": "Холестерин", "ru": "Холестерин общий", "pl": "Cholesterol całkowity",
             "en": "Total cholesterol", "group": "Липиды", "si": "ммоль/л", "ref_si": "< 5.2",
             "mgdl_k": 38.67, "ref_mgdl": "< 200", "hi": 5.2},
    "ldl":  {"short": "LDL", "ru": "Холестерин ЛПНП", "pl": "Cholesterol LDL", "en": "LDL cholesterol",
             "group": "Липиды", "si": "ммоль/л", "ref_si": "< 3.0", "mgdl_k": 38.67, "ref_mgdl": "< 115",
             "hi": 3.0},
    "hdl":  {"short": "HDL", "ru": "Холестерин ЛПВП", "pl": "Cholesterol HDL", "en": "HDL cholesterol",
             "group": "Липиды", "si": "ммоль/л", "ref_si": "> 1.0", "mgdl_k": 38.67, "ref_mgdl": "> 40",
             "lo": 1.0},
    "tg":   {"short": "Триглицериды", "ru": "Триглицериды", "pl": "Triglicerydy", "en": "Triglycerides",
             "group": "Липиды", "si": "ммоль/л", "ref_si": "< 1.7", "mgdl_k": 88.57, "ref_mgdl": "< 150",
             "hi": 1.7},
    "glu":  {"short": "Глюкоза", "ru": "Глюкоза", "pl": "Glukoza", "en": "Glucose", "group": "Обмен веществ",
             "si": "ммоль/л", "ref_si": "3.9–5.6", "mgdl_k": 18.0, "ref_mgdl": "70–99", "lo": 3.9, "hi": 5.6},
    "alt":  {"short": "ALT", "ru": "АЛТ", "pl": "ALT", "en": "ALT", "group": "Печень",
             "si": "Ед/л", "si_pl": "U/l", "ref_si": "< 41", "hi": 41},
    "ast":  {"short": "AST", "ru": "АСТ", "pl": "AST", "en": "AST", "group": "Печень",
             "si": "Ед/л", "si_pl": "U/l", "ref_si": "< 40", "hi": 40},
    "fer":  {"short": "Ферритин", "ru": "Ферритин", "pl": "Ferrytyna", "en": "Ferritin",
             "group": "Железо и витамины", "si": "нг/мл", "si_pl": "ng/ml", "ref_si": "30–400",
             "lo": 30, "hi": 400},
    "vitd": {"short": "Витамин D", "ru": "Витамин D (25-OH)", "pl": "Witamina D3 (25-OH)",
             "en": "Vitamin D (25-OH)", "group": "Железо и витамины", "si": "нг/мл", "si_pl": "ng/ml",
             "ref_si": "30–100", "lo": 30, "hi": 100},
    "tsh":  {"short": "ТТГ", "ru": "ТТГ", "pl": "TSH", "en": "TSH", "group": "Щитовидная железа",
             "si": "мкМЕ/мл", "si_pl": "µIU/ml", "si_en": "mIU/L", "ref_si": "0.4–4.0", "lo": 0.4, "hi": 4.0},
    "ft4":  {"short": "Т4 св.", "ru": "Т4 свободный", "pl": "FT4", "en": "Free T4",
             "group": "Щитовидная железа", "si": "пмоль/л", "si_en": "pmol/L", "ref_si": "12–22",
             "lo": 12, "hi": 22},
    "hb":   {"short": "Гемоглобин", "ru": "Гемоглобин", "pl": "Hemoglobina", "en": "Haemoglobin",
             "group": "Кровь", "si": "г/л", "si_pl": "g/l", "si_en": "g/L", "ref_si": "130–170",
             "lo": 130, "hi": 170},
}


def flag(key, value):
    m = MARKERS.get(key, {})
    if "hi" in m and value > m["hi"]:
        return "high"
    if "lo" in m and value < m["lo"]:
        return "low"
    return "ok"


def to_si(key, value, unit):
    """Значение в единицах медкарты. mg/dl пересчитываем по коэффициенту справочника."""
    m = MARKERS.get(key)
    if m and "mgdl_k" in m and unit.replace(" ", "").lower() in ("mg/dl", "мг/дл"):
        return round(value / m["mgdl_k"], 2)
    if m and key == "hb" and unit.replace(" ", "").lower() in ("g/dl", "г/дл"):
        return round(value * 10)
    return value


def catalog_text():
    """Список для модели: ключ и названия на трёх языках."""
    return "\n".join(f"{k}: {m['ru']} / {m['pl']} / {m['en']} (единицы медкарты: {m['si']})"
                     for k, m in MARKERS.items())
