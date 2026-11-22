"""Turn any source (URL, video, text, photos, documents) into a normalized recipe draft."""
from __future__ import annotations

import logging
import re
import shutil
import os
from typing import Optional

from . import llm, textparse, video, documents
from .categorize import categorize as heuristic_categorize
from .extract import extract_recipe, find_urls, page_meta, page_text
from .fetch import FetchError, fetch_html
from .ingredients import parse_ingredient_lines

log = logging.getLogger("mise.import")


class ImportFailed(Exception):
    """Raised with a message that is safe to show the user."""


# ---------------------------------------------------------------------------
# Finalize
# ---------------------------------------------------------------------------

def finalize(draft: dict, source_type: str, enrich: bool = True) -> dict:
    ings = parse_ingredient_lines(draft.get("ingredients") or [])
    steps = []
    for s in draft.get("steps") or []:
        if isinstance(s, str):
            s = {"text": s, "section": None}
        if s.get("text", "").strip():
            steps.append({"text": s["text"].strip(), "section": s.get("section") or None})
    total = draft.get("total_time")
    if not total and (draft.get("prep_time") or draft.get("cook_time")):
        total = (draft.get("prep_time") or 0) + (draft.get("cook_time") or 0)
    out = {
        "title": (draft.get("title") or "Untitled recipe").strip()[:300],
        "description": draft.get("description"),
        "image_url": draft.get("image_url"),
        "source_url": draft.get("source_url"),
        "source_type": source_type,
        "author": draft.get("author"),
        "servings": draft.get("servings"),
        "servings_text": draft.get("servings_text"),
        "prep_time": draft.get("prep_time"),
        "cook_time": draft.get("cook_time"),
        "total_time": total,
        "ingredients": [i.to_dict() for i in ings],
        "steps": steps,
        "cuisine": draft.get("cuisine"),
        "nutrition": draft.get("nutrition"),
        "notes": draft.get("notes"),
        "categories": [],
    }
    if enrich:
        out["categories"] = auto_categories(out, draft.get("categories") or [])
        if not out["cuisine"] and draft.get("_llm_cuisine"):
            out["cuisine"] = draft["_llm_cuisine"]
    return out


def brief(recipe: dict) -> dict:
    return {
        "title": recipe.get("title"),
        "servings": recipe.get("servings"),
        "ingredients_text": [i.get("raw") for i in recipe.get("ingredients") or []],
        "steps_text": [s.get("text") for s in recipe.get("steps") or []],
    }


def auto_categories(recipe: dict, existing: list[str]) -> list[str]:
    names = [i.get("raw", "") for i in recipe.get("ingredients") or []]
    cats = heuristic_categorize(recipe["title"], names, recipe.get("total_time"), existing)
    if llm.enabled():
        try:
            res = llm.categorize(brief(recipe))
            # trust the model's categories; keep the heuristic's diet/time tags too
            keep = [c for c in cats if c in ("Quick (under 30 min)", "Vegetarian", "Vegan")]
            cats = list(dict.fromkeys(res["categories"] + keep)) or cats
            if res.get("cuisine") and not recipe.get("cuisine"):
                recipe["cuisine"] = res["cuisine"]
        except Exception as e:  # never fail an import because of categorization
            log.warning("LLM categorize failed: %s", e)
    return cats


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

def from_url(url: str, enrich: bool = True) -> dict:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    if video.is_video_url(url):
        return from_video(url, enrich)
    try:
        final, html = fetch_html(url)
    except FetchError as e:
        raise ImportFailed(f"Couldn't open that page: {e}")
    except Exception as e:
        raise ImportFailed(f"Couldn't open that page ({type(e).__name__})")
    return from_html(html, final, enrich)


def from_html(html: str, url: str, enrich: bool = True) -> dict:
    """Extract from page HTML we already have (fetched by the server, or by the phone when a site
    blocks the server)."""
    draft = extract_recipe(html, url)
    if draft:
        return finalize(draft, "web", enrich)
    meta = page_meta(html, url)
    text = page_text(html)
    if llm.enabled():
        try:
            d = llm.recipe_from_text(text, hint=f"web page {url}")
        except llm.LLMError as e:
            raise ImportFailed(f"No structured recipe on that page and the AI fallback failed: {e}")
        if d:
            d["image_url"] = d.get("image_url") or meta["image_url"]
            d["source_url"] = url
            return finalize(d, "web", enrich)
    else:
        d = textparse.parse_text(text, title=meta["title"])
        if len(d["ingredients"]) >= 2 and d["steps"]:
            d["image_url"] = meta["image_url"]
            d["source_url"] = url
            return finalize(d, "web", enrich)
    raise ImportFailed("Couldn't find a recipe on that page."
                       + ("" if llm.enabled() else " Configure an AI model on the server for tougher pages."))


def from_video(url: str, enrich: bool = True) -> dict:
    try:
        info = video.video_info(url)
    except Exception as e:
        raise ImportFailed(f"Couldn't read that video ({str(e)[:160]}). Instagram may need a cookies file on the server.")

    # 1) Creators often link the full recipe on their blog.
    for link in find_urls(info["description"])[:6]:
        if video.is_social(link):
            continue
        try:
            final, html = fetch_html(link)
        except Exception:
            continue
        d = extract_recipe(html, final)
        if d and len(d.get("ingredients") or []) >= 2:
            d["source_url"] = info["webpage_url"]
            d["notes"] = f"Full recipe: {final}"
            d["image_url"] = d.get("image_url") or info["thumbnail"]
            return finalize(d, "video", enrich)

    # 2) AI on description + captions (+ transcript)
    text = f"Title: {info['title']}\nCreator: {info.get('uploader') or ''}\n\nDescription:\n{info['description']}"
    if info["captions"]:
        text += f"\n\nCaptions:\n{info['captions']}"
    if llm.enabled():
        if not info["captions"]:
            transcript = _transcribe(url)
            if transcript:
                text += f"\n\nTranscript:\n{transcript}"
        try:
            d = llm.recipe_from_text(text, hint=f"video {info['webpage_url']}")
        except llm.LLMError as e:
            raise ImportFailed(f"AI extraction failed: {e}")
        if d:
            d["image_url"] = info["thumbnail"]
            d["source_url"] = info["webpage_url"]
            d["author"] = info.get("uploader")
            return finalize(d, "video", enrich)
        raise ImportFailed("That video doesn't seem to contain a recipe.")

    # 3) No AI: hope the caption lists the recipe
    d = textparse.parse_text(info["description"], title=info["title"])
    if d["ingredients"]:
        d["image_url"] = info["thumbnail"]
        d["source_url"] = info["webpage_url"]
        d["author"] = info.get("uploader")
        return finalize(d, "video", enrich)
    raise ImportFailed("The video caption has no recipe. Configure an AI model on the server to import from captions and speech.")


def _transcribe(url: str) -> Optional[str]:
    from ..config import get_settings
    if not get_settings().transcribe_model:
        return None
    path = None
    try:
        path = video.download_audio(url)
        return llm.transcribe(path) if path else None
    except Exception as e:
        log.warning("transcription failed: %s", e)
        return None
    finally:
        if path:
            shutil.rmtree(os.path.dirname(path), ignore_errors=True)


def from_text(text: str, title: Optional[str] = None, source_type: str = "text", enrich: bool = True) -> dict:
    if not text or not text.strip():
        raise ImportFailed("Nothing to import.")
    if llm.enabled():
        try:
            d = llm.recipe_from_text(text, hint=source_type)
        except llm.LLMError as e:
            raise ImportFailed(f"AI extraction failed: {e}")
        if not d:
            raise ImportFailed("That text doesn't seem to contain a recipe.")
        if title:
            d["title"] = title
        return finalize(d, source_type, enrich)
    d = textparse.parse_text(text, title=title)
    if not d["ingredients"] and not d["steps"]:
        raise ImportFailed("Couldn't find ingredients or steps. Add 'Ingredients' and 'Instructions' headings, or configure an AI model.")
    return finalize(d, source_type, enrich)


def from_images(images: list[bytes], enrich: bool = True) -> dict:
    if not llm.enabled():
        raise ImportFailed("Importing from photos needs an AI model with vision configured on the server.")
    try:
        d = llm.recipe_from_images(images)
    except llm.LLMError as e:
        raise ImportFailed(f"AI extraction failed: {e}")
    if not d:
        raise ImportFailed("Couldn't find a recipe in that photo.")
    return finalize(d, "photo", enrich)


def from_document(data: bytes, filename: str, content_type: str, enrich: bool = True) -> dict:
    kind = documents.kind_of(filename, content_type, data)
    if kind == "image":
        return from_images([data], enrich)
    if kind == "pdf":
        text = documents.pdf_text(data)
        if len(text) < 150:
            imgs = documents.pdf_images(data)
            if imgs:
                r = from_images(imgs, enrich)
                r["source_type"] = "document"
                return r
        return from_text(text, source_type="document", enrich=enrich)
    if kind == "docx":
        return from_text(documents.docx_text(data), source_type="document", enrich=enrich)
    if kind == "html":
        html = documents.plain_text(data)
        d = extract_recipe(html, "file://" + (filename or "upload.html"))
        if d:
            d["source_url"] = None
            return finalize(d, "document", enrich)
        return from_text(page_text(html), source_type="document", enrich=enrich)
    return from_text(documents.plain_text(data), source_type="document", enrich=enrich)


_STOP = {"the", "for", "make", "making", "made", "ingredients", "ingredient", "on", "day", "days", "and", "a",
         "an", "to", "of", "prepare", "preparing", "assemble", "assembly", "step", "steps", "your", "this", "it"}


def _tokens(name: str) -> set[str]:
    words = re.findall(r"[a-zà-ÿ]+", (name or "").lower())
    return {w.rstrip("s") if len(w) > 3 else w for w in words if w not in _STOP}


def components_heuristic(recipe: dict) -> list[dict]:
    """Sub-recipes from ingredient groups and step sections, when no LLM is configured.
    Groups and sections are matched by shared words ("Starter" <-> "Make the starter")."""
    comps: list[dict] = []

    def find_or_add(name: str) -> dict:
        toks = _tokens(name)
        for c in comps:
            if c["name"].lower() == name.lower() or (toks and toks & _tokens(c["name"])):
                return c
        c = {"name": name, "ingredients": [], "steps": [], "feeds_into": None}
        comps.append(c)
        return c

    loose_ings, loose_steps = [], []
    for ing in recipe.get("ingredients") or []:
        if ing.get("group"):
            find_or_add(ing["group"])["ingredients"].append(ing.get("raw"))
        else:
            loose_ings.append(ing.get("raw"))
    for st in recipe.get("steps") or []:
        if st.get("section"):
            find_or_add(st["section"])["steps"].append(st["text"])
        else:
            loose_steps.append(st["text"])

    title = recipe.get("title") or "Finished dish"
    if loose_ings or loose_steps or not comps:
        final = {"name": title, "ingredients": loose_ings, "steps": loose_steps, "feeds_into": None}
        for c in comps:
            c["feeds_into"] = title
        return comps + [final]
    # Everything is grouped: the last part (e.g. "Bread", "Assembly") is the finished dish.
    for c in comps[:-1]:
        c["feeds_into"] = comps[-1]["name"]
    return comps
