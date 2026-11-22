import os
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import String, cast, or_, select, text
from sqlalchemy.orm import Session

from ..auth import current_user, optional_user
from ..config import get_settings
from ..db import get_db
from ..models import Collection, Recipe, User
from ..schemas import RecipeIn, RecipePatch
from ..serialize import recipe_full, recipe_summary
from ..services import llm
from ..services.categorize import CATEGORIES
from ..services.importer import auto_categories, brief, components_heuristic, finalize

router = APIRouter(prefix="/api/recipes", tags=["recipes"])


def can_view(r: Recipe, viewer: Optional[User]) -> bool:
    if viewer and viewer.id == r.owner_id:
        return True
    return r.is_public and not r.owner.is_private


def get_owned(db: Session, rid: int, user: User) -> Recipe:
    r = db.get(Recipe, rid)
    if not r or r.owner_id != user.id:
        raise HTTPException(404, "Recipe not found")
    return r


def save_draft(db: Session, user: User, draft: dict) -> Recipe:
    fields = {k: v for k, v in draft.items() if k in Recipe.__table__.columns.keys() and k not in ("id", "owner_id")}
    r = Recipe(owner_id=user.id, is_public=not user.is_private, **fields)
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


@router.get("")
def list_recipes(q: Optional[str] = None, category: Optional[str] = None, collection_id: Optional[int] = None,
                 favorite: Optional[bool] = None, sort: str = "recent", limit: int = Query(200, le=1000),
                 offset: int = 0, user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(Recipe).where(Recipe.owner_id == user.id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Recipe.title.ilike(like), cast(Recipe.ingredients, String).ilike(like),
                              Recipe.cuisine.ilike(like), Recipe.notes.ilike(like)))
    if category:
        stmt = stmt.where(Recipe.categories.contains([category]))
    if collection_id:
        stmt = stmt.where(Recipe.collections.any(Collection.id == collection_id))
    if favorite is not None:
        stmt = stmt.where(Recipe.favorite == favorite)
    order = {
        "title": Recipe.title.asc(),
        "cooked": Recipe.last_cooked_at.desc().nulls_last(),
        "rating": Recipe.rating.desc().nulls_last(),
        "time": Recipe.total_time.asc().nulls_last(),
    }.get(sort, Recipe.created_at.desc())
    rows = db.scalars(stmt.order_by(order).limit(limit).offset(offset)).unique().all()
    return [recipe_summary(r) for r in rows]


@router.get("/categories")
def categories(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Automatic collections: category -> count, plus a cover image."""
    rows = db.execute(text(
        "SELECT c, count(*), max(r.image_url) FROM recipes r "
        "CROSS JOIN LATERAL jsonb_array_elements_text(r.categories) AS c "
        "WHERE r.owner_id = :uid AND jsonb_typeof(r.categories) = 'array' GROUP BY c"
    ), {"uid": user.id}).all()
    found = {c: (n, img) for c, n, img in rows}
    ordered = [c for c in CATEGORIES if c in found] + sorted(c for c in found if c not in CATEGORIES)
    return [{"name": c, "count": found[c][0], "image_url": found[c][1]} for c in ordered]


@router.post("")
def create_recipe(body: RecipeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    draft = body.model_dump()
    draft["ingredients"] = [{"text": i.raw, "group": i.group} for i in body.ingredients]
    draft["steps"] = [s.model_dump() for s in body.steps]
    data = finalize(draft, "manual", enrich=body.categories is None)
    if body.categories is not None:
        data["categories"] = body.categories
    data.update(rating=body.rating, favorite=body.favorite)
    r = save_draft(db, user, data)
    r.is_public = body.is_public
    db.commit()
    return recipe_full(r, user)


@router.get("/shared/{token}")
def get_shared(token: str, servings: Optional[float] = None, scale: Optional[float] = None,
               units: Optional[str] = None, viewer: Optional[User] = Depends(optional_user),
               db: Session = Depends(get_db)):
    """Open a share link inside the app (the token itself grants read access)."""
    r = db.scalar(select(Recipe).where(Recipe.share_token == token))
    if not r:
        raise HTTPException(404, "Recipe not found")
    return recipe_full(r, viewer, servings, scale, units)


@router.get("/{rid}")
def get_recipe(rid: int, servings: Optional[float] = None, scale: Optional[float] = None,
               units: Optional[str] = None, viewer: Optional[User] = Depends(optional_user),
               db: Session = Depends(get_db)):
    r = db.get(Recipe, rid)
    if not r or not can_view(r, viewer):
        raise HTTPException(404, "Recipe not found")
    return recipe_full(r, viewer, servings, scale, units)


@router.put("/{rid}")
def update_recipe(rid: int, body: RecipeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = get_owned(db, rid, user)
    draft = body.model_dump()
    draft["ingredients"] = [{"text": i.raw, "group": i.group} for i in body.ingredients]
    draft["steps"] = [s.model_dump() for s in body.steps]
    data = finalize(draft, r.source_type, enrich=False)
    for k in ("title", "description", "image_url", "source_url", "author", "servings", "servings_text",
              "prep_time", "cook_time", "total_time", "ingredients", "steps", "cuisine", "notes"):
        setattr(r, k, data[k])
    if body.categories is not None:
        r.categories = body.categories
    r.rating, r.favorite, r.is_public = body.rating, body.favorite, body.is_public
    r.components = None  # ingredients changed: breakdown is stale
    db.commit()
    return recipe_full(r, user)


@router.patch("/{rid}")
def patch_recipe(rid: int, body: RecipePatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = get_owned(db, rid, user)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(r, k, v)
    db.commit()
    return recipe_full(r, user)


@router.delete("/{rid}")
def delete_recipe(rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = get_owned(db, rid, user)
    db.delete(r)
    db.commit()
    return {"ok": True}


@router.post("/{rid}/copy")
def copy_recipe(rid: int, share: Optional[str] = None, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    src = db.get(Recipe, rid)
    if not src or not (can_view(src, user) or (share and share == src.share_token)):
        raise HTTPException(404, "Recipe not found")
    if src.owner_id == user.id:
        return recipe_full(src, user)
    cols = [c for c in Recipe.__table__.columns.keys()
            if c not in ("id", "owner_id", "share_token", "created_at", "updated_at", "favorite", "rating",
                         "notes", "last_cooked_at", "copied_from_id", "is_public")]
    r = Recipe(owner_id=user.id, copied_from_id=src.id, is_public=not user.is_private,
               **{c: getattr(src, c) for c in cols})
    db.add(r)
    db.commit()
    return recipe_full(r, user)


@router.post("/{rid}/nutrition")
def compute_nutrition(rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = get_owned(db, rid, user)
    if not llm.enabled():
        raise HTTPException(400, "Nutrition estimates need an AI model configured on the server")
    try:
        r.nutrition = llm.nutrition(brief(recipe_dict(r)))
    except llm.LLMError as e:
        raise HTTPException(502, str(e))
    db.commit()
    return recipe_full(r, user)


@router.post("/{rid}/breakdown")
def compute_breakdown(rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = get_owned(db, rid, user)
    d = recipe_dict(r)
    comps = None
    if llm.enabled():
        try:
            comps = llm.breakdown(brief(d))
        except llm.LLMError:
            comps = None
    r.components = comps or components_heuristic(d)
    db.commit()
    return recipe_full(r, user)


@router.post("/{rid}/recategorize")
def recategorize(rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = get_owned(db, rid, user)
    d = recipe_dict(r)
    r.categories = auto_categories(d, [])
    if d.get("cuisine") and not r.cuisine:
        r.cuisine = d["cuisine"]
    db.commit()
    return recipe_full(r, user)


@router.post("/{rid}/image")
async def upload_image(rid: int, file: UploadFile = File(...), user: User = Depends(current_user),
                       db: Session = Depends(get_db)):
    r = get_owned(db, rid, user)
    r.image_url = await save_upload(file)
    db.commit()
    return recipe_full(r, user)


def recipe_dict(r: Recipe) -> dict:
    return {"title": r.title, "servings": r.servings, "ingredients": r.ingredients or [],
            "steps": r.steps or [], "total_time": r.total_time, "cuisine": r.cuisine}


ALLOWED_IMAGE = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/heic": ".heic"}


async def save_upload(file: UploadFile, max_mb: int = 15) -> str:
    ext = ALLOWED_IMAGE.get((file.content_type or "").lower())
    if not ext:
        raise HTTPException(400, "Upload a JPEG, PNG, WebP or HEIC image")
    data = await file.read()
    if len(data) > max_mb * 1024 * 1024:
        raise HTTPException(413, "Image is too large")
    s = get_settings()
    os.makedirs(s.media_dir, exist_ok=True)
    name = f"{uuid.uuid4().hex}{ext}"
    with open(os.path.join(s.media_dir, name), "wb") as f:
        f.write(data)
    return f"{s.public_url.rstrip('/')}/media/{name}"
