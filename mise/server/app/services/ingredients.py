"""Ingredient parsing, scaling and metric/imperial conversion.

Pure Python, no third-party dependencies, so it is easy to unit-test.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Optional

# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------

# canonical unit -> (family, factor to base). Base: ml for volume, g for weight.
UNITS: dict[str, tuple[str, float]] = {
    "tsp": ("volume", 4.92892),
    "tbsp": ("volume", 14.7868),
    "cup": ("volume", 236.588),
    "fl oz": ("volume", 29.5735),
    "pint": ("volume", 473.176),
    "quart": ("volume", 946.353),
    "gallon": ("volume", 3785.41),
    "ml": ("volume", 1.0),
    "cl": ("volume", 10.0),
    "dl": ("volume", 100.0),
    "l": ("volume", 1000.0),
    "g": ("weight", 1.0),
    "mg": ("weight", 0.001),
    "kg": ("weight", 1000.0),
    "oz": ("weight", 28.3495),
    "lb": ("weight", 453.592),
    "stick": ("weight", 113.0),  # stick of butter
}

COUNT_UNITS = {
    "pinch", "dash", "clove", "can", "jar", "package", "packet", "slice", "piece",
    "bunch", "sprig", "handful", "head", "sheet", "bag", "box", "bottle", "stalk",
    "fillet", "leaf", "drop", "scoop", "container", "envelope",
}

# alias -> canonical. Matched case-insensitively except "T"/"t" handled separately.
_ALIASES = {
    "teaspoon": "tsp", "teaspoons": "tsp", "tsp": "tsp", "tsps": "tsp", "tsp.": "tsp", "tspn": "tsp",
    "tablespoon": "tbsp", "tablespoons": "tbsp", "tbsp": "tbsp", "tbsps": "tbsp", "tbsp.": "tbsp",
    "tbs": "tbsp", "tbl": "tbsp", "tbls": "tbsp", "tblsp": "tbsp",
    "cup": "cup", "cups": "cup", "c.": "cup",
    "fl oz": "fl oz", "fl. oz.": "fl oz", "fl. oz": "fl oz", "fluid ounce": "fl oz", "fluid ounces": "fl oz",
    "pint": "pint", "pints": "pint", "pt": "pint",
    "quart": "quart", "quarts": "quart", "qt": "quart", "qts": "quart",
    "gallon": "gallon", "gallons": "gallon", "gal": "gallon",
    "ml": "ml", "milliliter": "ml", "milliliters": "ml", "millilitre": "ml", "millilitres": "ml",
    "cl": "cl", "dl": "dl",
    "l": "l", "liter": "l", "liters": "l", "litre": "l", "litres": "l", "ltr": "l",
    "g": "g", "gr": "g", "gram": "g", "grams": "g", "gramme": "g", "grammes": "g", "g.": "g",
    "mg": "mg", "kg": "kg", "kilogram": "kg", "kilograms": "kg", "kgs": "kg",
    "oz": "oz", "oz.": "oz", "ounce": "oz", "ounces": "oz",
    "lb": "lb", "lbs": "lb", "lb.": "lb", "lbs.": "lb", "pound": "lb", "pounds": "lb",
    "stick": "stick", "sticks": "stick",
}
for _u in COUNT_UNITS:
    _ALIASES.setdefault(_u, _u)
    _ALIASES.setdefault(_u + "s", _u)
    _ALIASES.setdefault(_u + "es", _u)
_ALIASES["leaves"] = "leaf"
_ALIASES["pinches"] = "pinch"
_ALIASES["dashes"] = "dash"
_ALIASES["boxes"] = "box"

_ALIAS_PATTERN = "|".join(sorted((re.escape(a) for a in _ALIASES), key=len, reverse=True))

UNICODE_FRACTIONS = {
    "½": 0.5, "⅓": 1 / 3, "⅔": 2 / 3, "¼": 0.25, "¾": 0.75, "⅕": 0.2, "⅖": 0.4,
    "⅗": 0.6, "⅘": 0.8, "⅙": 1 / 6, "⅚": 5 / 6, "⅛": 0.125, "⅜": 0.375, "⅝": 0.625, "⅞": 0.875,
}
_UF = "".join(UNICODE_FRACTIONS)

_NUM = rf"(?:\d+\s*[{_UF}]|\d+\s+\d+\s*/\s*\d+|\d+\s*/\s*\d+|\d+(?:[.,]\d+)?|[{_UF}])"
_QTY_RE = re.compile(
    rf"^\s*(?P<q1>{_NUM})(?:\s*(?:-|–|—|to|or)\s*(?P<q2>{_NUM}))?\s*", re.IGNORECASE
)
_PAREN_RE = re.compile(r"^\s*(\([^)]*\))\s*")
_UNIT_RE = re.compile(rf"^(?P<unit>{_ALIAS_PATTERN})(?=$|[\s,.)(]|\b)\.?\s*(?:of\s+)?", re.IGNORECASE)


def parse_number(s: str) -> Optional[float]:
    s = s.strip()
    if not s:
        return None
    total = 0.0
    for ch, val in UNICODE_FRACTIONS.items():
        if ch in s:
            total += val
            s = s.replace(ch, " ")
    s = s.strip()
    if not s:
        return total
    parts = s.split()
    for p in parts:
        if "/" in p:
            a, _, b = p.partition("/")
            try:
                total += float(a) / float(b)
            except (ValueError, ZeroDivisionError):
                return None
        else:
            try:
                total += float(p.replace(",", "."))
            except ValueError:
                return None
    return total


@dataclass
class Ingredient:
    raw: str
    quantity: Optional[float] = None
    quantity_max: Optional[float] = None
    unit: Optional[str] = None
    size: Optional[str] = None  # e.g. "(14 oz)" in "1 (14 oz) can tomatoes"
    name: str = ""
    note: Optional[str] = None
    group: Optional[str] = None
    is_header: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Ingredient":
        fields = {k: d.get(k) for k in cls.__dataclass_fields__ if k in d}
        fields.setdefault("raw", d.get("raw") or d.get("text") or "")
        return cls(**fields)


def _clean(s: str) -> str:
    s = s.replace(" ", " ").replace(" ", " ")
    s = re.sub(r"^\s*[-*•▢□☐◦·]+\s*", "", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def is_group_header(line: str) -> bool:
    line = line.strip()
    if not line:
        return False
    if line.endswith(":") and len(line) < 60 and not _QTY_RE.match(line):
        return True
    if re.match(r"^for the\b", line, re.I) and len(line) < 50 and not _QTY_RE.match(line):
        return True
    return False


def parse_ingredient(line: str, group: Optional[str] = None) -> Ingredient:
    raw = _clean(line)
    ing = Ingredient(raw=raw, group=group)
    if is_group_header(raw):
        ing.is_header = True
        ing.name = raw.rstrip(":").strip()
        return ing

    rest = raw
    m = _QTY_RE.match(rest)
    if m:
        q1 = parse_number(m.group("q1"))
        q2 = parse_number(m.group("q2")) if m.group("q2") else None
        if q1 is not None:
            ing.quantity = q1
            ing.quantity_max = q2
            rest = rest[m.end():]
            pm = _PAREN_RE.match(rest)
            if pm:
                ing.size = pm.group(1)
                rest = rest[pm.end():]
    # Unit: "T" (capital) = tbsp, "t" = tsp, only directly after a quantity
    if ing.quantity is not None:
        tm = re.match(r"^(T|t|c|C)\b\.?\s+", rest)
        if tm:
            ing.unit = {"T": "tbsp", "t": "tsp"}.get(tm.group(1), "cup")
            rest = rest[tm.end():]
        else:
            um = _UNIT_RE.match(rest)
            if um:
                alias = um.group("unit").lower()
                canon = _ALIASES.get(alias)
                # "c" alone only counts as cup when followed by a space
                if canon:
                    ing.unit = canon
                    rest = rest[um.end():]
    rest = rest.strip()
    if "," in rest:
        name, _, note = rest.partition(",")
        ing.name, ing.note = name.strip(), note.strip() or None
    else:
        ing.name = rest
    return ing


def parse_ingredient_lines(lines: list) -> list[Ingredient]:
    """Parse a list of strings or {raw/text, group} dicts, tracking group headers."""
    out: list[Ingredient] = []
    group: Optional[str] = None
    for item in lines:
        if isinstance(item, dict):
            text = item.get("raw") or item.get("text") or ""
            g = item.get("group") or group
        else:
            text, g = str(item), group
        if not text.strip():
            continue
        ing = parse_ingredient(text, g)
        if ing.is_header:
            group = ing.name
            continue
        out.append(ing)
    return out


# ---------------------------------------------------------------------------
# Densities (grams per US cup) so "2 cups flour" can become grams in metric
# ---------------------------------------------------------------------------
DENSITY_G_PER_CUP = [
    ("almond flour", 96), ("bread flour", 127), ("cake flour", 114), ("whole wheat flour", 120),
    ("flour", 125), ("powdered sugar", 120), ("icing sugar", 120), ("confectioners", 120),
    ("brown sugar", 213), ("caster sugar", 200), ("granulated sugar", 200), ("sugar", 200),
    ("cocoa", 85), ("butter", 227), ("rolled oats", 90), ("oats", 90), ("rice", 185),
    ("honey", 340), ("maple syrup", 315), ("peanut butter", 258), ("cornstarch", 128),
    ("chocolate chips", 170), ("shredded cheese", 113), ("parmesan", 100), ("breadcrumbs", 108),
    ("panko", 50), ("ricotta", 246), ("cream cheese", 232), ("sour cream", 230),
    ("greek yogurt", 245), ("yogurt", 245), ("mascarpone", 240), ("cottage cheese", 225), ("grated cheese", 100),
    ("cornmeal", 138), ("semolina", 167), ("lentils", 192), ("quinoa", 170), ("couscous", 173), ("chickpeas", 164),
    ("frozen peas", 134), ("mayonnaise", 220), ("jam", 320), ("nutella", 296), ("tahini", 240), ("walnuts", 117), ("pecans", 109), ("almonds", 143), ("raisins", 149),
    ("shortening", 192), ("coconut flakes", 85), ("shredded coconut", 85), ("salt", 292),
]


def _density(name: str) -> Optional[float]:
    n = name.lower()
    for key, d in DENSITY_G_PER_CUP:
        if key in n:
            return d
    return None


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------
_NICE_FRACTIONS = [
    (0, ""), (1 / 8, "⅛"), (1 / 4, "¼"), (1 / 3, "⅓"), (3 / 8, "⅜"), (1 / 2, "½"),
    (5 / 8, "⅝"), (2 / 3, "⅔"), (3 / 4, "¾"), (7 / 8, "⅞"), (1, ""),
]


def format_quantity(q: float, prefer_fractions: bool = True) -> str:
    if q is None:
        return ""
    if q <= 0:
        return "0"
    whole = int(q)
    frac = q - whole
    if prefer_fractions and q < 20:
        best = min(_NICE_FRACTIONS, key=lambda f: abs(f[0] - frac))
        if abs(best[0] - frac) <= 0.04 or (whole == 0 and abs(best[0] - frac) <= 0.06):
            if best[0] == 1:
                return str(whole + 1)
            if best[1] == "":
                return str(whole) if whole else _fmt_decimal(q)
            return f"{whole}{best[1]}" if whole else best[1]
    return _fmt_decimal(q)


def _fmt_decimal(q: float) -> str:
    if q >= 100:
        return str(int(round(q)))
    if q >= 10:
        return f"{q:.1f}".rstrip("0").rstrip(".")
    return f"{q:.2f}".rstrip("0").rstrip(".")


def _round_metric(q: float) -> float:
    if q < 10:
        return round(q * 2) / 2
    if q < 100:
        return float(round(q))
    if q < 1000:
        return float(round(q / 5) * 5)
    return float(round(q / 10) * 10)


_PLURAL_UNITS = {"cup": "cups", "pint": "pints", "quart": "quarts", "gallon": "gallons",
                 "stick": "sticks", "pinch": "pinches", "dash": "dashes", "leaf": "leaves",
                 "box": "boxes"}


def unit_label(unit: Optional[str], qty: Optional[float]) -> str:
    if not unit:
        return ""
    plural = qty is not None and (qty > 1 or (qty == 0))
    if plural:
        if unit in _PLURAL_UNITS:
            return _PLURAL_UNITS[unit]
        if unit in COUNT_UNITS:
            return unit + "s"
    return unit


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------

def to_base(qty: float, unit: str) -> tuple[str, float] | None:
    if unit not in UNITS:
        return None
    fam, f = UNITS[unit]
    return fam, qty * f


def best_metric(fam: str, base: float) -> tuple[float, str]:
    if fam == "volume":
        if base >= 1000:
            return round(base / 1000, 2), "l"
        return _round_metric(base), "ml"
    if base >= 1000:
        return round(base / 1000, 2), "kg"
    return _round_metric(base), "g"


def _round_to(q: float, step: float) -> float:
    return max(step, round(q / step) * step)


def best_imperial(fam: str, base: float) -> tuple[float, str]:
    q, u = _best_imperial(fam, base)
    return _round_to(q, 0.25 if u in ("oz", "lb") else 0.125), u


def _best_imperial(fam: str, base: float) -> tuple[float, str]:
    if fam == "volume":
        if base < 14:
            return base / UNITS["tsp"][1], "tsp"
        if base < 59:
            return base / UNITS["tbsp"][1], "tbsp"
        if base >= 3785 * 1.0:
            return base / UNITS["gallon"][1], "gallon"
        return base / UNITS["cup"][1], "cup"
    if base >= 453:
        return base / UNITS["lb"][1], "lb"
    return base / UNITS["oz"][1], "oz"


METRIC = {"ml", "cl", "dl", "l", "g", "mg", "kg"}
IMPERIAL = {"cup", "fl oz", "pint", "quart", "gallon", "oz", "lb", "stick"}


def convert(qty: float, unit: Optional[str], name: str, system: Optional[str]) -> tuple[float, Optional[str]]:
    """Convert a quantity to the requested measuring system ('metric'|'imperial'|None)."""
    if qty is None or not unit or system not in ("metric", "imperial") or unit not in UNITS:
        return qty, unit
    if system == "metric":
        if unit in METRIC or unit in ("tsp", "tbsp"):
            # spoons are used everywhere; leave them alone
            if unit in METRIC:
                fam, base = to_base(qty, unit)
                return best_metric(fam, base)
            return qty, unit
        fam, base = to_base(qty, unit)
        if fam == "volume":
            d = _density(name)
            if d:
                grams = base / UNITS["cup"][1] * d
                return best_metric("weight", grams)
        return best_metric(fam, base)
    # imperial
    if unit in IMPERIAL or unit in ("tsp", "tbsp"):
        return qty, unit
    fam, base = to_base(qty, unit)
    return best_imperial(fam, base)


def render(ing: Ingredient | dict, factor: float = 1.0, system: Optional[str] = None) -> dict:
    """Return the ingredient scaled + converted with a display string."""
    if isinstance(ing, dict):
        ing = Ingredient.from_dict(ing)
    q, qmax, unit = ing.quantity, ing.quantity_max, ing.unit
    if q is not None:
        q = q * factor
        qmax = qmax * factor if qmax is not None else None
        q_conv, unit_conv = convert(q, unit, ing.name, system)
        if qmax is not None and unit_conv != unit:
            qmax, _ = convert(qmax, unit, ing.name, system)
        q, unit = q_conv, unit_conv
    if q is None:
        display = ing.raw if factor == 1.0 and system is None else ing.raw
        return {**ing.to_dict(), "display": display, "display_quantity": "", "display_unit": ""}
    metric_unit = unit in METRIC
    qs = format_quantity(q, prefer_fractions=not metric_unit)
    if qmax is not None:
        qs = f"{qs}–{format_quantity(qmax, prefer_fractions=not metric_unit)}"
    ul = unit_label(unit, qmax if qmax is not None else q)
    parts = [qs]
    if ing.size:
        parts.append(ing.size)
    if ul:
        parts.append(ul)
    parts.append(ing.name)
    display = " ".join(p for p in parts if p)
    if ing.note:
        display += f", {ing.note}"
    return {
        **ing.to_dict(),
        "quantity": q,
        "quantity_max": qmax,
        "unit": unit,
        "display": display,
        "display_quantity": qs,
        "display_unit": ul,
    }


# ---------------------------------------------------------------------------
# Temperatures inside step text
# ---------------------------------------------------------------------------
_TEMP_RE = re.compile(
    r"(?P<num>\d{2,3})\s*(?:°|º|degrees?\s*|deg\.?\s*)\s*(?P<scale>F|C|Fahrenheit|Celsius)\b",
    re.IGNORECASE,
)


def convert_temperatures(text: str, system: Optional[str]) -> str:
    if system not in ("metric", "imperial"):
        return text

    def repl(m: re.Match) -> str:
        n = int(m.group("num"))
        scale = m.group("scale")[0].upper()
        if system == "metric" and scale == "F":
            c = round((n - 32) * 5 / 9 / 5) * 5
            return f"{c}°C"
        if system == "imperial" and scale == "C":
            raw = n * 9 / 5 + 32
            f = round(raw / 25) * 25 if raw > 250 else round(raw / 5) * 5
            return f"{f}°F"
        return m.group(0)

    return _TEMP_RE.sub(repl, text)


# ---------------------------------------------------------------------------
# Name normalization (shopping list merge key)
# ---------------------------------------------------------------------------
_DESCRIPTORS = {
    "fresh", "freshly", "large", "small", "medium", "chopped", "minced", "diced", "sliced",
    "ripe", "finely", "roughly", "thinly", "coarsely", "grated", "shredded", "peeled",
    "crushed", "packed", "softened", "melted", "cold", "warm", "room-temperature",
    "boneless", "skinless", "organic", "extra", "optional", "about", "heaping", "level",
}


def singular(word: str) -> str:
    if word in ("leaves", "loaves", "halves"):
        return word[:-3] + "f"
    if len(word) <= 3:
        return word
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith(("oes", "ches", "shes", "sses")):
        return word[:-2]
    if word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def normalize_name(name: str) -> str:
    n = re.sub(r"\([^)]*\)", " ", name.lower())
    n = re.split(r"\bor\b|;", n)[0]
    words = [w for w in re.findall(r"[a-zà-ÿ'-]+", n) if w not in _DESCRIPTORS and w not in ("of", "a", "an", "the")]
    if not words:
        return name.lower().strip()
    words[-1] = singular(words[-1])
    return " ".join(words)
