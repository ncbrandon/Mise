"""Run with:  python -m pytest tests  (or: python tests/test_services.py)"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.extract import extract_recipe, parse_duration, page_text
from app.services.ingredients import parse_ingredient, render, convert_temperatures, parse_ingredient_lines
from app.services.textparse import parse_text
from app.services.categorize import categorize
from app.services.shopping import merge_into, display_item, aisle_for

JSONLD_PAGE = """<html><head><title>Best Lasagna | Blog</title>
<meta property="og:image" content="/img/og.jpg">
<script type="application/ld+json">{"@context":"https://schema.org","@graph":[
 {"@type":"WebPage","name":"x"},
 {"@type":["Recipe"],"name":"Best Lasagna &amp; Garlic Bread","image":[{"@type":"ImageObject","url":"https://ex.com/a.jpg"}],
  "recipeYield":["8","8 servings"],"prepTime":"PT30M","cookTime":"PT1H15M",
  "recipeIngredient":["1 lb ground beef","2 cups ricotta cheese","12 lasagna noodles","For the sauce:","1 (28 oz) can crushed tomatoes"],
  "recipeInstructions":[{"@type":"HowToSection","name":"Sauce","itemListElement":[{"@type":"HowToStep","text":"Brown the beef."},{"@type":"HowToStep","text":"Add tomatoes and simmer."}]},
                         {"@type":"HowToStep","text":"Layer and bake at 375°F for 45 minutes."}],
  "recipeCategory":"Dinner","recipeCuisine":["Italian"],"keywords":"lasagna, pasta",
  "nutrition":{"@type":"NutritionInformation","calories":"520 kcal","proteinContent":"30 g"}}
]}</script></head><body><article><p>Life story...</p></article></body></html>"""

MICRODATA_PAGE = """<html><body><div itemscope itemtype="http://schema.org/Recipe">
<h1 itemprop="name">Pancakes</h1>
<span itemprop="recipeYield">4</span>
<li itemprop="recipeIngredient">1 cup flour</li><li itemprop="recipeIngredient">1 egg</li>
<li itemprop="recipeInstructions">Mix.</li><li itemprop="recipeInstructions">Cook on a griddle.</li>
</div></body></html>"""


def test_jsonld():
    r = extract_recipe(JSONLD_PAGE, "https://ex.com/lasagna")
    assert r["title"] == "Best Lasagna & Garlic Bread"
    assert r["image_url"] == "https://ex.com/a.jpg"
    assert r["servings"] == 8 and r["servings_text"] == "8 servings"
    assert r["prep_time"] == 30 and r["cook_time"] == 75
    assert len(r["ingredients"]) == 5
    assert r["steps"][0] == {"text": "Brown the beef.", "section": "Sauce"}
    assert r["steps"][2]["section"] is None
    assert r["cuisine"] == "Italian"
    assert r["nutrition"]["calories"] == 520


def test_microdata():
    r = extract_recipe(MICRODATA_PAGE, "https://ex.com/p")
    assert r["title"] == "Pancakes"
    assert r["ingredients"] == ["1 cup flour", "1 egg"]
    assert len(r["steps"]) == 2


def test_groups():
    ings = parse_ingredient_lines(["1 lb beef", "For the sauce:", "1 can tomatoes", "2 tbsp oil"])
    assert [i.group for i in ings] == [None, "For the sauce", "For the sauce"]


def test_duration():
    assert parse_duration("PT1H30M") == 90
    assert parse_duration("P0DT0H20M") == 20
    assert parse_duration("") is None


def test_scaling_and_units():
    i = parse_ingredient("1 1/2 cups all-purpose flour")
    assert render(i, 2)["display"] == "3 cups all-purpose flour"
    assert render(i, 1, "metric")["display"] == "190 g all-purpose flour"
    assert render(parse_ingredient("1 cup milk"), 1, "metric")["display"] == "235 ml milk"
    assert render(parse_ingredient("250 g butter"), 1, "imperial")["display"] == "8¾ oz butter"
    assert convert_temperatures("Bake at 350°F", "metric") == "Bake at 175°C"


def test_textparse_headings():
    t = """Grandma's Chili
Serves 6
Ingredients
- 2 lb ground beef
- 1 onion, diced
- 2 cans kidney beans
Instructions
1. Brown beef with onion.
2. Add beans and simmer 1 hour.
#chili #dinner"""
    r = parse_text(t)
    assert r["title"] == "Grandma's Chili"
    assert r["servings"] == 6
    assert len(r["ingredients"]) == 3
    assert r["steps"][0]["text"] == "Brown beef with onion."
    assert len(r["steps"]) == 2


def test_textparse_no_headings():
    t = """Quick garlic noodles 🍜
200g spaghetti
4 tbsp butter
6 cloves garlic
Boil the noodles in salted water until al dente.
Melt butter, fry garlic, then toss everything together with parmesan."""
    r = parse_text(t)
    assert len(r["ingredients"]) == 3
    assert len(r["steps"]) == 2


def test_categorize():
    c = categorize("Creamy Tomato Soup", ["2 cans tomatoes", "1 cup cream", "1 onion"], 25)
    assert "Soups & Stews" in c and "Vegetarian" in c and "Quick (under 30 min)" in c and "Vegan" not in c
    c = categorize("Chocolate Chip Cookies", ["2 cups flour", "1 tsp baking soda", "1 cup butter"])
    assert "Desserts" in c and "Baking" in c
    c = categorize("Lemon Chicken", ["4 chicken thighs", "1 lemon"])
    assert "Chicken" in c and "Dinner" in c


def test_shopping_merge():
    items = []
    merge_into(items, parse_ingredient("2 cups milk"), 1, "Pancakes")
    merge_into(items, parse_ingredient("1/2 cup milk"), 2, "Cake")
    merge_into(items, parse_ingredient("3 large eggs"), 1, "Cake")
    merge_into(items, parse_ingredient("1 egg"), 1, "Pancakes")
    merge_into(items, parse_ingredient("1 cup water"), 1, "Cake")
    assert len(items) == 2
    milk = next(i for i in items if i["key"] == "milk")
    assert display_item(milk["name"], milk["quantity"], milk["unit"]) == "3 cups milk"
    egg = next(i for i in items if i["key"] == "egg")
    assert egg["quantity"] == 4 and egg["sources"] == ["Cake", "Pancakes"]
    assert aisle_for("garlic powder") == "Spices & Seasonings"
    assert aisle_for("garlic") == "Produce"
    assert aisle_for("cheddar cheese") == "Dairy & Eggs"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
