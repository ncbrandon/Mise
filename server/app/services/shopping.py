"""Smart shopping list: merge duplicate ingredients across recipes, sort by aisle."""
from __future__ import annotations

import re
from typing import Optional

from .ingredients import (UNITS, Ingredient, best_imperial, best_metric, format_quantity,
                          normalize_name, unit_label, METRIC)

AISLES = ["Produce", "Meat & Seafood", "Dairy & Eggs", "Bakery", "Pantry", "Spices & Seasonings",
          "Canned & Jarred", "Frozen", "Beverages", "Other"]

_AISLE_RULES: list[tuple[str, str]] = [
    ("Frozen", r"\bfrozen\b"),
    ("Canned & Jarred", r"\b(canned|can of|jar of|tomato paste|tomato sauce|crushed tomatoes|diced tomatoes|coconut milk|beans|chickpeas|olives|capers|pickles?|salsa|broth|stock)\b"),
    ("Spices & Seasonings", r"\b(salt|pepper(corns)?|cumin|paprika|cinnamon|nutmeg|oregano|thyme dried|dried|powder|chili flakes|red pepper flakes|turmeric|coriander seed|cayenne|garam masala|curry|bay lea|allspice|cloves ground|seasoning|vanilla|extract|ground ginger|five spice|saffron|sesame seeds)\b"),
    ("Meat & Seafood", r"\b(chicken|beef|pork|bacon|sausage|turkey|lamb|steak|ham|ground meat|mince|salmon|fish|shrimp|prawn|cod|tuna steak|crab|scallop|mussel|clam|chorizo|prosciutto|pancetta)\b"),
    ("Dairy & Eggs", r"\b(milk|butter|cheese|cream|yogurt|yoghurt|egg|eggs|sour cream|creme fraiche|crème fraîche|buttermilk|parmesan|mozzarella|cheddar|ricotta|feta|ghee|half-and-half)\b"),
    ("Bakery", r"\b(bread|bun|buns|tortilla|pita|naan|baguette|croissant|rolls|brioche|bagel)\b"),
    ("Beverages", r"\b(wine|beer|juice|soda|sparkling water|coffee|tea|rum|vodka|gin|whiskey|tequila|bourbon)\b"),
    ("Produce", r"\b(onion|garlic|shallot|tomato|potato|carrot|celery|lettuce|spinach|kale|cabbage|broccoli|cauliflower|zucchini|courgette|squash|pumpkin|cucumber|bell pepper|jalapeño|jalapeno|chili|chile|avocado|lemon|lime|orange|apple|banana|berr(y|ies)|strawberr|blueberr|raspberr|grape|mango|pineapple|peach|pear|herb|basil|parsley|cilantro|coriander|mint|dill|rosemary|thyme|sage|chive|scallion|green onion|leek|ginger|mushroom|eggplant|aubergine|corn|peas|green beans|asparagus|arugula|rocket|beet|radish|sweet potato|fennel|lemongrass)\b"),
    ("Pantry", r"\b(flour|sugar|oil|vinegar|rice|pasta|noodle|spaghetti|oats|honey|syrup|soy sauce|fish sauce|mustard|ketchup|mayonnaise|mayo|baking|yeast|cornstarch|cocoa|chocolate|nuts?|almond|walnut|pecan|peanut|breadcrumb|panko|quinoa|lentil|couscous|tahini|sriracha|worcestershire|stock cube|bouillon|raisins|coconut)\b"),
]

SKIP = re.compile(r"^(water|ice|ice cubes|hot water|cold water|warm water)$", re.I)


def aisle_for(name: str) -> str:
    n = name.lower()
    for aisle, rx in _AISLE_RULES:
        if re.search(rx, n):
            return aisle
    return "Other"


def to_base(qty: Optional[float], unit: Optional[str]) -> tuple[Optional[float], Optional[str]]:
    """Return quantity in a merge-friendly unit: ml / g for convertible units, else unchanged."""
    if qty is None:
        return None, unit
    if unit in UNITS:
        fam, f = UNITS[unit]
        return qty * f, ("ml" if fam == "volume" else "g")
    return qty, unit


def display_item(name: str, qty: Optional[float], unit: Optional[str], system: str = "imperial") -> str:
    if qty is None:
        return name
    q, u = qty, unit
    if unit in ("ml", "g"):
        fam = "volume" if unit == "ml" else "weight"
        q, u = best_metric(fam, qty) if system == "metric" else best_imperial(fam, qty)
    qs = format_quantity(q, prefer_fractions=u not in METRIC)
    ul = unit_label(u, q)
    return " ".join(p for p in (qs, ul, name) if p)


def merge_into(items: list[dict], ingredient: Ingredient, factor: float, recipe_title: Optional[str]) -> list[dict]:
    """Merge one ingredient into a list of item dicts (name, key, quantity, unit, aisle, checked, sources).
    Returns the list (mutated) for convenience."""
    if ingredient.is_header or not ingredient.name:
        return items
    key = normalize_name(ingredient.name)
    if SKIP.match(key):
        return items
    qty = ingredient.quantity * factor if ingredient.quantity is not None else None
    qty, unit = to_base(qty, ingredient.unit)
    for it in items:
        if it.get("checked"):
            continue
        if it["key"] == key and (it.get("unit") == unit or it.get("quantity") is None or qty is None):
            if qty is not None:
                if it.get("quantity") is None:
                    it["quantity"], it["unit"] = qty, unit
                elif it.get("unit") == unit:
                    it["quantity"] += qty
            if recipe_title and recipe_title not in it["sources"]:
                it["sources"].append(recipe_title)
            return items
    items.append({
        "name": ingredient.name.strip(),
        "key": key,
        "quantity": qty,
        "unit": unit,
        "aisle": aisle_for(ingredient.name),
        "checked": False,
        "sources": [recipe_title] if recipe_title else [],
    })
    return items
