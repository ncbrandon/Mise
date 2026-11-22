"""Extract a structured recipe from a web page.

Order of attempts: schema.org JSON-LD -> schema.org microdata -> common plugin
markup (WP Recipe Maker / Tasty) -> caller may fall back to the LLM with page_text().
"""
from __future__ import annotations

import html as htmllib
import json
import re
from typing import Any, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup


def _text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, list):
        v = " ".join(_text(x) for x in v)
    if isinstance(v, dict):
        v = v.get("text") or v.get("name") or v.get("@value") or ""
    s = htmllib.unescape(str(v))
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def parse_duration(v: Any) -> Optional[int]:
    """ISO-8601 duration (PT1H30M) -> minutes."""
    if not v:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip().upper()
    m = re.match(r"^P(?:(\d+)D)?(?:T(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?)?$", s)
    if m and any(m.groups()):
        d, h, mi, sec = (float(x) if x else 0 for x in m.groups())
        total = int(round(d * 1440 + h * 60 + mi + sec / 60))
        return total or None
    m = re.search(r"(\d+)\s*(?:min|minutes)", s, re.I)
    if m:
        return int(m.group(1))
    return None


def parse_yield(v: Any) -> tuple[Optional[float], Optional[str]]:
    if v is None:
        return None, None
    if isinstance(v, list):
        nums = [parse_yield(x) for x in v]
        text = next((t for _, t in nums if t and not re.fullmatch(r"\d+", t)), None)
        num = next((n for n, _ in nums if n), None)
        return num, text or (str(int(num)) if num else None)
    if isinstance(v, (int, float)):
        return float(v), str(int(v)) if float(v).is_integer() else str(v)
    s = _text(v)
    m = re.search(r"\d+(?:\.\d+)?", s)
    return (float(m.group(0)) if m else None), s or None


def _image(v: Any, base: str) -> Optional[str]:
    if not v:
        return None
    if isinstance(v, list):
        # prefer the largest-looking one (often last), but any string works
        for x in reversed(v):
            r = _image(x, base)
            if r:
                return r
        return None
    if isinstance(v, dict):
        return _image(v.get("url") or v.get("contentUrl") or v.get("@id"), base)
    s = str(v).strip()
    return urljoin(base, s) if s else None


def _as_list(v: Any) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _types(node: dict) -> list[str]:
    t = node.get("@type")
    return [str(x) for x in _as_list(t)]


def _find_recipe_nodes(data: Any) -> list[dict]:
    found: list[dict] = []

    def walk(n: Any, depth: int = 0) -> None:
        if depth > 8:
            return
        if isinstance(n, list):
            for x in n:
                walk(x, depth + 1)
        elif isinstance(n, dict):
            if any(t.lower() == "recipe" or t.lower().endswith("/recipe") for t in _types(n)):
                found.append(n)
                return
            for key in ("@graph", "mainEntity", "mainEntityOfPage", "itemListElement", "item", "hasPart"):
                if key in n:
                    walk(n[key], depth + 1)

    walk(data)
    return found


def _loads_lenient(raw: str) -> Any:
    raw = raw.strip()
    if raw.startswith("<!--"):
        raw = raw[4:]
    if raw.endswith("-->"):
        raw = raw[:-3]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # strip trailing commas and control chars, a common CMS bug
        cleaned = re.sub(r",\s*([}\]])", r"\1", raw)
        cleaned = re.sub(r"[\x00-\x1f]", " ", cleaned)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return None


def _instructions(v: Any) -> list[dict]:
    steps: list[dict] = []

    def add(item: Any, section: Optional[str]) -> None:
        if item is None:
            return
        if isinstance(item, str):
            txt = _text(item)
            # a single blob: split into sentences-ish lines
            parts = [p.strip() for p in re.split(r"\n+|(?<=[.!?])\s+(?=\d+[.)]\s)", txt) if p.strip()]
            for p in parts:
                p = re.sub(r"^\d+[.)]\s*", "", p)
                if p:
                    steps.append({"text": p, "section": section})
            return
        if isinstance(item, list):
            for x in item:
                add(x, section)
            return
        if isinstance(item, dict):
            types = [t.lower() for t in _types(item)]
            if "howtosection" in types or ("itemlistelement" in {k.lower() for k in item} and "text" not in item):
                add(item.get("itemListElement"), _text(item.get("name")) or section)
                return
            txt = _text(item.get("text") or item.get("description") or item.get("name"))
            if txt:
                steps.append({"text": txt, "section": section})

    add(v, None)
    # drop duplicates while keeping order
    seen, out = set(), []
    for s in steps:
        k = s["text"].lower()
        if k not in seen:
            seen.add(k)
            out.append(s)
    return out


def _nutrition(v: Any) -> Optional[dict]:
    if not isinstance(v, dict):
        return None
    mapping = {
        "calories": "calories", "proteinContent": "protein_g", "carbohydrateContent": "carbs_g",
        "fatContent": "fat_g", "saturatedFatContent": "saturated_fat_g", "fiberContent": "fiber_g",
        "sugarContent": "sugar_g", "sodiumContent": "sodium_mg", "cholesterolContent": "cholesterol_mg",
    }
    out: dict[str, Any] = {}
    for k, nk in mapping.items():
        if k in v:
            m = re.search(r"\d+(?:\.\d+)?", _text(v[k]))
            if m:
                out[nk] = float(m.group(0))
    if not out:
        return None
    out["per"] = "serving"
    out["source"] = "publisher"
    return out


def _keywords(v: Any) -> list[str]:
    if not v:
        return []
    if isinstance(v, list):
        items = [_text(x) for x in v]
    else:
        items = re.split(r"[,;]", _text(v))
    return [i.strip() for i in items if i.strip()][:20]


def recipe_from_node(node: dict, base_url: str) -> dict:
    servings, servings_text = parse_yield(node.get("recipeYield") or node.get("yield"))
    ingredients = [_text(x) for x in _as_list(node.get("recipeIngredient") or node.get("ingredients"))]
    author = node.get("author")
    if isinstance(author, list):
        author = author[0] if author else None
    return {
        "title": _text(node.get("name")) or "Untitled recipe",
        "description": _text(node.get("description")) or None,
        "image_url": _image(node.get("image") or node.get("thumbnailUrl"), base_url),
        "author": _text(author) or None,
        "servings": servings,
        "servings_text": servings_text,
        "prep_time": parse_duration(node.get("prepTime")),
        "cook_time": parse_duration(node.get("cookTime")),
        "total_time": parse_duration(node.get("totalTime")),
        "ingredients": [i for i in ingredients if i],
        "steps": _instructions(node.get("recipeInstructions")),
        "categories": [c for c in (_text(x) for x in _as_list(node.get("recipeCategory"))) if c],
        "cuisine": _text(_as_list(node.get("recipeCuisine"))[0]) if node.get("recipeCuisine") else None,
        "keywords": _keywords(node.get("keywords")),
        "nutrition": _nutrition(node.get("nutrition")),
    }


def _from_jsonld(soup: BeautifulSoup, url: str) -> Optional[dict]:
    for tag in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        data = _loads_lenient(tag.string or tag.get_text() or "")
        if data is None:
            continue
        for node in _find_recipe_nodes(data):
            r = recipe_from_node(node, url)
            if r["ingredients"] or r["steps"]:
                return r
    return None


def _from_microdata(soup: BeautifulSoup, url: str) -> Optional[dict]:
    scope = soup.find(attrs={"itemtype": re.compile(r"schema\.org/Recipe", re.I)})
    if not scope:
        return None

    def props(name: str) -> list:
        return scope.find_all(attrs={"itemprop": name})

    def val(el) -> str:
        if el is None:
            return ""
        return el.get("content") or el.get("datetime") or el.get_text(" ", strip=True)

    node = {
        "@type": "Recipe",
        "name": val(next(iter(props("name")), None)),
        "description": val(next(iter(props("description")), None)),
        "image": (lambda e: e and (e.get("src") or e.get("content") or e.get("href")))(next(iter(props("image")), None)),
        "recipeYield": val(next(iter(props("recipeYield")), None)),
        "prepTime": val(next(iter(props("prepTime")), None)),
        "cookTime": val(next(iter(props("cookTime")), None)),
        "totalTime": val(next(iter(props("totalTime")), None)),
        "recipeIngredient": [val(e) for e in (props("recipeIngredient") or props("ingredients"))],
        "recipeInstructions": [val(e) for e in props("recipeInstructions")],
    }
    r = recipe_from_node(node, url)
    return r if r["ingredients"] else None


def _from_plugins(soup: BeautifulSoup, url: str) -> Optional[dict]:
    # WP Recipe Maker
    ing = soup.select(".wprm-recipe-ingredient") or soup.select(".tasty-recipes-ingredients li") \
        or soup.select(".mv-create-ingredients li") or soup.select("[class*=ingredient] li")
    ins = soup.select(".wprm-recipe-instruction-text") or soup.select(".tasty-recipes-instructions li") \
        or soup.select(".mv-create-instructions li") or soup.select("[class*=instruction] li, [class*=direction] li")
    if len(ing) < 2 or not ins:
        return None
    title_el = soup.select_one(".wprm-recipe-name, .tasty-recipes-title, h1")
    node = {
        "@type": "Recipe",
        "name": title_el.get_text(" ", strip=True) if title_el else "",
        "recipeIngredient": [e.get_text(" ", strip=True) for e in ing],
        "recipeInstructions": [e.get_text(" ", strip=True) for e in ins],
    }
    return recipe_from_node(node, url)


def _meta(soup: BeautifulSoup, *names: str) -> Optional[str]:
    for n in names:
        el = soup.find("meta", attrs={"property": n}) or soup.find("meta", attrs={"name": n})
        if el and el.get("content"):
            return el["content"].strip()
    return None


def extract_recipe(html: str, url: str) -> Optional[dict]:
    soup = BeautifulSoup(html, "lxml")
    r = _from_jsonld(soup, url) or _from_microdata(soup, url) or _from_plugins(soup, url)
    if r is None:
        return None
    if not r.get("image_url"):
        img = _meta(soup, "og:image", "twitter:image")
        r["image_url"] = urljoin(url, img) if img else None
    if not r.get("description"):
        r["description"] = _meta(soup, "og:description", "description")
    r["source_url"] = url
    return r


def page_meta(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    img = _meta(soup, "og:image", "twitter:image")
    return {
        "title": _meta(soup, "og:title") or (soup.title.get_text(strip=True) if soup.title else None),
        "image_url": urljoin(url, img) if img else None,
        "description": _meta(soup, "og:description", "description"),
    }


def page_text(html: str, limit: int = 20000) -> str:
    """Main readable text of a page, for LLM fallback."""
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style", "noscript", "nav", "footer", "header", "aside", "form", "iframe", "svg"]):
        t.decompose()
    for t in soup.select("[class*=comment], [id*=comment], [class*=sidebar], [class*=related], [class*=newsletter], [class*=advert], [class*=-ad-], [id*=ad-]"):
        t.decompose()
    main = soup.find("article") or soup.find("main") or soup.body or soup
    text = main.get_text("\n", strip=True)
    text = re.sub(r"\n{2,}", "\n", text)
    if len(text) > limit:
        # recipes live near "ingredients"; centre the window on that word
        idx = text.lower().find("ingredient")
        start = max(0, idx - limit // 4) if idx > 0 else 0
        text = text[start:start + limit]
    return text


URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")


def find_urls(text: str) -> list[str]:
    return [u.rstrip(".,;!") for u in URL_RE.findall(text or "")]
