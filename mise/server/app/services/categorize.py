"""Keyword-based auto categorization (used when no LLM is configured, and to
normalize LLM output onto a stable category list)."""
from __future__ import annotations

import re

CATEGORIES = [
    "Breakfast", "Lunch", "Dinner", "Appetizers", "Soups & Stews", "Salads", "Pasta & Noodles",
    "Rice & Grains", "Chicken", "Beef", "Pork", "Lamb", "Seafood", "Vegetarian", "Vegan",
    "Sides", "Sauces & Dressings", "Breads", "Baking", "Desserts", "Snacks", "Drinks",
    "Slow Cooker", "Air Fryer", "Grilling", "Quick (under 30 min)",
]

_RULES: list[tuple[str, str]] = [
    ("Breakfast", r"\b(pancake|waffle|omelet|omelette|frittata|granola|oatmeal|porridge|french toast|breakfast|brunch|scrambled|muffin|bagel|smoothie bowl|shakshuka|crepe)s?\b"),
    ("Soups & Stews", r"\b(soup|stew|chowder|bisque|chili|broth|ramen|pho|gumbo|minestrone)\b"),
    ("Salads", r"\b(salad|slaw|coleslaw)\b"),
    ("Pasta & Noodles", r"\b(pasta|spaghetti|penne|linguine|fettuccine|lasagna|lasagne|macaroni|mac and cheese|noodles?|orzo|gnocchi|ravioli|tortellini|rigatoni|udon|lo mein|pad thai)\b"),
    ("Rice & Grains", r"\b(risotto|fried rice|pilaf|paella|biryani|quinoa|couscous|farro|bulgur|rice bowl)\b"),
    ("Sauces & Dressings", r"\b(sauce|dressing|vinaigrette|pesto|salsa|gravy|aioli|marinade|dip|chutney|hummus)\b"),
    ("Breads", r"\b(bread|focaccia|brioche|baguette|sourdough|rolls?|biscuits?|naan|pita|flatbread|bagels?|challah)\b"),
    ("Desserts", r"\b(cake|cookies?|brownies?|pie|tart|cheesecake|pudding|ice cream|mousse|cupcakes?|fudge|tiramisu|cobbler|crumble|macarons?|dessert|frosting|truffles?|panna cotta|sorbet)\b"),
    ("Drinks", r"\b(cocktail|smoothie|lemonade|latte|tea|coffee|margarita|sangria|punch|milkshake|mocktail|juice|spritz)\b"),
    ("Appetizers", r"\b(appetizer|bruschetta|crostini|dip|wings|sliders|deviled eggs|spring rolls|dumplings?|nachos|tapas)\b"),
    ("Snacks", r"\b(snack|energy balls?|bites|popcorn|trail mix|chips|crackers|granola bars?)\b"),
    ("Slow Cooker", r"\b(slow cooker|crock ?pot|instant pot|pressure cooker)\b"),
    ("Air Fryer", r"\bair[- ]?fr(y|ied|yer)\b"),
    ("Grilling", r"\b(grill(ed)?|bbq|barbecue|kebabs?|skewers?|smoked)\b"),
    ("Sides", r"\b(side dish|roasted vegetables|mashed potatoes|fries|roasted potatoes|green beans|coleslaw)\b"),
]

_MEAT = {
    "Chicken": r"\b(chicken|turkey|poultry)\b",
    "Beef": r"\b(beef|steak|brisket|ground chuck|sirloin|ribeye|short ribs?|veal|meatballs?)\b",
    "Pork": r"\b(pork|bacon|ham|sausage|prosciutto|pancetta|chorizo|chops|pulled pork)\b",
    "Lamb": r"\b(lamb|mutton)\b",
    "Seafood": r"\b(fish|salmon|tuna|shrimp|prawns?|cod|tilapia|halibut|crab|lobster|scallops?|mussels|clams|anchov(y|ies)|sardines?|squid|calamari|seafood|trout|sea bass)\b",
}
_ANIMAL = r"\b(egg|eggs|milk|butter|cheese|cream|yogurt|yoghurt|honey|gelatin|mayonnaise|ghee|buttermilk|parmesan|mozzarella)\b"
_BAKING = r"\b(flour|baking powder|baking soda|yeast)\b"


def categorize(title: str, ingredients: list[str], total_time: int | None = None,
               existing: list[str] | None = None) -> list[str]:
    t = (title or "").lower()
    ing_text = " ".join(i.lower() for i in ingredients or [])
    cats: list[str] = []

    for cat, rx in _RULES:
        if re.search(rx, t):
            cats.append(cat)

    has_meat = False
    for cat, rx in _MEAT.items():
        if re.search(rx, t) or re.search(rx, ing_text):
            # stock/broth alone doesn't make it a chicken dish
            if cat == "Chicken" and not re.search(rx, t) and re.search(r"chicken (stock|broth|bouillon)", ing_text) \
                    and not re.search(r"chicken (breast|thigh|wing|leg|drumstick)s?|whole chicken|shredded chicken", ing_text):
                pass
            else:
                cats.append(cat)
        if re.search(rx, ing_text):
            has_meat = True
    if ingredients and not has_meat and not re.search(r"\b(gelatin|anchov|fish sauce|lard)\b", ing_text):
        if re.search(_ANIMAL, ing_text):
            cats.append("Vegetarian")
        else:
            cats.extend(["Vegetarian", "Vegan"])
    if re.search(_BAKING, ing_text) and "Breads" not in cats and "Desserts" not in cats and re.search(r"\b(bake|oven)\b", t + ing_text):
        cats.append("Baking")
    if "Desserts" in cats or "Breads" in cats:
        if re.search(_BAKING, ing_text):
            cats.append("Baking")
    if not any(c in cats for c in ("Breakfast", "Desserts", "Drinks", "Snacks", "Sauces & Dressings", "Appetizers", "Sides", "Breads")):
        if has_meat or any(c in cats for c in ("Pasta & Noodles", "Soups & Stews", "Rice & Grains")):
            cats.append("Dinner")
    if total_time and total_time <= 30:
        cats.append("Quick (under 30 min)")

    for e in existing or []:
        match = next((c for c in CATEGORIES if c.lower() == e.lower().strip()), None)
        if match:
            cats.append(match)

    seen, out = set(), []
    for c in cats:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out
