"""OpenAI-compatible LLM client (works with OpenAI, OpenRouter, Ollama, LM Studio, vLLM...)."""
from __future__ import annotations

import base64
import json
import re
from typing import Any, Optional

import httpx

from ..config import get_settings
from .categorize import CATEGORIES


class LLMError(Exception):
    pass


def enabled() -> bool:
    return get_settings().llm_enabled


def _post(path: str, payload: dict) -> dict:
    s = get_settings()
    headers = {"Content-Type": "application/json"}
    if s.llm_api_key:
        headers["Authorization"] = f"Bearer {s.llm_api_key}"
    url = s.llm_base_url.rstrip("/") + path
    try:
        r = httpx.post(url, json=payload, headers=headers, timeout=s.llm_timeout)
    except httpx.HTTPError as e:
        raise LLMError(f"LLM request failed: {e}") from e
    if r.status_code >= 400:
        raise LLMError(f"LLM error {r.status_code}: {r.text[:300]}")
    return r.json()


def _parse_json(text: str) -> Any:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    raise LLMError("Model did not return valid JSON")


def chat_json(system: str, user: Any, vision: bool = False) -> dict:
    s = get_settings()
    model = (s.llm_vision_model or s.llm_model) if vision else s.llm_model
    payload = {
        "model": model,
        "temperature": 0.2,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {"type": "json_object"},
    }
    try:
        data = _post("/chat/completions", payload)
    except LLMError as e:
        # some local servers reject response_format; retry without it
        if "response_format" in str(e) or "400" in str(e):
            payload.pop("response_format")
            data = _post("/chat/completions", payload)
        else:
            raise
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise LLMError("Unexpected LLM response")
    if isinstance(content, list):
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return _parse_json(content or "")


RECIPE_SCHEMA = """{
  "found": true,
  "title": string,
  "description": string | null,       // one or two sentences
  "servings": number | null,
  "servings_text": string | null,     // e.g. "4 servings", "12 cookies"
  "prep_time": integer | null,        // minutes
  "cook_time": integer | null,        // minutes
  "total_time": integer | null,       // minutes
  "ingredients": [ { "text": string, "group": string | null } ],  // "2 cups flour" - keep quantities & units
  "steps": [ { "text": string, "section": string | null } ],
  "cuisine": string | null,
  "notes": string | null
}"""

RECIPE_SYSTEM = f"""You turn messy cooking content (web pages, video captions and transcripts, social captions,
photos of cookbooks or handwritten cards, documents) into a clean recipe.
Reply with JSON only, in exactly this shape:
{RECIPE_SCHEMA}
Rules:
- Each ingredient is one line starting with its quantity and unit when known ("1 1/2 cups flour, sifted").
- If the source mentions an ingredient without an amount, keep it without inventing one.
- Use "group" for ingredient sections such as "Dough" or "Sauce"; otherwise null.
- Steps are short, clear and imperative. Keep every temperature, time and quantity. Drop chatter, ads,
  life stories, sponsor messages and calls to like/subscribe.
- Write in the same language as the source.
- If there is no recipe in the content, reply {{"found": false}}."""


def recipe_from_text(text: str, hint: str = "") -> Optional[dict]:
    user = (f"Source: {hint}\n\n" if hint else "") + text[:24000]
    out = chat_json(RECIPE_SYSTEM, user)
    return _normalize_recipe(out)


def recipe_from_images(images: list[bytes], hint: str = "") -> Optional[dict]:
    parts: list[dict] = [{"type": "text", "text": hint or "Extract the recipe from these images."}]
    for img in images[:6]:
        b64 = base64.b64encode(img).decode()
        mime = "image/png" if img[:4] == b"\x89PNG" else "image/jpeg"
        parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
    out = chat_json(RECIPE_SYSTEM, parts, vision=True)
    return _normalize_recipe(out)


def _normalize_recipe(out: dict) -> Optional[dict]:
    if not isinstance(out, dict) or out.get("found") is False:
        return None
    ings = []
    for i in out.get("ingredients") or []:
        if isinstance(i, str):
            ings.append({"text": i, "group": None})
        elif isinstance(i, dict) and (i.get("text") or i.get("raw")):
            ings.append({"text": i.get("text") or i.get("raw"), "group": i.get("group")})
    steps = []
    for s in out.get("steps") or []:
        if isinstance(s, str):
            steps.append({"text": s, "section": None})
        elif isinstance(s, dict) and s.get("text"):
            steps.append({"text": s["text"], "section": s.get("section")})
    if not ings and not steps:
        return None

    def _int(v):
        try:
            return int(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None

    def _float(v):
        try:
            return float(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None

    return {
        "title": out.get("title") or "Untitled recipe",
        "description": out.get("description"),
        "servings": _float(out.get("servings")),
        "servings_text": out.get("servings_text"),
        "prep_time": _int(out.get("prep_time")),
        "cook_time": _int(out.get("cook_time")),
        "total_time": _int(out.get("total_time")),
        "ingredients": ings,
        "steps": steps,
        "cuisine": out.get("cuisine"),
        "notes": out.get("notes"),
    }


def _recipe_brief(r: dict) -> str:
    ings = "\n".join(f"- {i}" for i in r.get("ingredients_text", []))
    steps = "\n".join(f"{n + 1}. {s}" for n, s in enumerate(r.get("steps_text", [])))
    return f"Title: {r.get('title')}\nServings: {r.get('servings') or 'unknown'}\n\nIngredients:\n{ings}\n\nSteps:\n{steps}"


def categorize(r: dict) -> dict:
    system = ("Classify the recipe. Reply JSON: {\"categories\": [..], \"cuisine\": string|null}. "
              f"Pick 1-5 categories ONLY from this list: {json.dumps(CATEGORIES)}.")
    out = chat_json(system, _recipe_brief(r))
    cats = [c for c in out.get("categories", []) if c in CATEGORIES]
    return {"categories": cats, "cuisine": out.get("cuisine")}


def nutrition(r: dict) -> dict:
    system = ("Estimate nutrition PER SERVING for the recipe using standard nutrition databases. "
              "If servings is unknown, assume a sensible number and say so in 'assumed_servings'. Reply JSON: "
              '{"calories": n, "protein_g": n, "carbs_g": n, "fat_g": n, "saturated_fat_g": n, "fiber_g": n, '
              '"sugar_g": n, "sodium_mg": n, "assumed_servings": n|null}. Numbers only, no units.')
    out = chat_json(system, _recipe_brief(r))
    clean: dict[str, Any] = {}
    for k in ("calories", "protein_g", "carbs_g", "fat_g", "saturated_fat_g", "fiber_g", "sugar_g", "sodium_mg", "assumed_servings"):
        try:
            if out.get(k) is not None:
                clean[k] = round(float(out[k]), 1)
        except (TypeError, ValueError):
            pass
    clean["per"] = "serving"
    clean["source"] = "estimated"
    return clean


def breakdown(r: dict) -> list[dict]:
    system = ("Break the recipe into its sub-recipes (components that are prepared separately, e.g. "
              "'Pizza dough', 'Tomato sauce', then the final assembly). Reply JSON: "
              '{"components": [{"name": str, "ingredients": [str], "steps": [str], "feeds_into": str|null}]}. '
              "Use ingredient lines exactly as given. The final component (the finished dish) has feeds_into null; "
              "every other component's feeds_into names the component it goes into. Keep steps short. "
              "A simple one-pot recipe may have just 1-2 components.")
    out = chat_json(system, _recipe_brief(r))
    comps = []
    for c in out.get("components") or []:
        if isinstance(c, dict) and c.get("name"):
            comps.append({
                "name": str(c["name"]),
                "ingredients": [str(x) for x in c.get("ingredients") or []],
                "steps": [str(x) for x in c.get("steps") or []],
                "feeds_into": c.get("feeds_into") or None,
            })
    return comps


def transcribe(path: str) -> Optional[str]:
    s = get_settings()
    if not s.transcribe_model:
        return None
    base = (s.transcribe_base_url or s.llm_base_url).rstrip("/")
    key = s.transcribe_api_key or s.llm_api_key
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    with open(path, "rb") as f:
        r = httpx.post(f"{base}/audio/transcriptions", headers=headers,
                       data={"model": s.transcribe_model}, files={"file": (path.rsplit("/", 1)[-1], f)},
                       timeout=300)
    if r.status_code >= 400:
        raise LLMError(f"Transcription failed {r.status_code}: {r.text[:200]}")
    return r.json().get("text")
