"""Public HTML pages: share links (/s/<token>) and the cooked.wiki-style reader (/https://any-site/recipe)."""
import re
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session
import os

from ..config import get_settings
from ..db import get_db
from ..models import Recipe
from ..services.importer import ImportFailed, from_url
from ..services.ingredients import convert_temperatures, render

router = APIRouter(tags=["web"])
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates"))


def _view(recipe: dict, units: str | None, servings: float | None) -> dict:
    system = units if units in ("metric", "imperial") else None
    factor = 1.0
    if servings and recipe.get("servings"):
        factor = servings / recipe["servings"]
    return {
        **recipe,
        "ingredients_view": [render(i, factor, system) for i in recipe.get("ingredients") or []],
        "steps_view": [{**s, "text": convert_temperatures(s["text"], system)} for s in recipe.get("steps") or []],
        "cur_servings": (recipe["servings"] * factor) if recipe.get("servings") else None,
        "units": system or "original",
    }


STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")


@router.get("/", include_in_schema=False)
def web_app():
    """The desktop/web version of Mise (single page app; talks to the same /api)."""
    return FileResponse(os.path.join(STATIC_DIR, "index.html"), headers={"Cache-Control": "no-cache"})


@router.get("/s/{token}", response_class=HTMLResponse)
def shared(token: str, request: Request, units: str | None = None, servings: float | None = None,
           db: Session = Depends(get_db)):
    r = db.scalar(select(Recipe).where(Recipe.share_token == token))
    if not r:
        raise HTTPException(404, "Recipe not found")
    data = {c: getattr(r, c) for c in ("title", "description", "image_url", "source_url", "servings", "servings_text",
                                       "prep_time", "cook_time", "total_time", "ingredients", "steps", "nutrition",
                                       "author", "cuisine")}
    data["by"] = r.owner.display_name or r.owner.username
    return templates.TemplateResponse(request, "recipe.html", {
        "r": _view(data, units, servings),
        "open_in_app": f"mise://recipe?share={token}",
        "self_url": str(request.url).split("?")[0],
    })


@router.get("/{target:path}", response_class=HTMLResponse)
def reader(target: str, request: Request, units: str | None = None, servings: float | None = None):
    if not re.match(r"^https?:/", target):
        raise HTTPException(404, "Not found")
    if not get_settings().public_reader:
        raise HTTPException(404, "The public reader is disabled on this server")
    url = re.sub(r"^(https?):/+", r"\1://", target)
    extra = [(k, v) for k, v in request.query_params.multi_items() if k not in ("units", "servings")]
    if extra:
        url += "?" + "&".join(f"{k}={quote(v)}" for k, v in extra)
    try:
        recipe = from_url(url, enrich=False)
    except ImportFailed as e:
        return templates.TemplateResponse(request, "error.html", {"message": str(e), "url": url}, status_code=422)
    return templates.TemplateResponse(request, "recipe.html", {
        "r": _view(recipe, units, servings),
        "open_in_app": f"mise://import?url={quote(url, safe='')}",
        "self_url": str(request.url).split("?")[0],
    })
