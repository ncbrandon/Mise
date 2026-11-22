from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse

from .config import get_settings
from .models import JournalEntry, Recipe, User
from .services.ingredients import convert_temperatures, render


def _iso(dt):
    return dt.isoformat() if dt else None


def user_public(u: User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "display_name": u.display_name or u.username,
        "bio": u.bio,
        "is_private": u.is_private,
    }


def user_me(u: User) -> dict:
    return {**user_public(u), "email": u.email, "is_admin": u.is_admin, "units": u.units,
            "created_at": _iso(u.created_at)}


def share_url(r: Recipe) -> str:
    return f"{get_settings().public_url.rstrip('/')}/s/{r.share_token}"


def recipe_summary(r: Recipe) -> dict:
    return {
        "id": r.id,
        "title": r.title,
        "image_url": r.image_url,
        "source_domain": (urlparse(r.source_url).hostname or "").removeprefix("www.") if r.source_url else None,
        "source_type": r.source_type,
        "categories": r.categories or [],
        "cuisine": r.cuisine,
        "total_time": r.total_time,
        "favorite": r.favorite,
        "rating": r.rating,
        "owner": r.owner.username if r.owner else None,
        "created_at": _iso(r.created_at),
        "last_cooked_at": _iso(r.last_cooked_at),
    }


def scale_factor(r: Recipe, servings: Optional[float], scale: Optional[float]) -> tuple[float, Optional[float]]:
    if scale and scale > 0:
        return scale, (r.servings * scale if r.servings else None)
    if servings and servings > 0 and r.servings:
        return servings / r.servings, servings
    return 1.0, r.servings


def recipe_full(r: Recipe, viewer: Optional[User], servings: Optional[float] = None,
                scale: Optional[float] = None, units: Optional[str] = None) -> dict:
    if units is None and viewer is not None:
        units = viewer.units
    system = units if units in ("metric", "imperial") else None
    factor, cur_servings = scale_factor(r, servings, scale)
    ings = [render(i, factor, system) for i in (r.ingredients or [])]
    steps = [{"text": convert_temperatures(s.get("text", ""), system), "section": s.get("section")}
             for s in (r.steps or [])]
    is_owner = viewer is not None and viewer.id == r.owner_id
    out = {
        **recipe_summary(r),
        "description": r.description,
        "source_url": r.source_url,
        "author": r.author,
        "servings": r.servings,
        "servings_text": r.servings_text,
        "current_servings": cur_servings,
        "scale": factor,
        "units": system or "original",
        "prep_time": r.prep_time,
        "cook_time": r.cook_time,
        "ingredients": ings,
        "steps": steps,
        "nutrition": r.nutrition,
        "components": r.components,
        "notes": r.notes if is_owner else None,
        "is_public": r.is_public,
        "is_owner": is_owner,
        "share_url": share_url(r) if is_owner or r.is_public else None,
        "collection_ids": [c.id for c in r.collections] if is_owner else [],
        "updated_at": _iso(r.updated_at),
    }
    return out


def recipe_export(r: Recipe) -> dict:
    return {
        "title": r.title, "description": r.description, "image_url": r.image_url, "source_url": r.source_url,
        "source_type": r.source_type, "author": r.author, "servings": r.servings, "servings_text": r.servings_text,
        "prep_time": r.prep_time, "cook_time": r.cook_time, "total_time": r.total_time,
        "ingredients": r.ingredients, "steps": r.steps, "categories": r.categories, "cuisine": r.cuisine,
        "nutrition": r.nutrition, "components": r.components, "notes": r.notes, "rating": r.rating,
        "favorite": r.favorite, "is_public": r.is_public, "collections": [c.name for c in r.collections],
        "created_at": _iso(r.created_at),
    }


def journal_out(e: JournalEntry) -> dict:
    return {
        "id": e.id,
        "user": user_public(e.owner) if e.owner else None,
        "recipe": recipe_summary(e.recipe) if e.recipe else None,
        "text": e.text,
        "rating": e.rating,
        "photo_url": e.photo_url,
        "is_public": e.is_public,
        "cooked_at": _iso(e.cooked_at),
    }
