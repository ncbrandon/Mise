from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db
from ..models import Collection, Recipe, User
from ..schemas import ImportTextIn, ImportURLIn
from ..serialize import recipe_full
from ..services import importer
from ..services.importer import ImportFailed
from .recipes import save_draft

router = APIRouter(prefix="/api/import", tags=["import"])

MAX_UPLOAD = 25 * 1024 * 1024


def _respond(db: Session, user: User, draft: dict, save: bool) -> dict:
    if not save:
        return {"saved": False, "draft": draft}
    r = save_draft(db, user, draft)
    return {"saved": True, "duplicate": False, "recipe": recipe_full(r, user)}


@router.post("/url")
def import_url(body: ImportURLIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    url = body.url.strip()
    existing = db.scalar(select(Recipe).where(Recipe.owner_id == user.id, Recipe.source_url == url))
    if existing and body.save:
        return {"saved": True, "duplicate": True, "recipe": recipe_full(existing, user)}
    try:
        draft = importer.from_url(url)
    except ImportFailed as e:
        raise HTTPException(422, str(e))
    if body.save and draft.get("source_url") and draft["source_url"] != url:
        dup = db.scalar(select(Recipe).where(Recipe.owner_id == user.id, Recipe.source_url == draft["source_url"]))
        if dup:
            return {"saved": True, "duplicate": True, "recipe": recipe_full(dup, user)}
    return _respond(db, user, draft, body.save)


@router.post("/text")
def import_text(body: ImportTextIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        draft = importer.from_text(body.text, body.title, source_type=body.source_type)
    except ImportFailed as e:
        raise HTTPException(422, str(e))
    return _respond(db, user, draft, body.save)


@router.post("/photos")
async def import_photos(files: list[UploadFile] = File(...), user: User = Depends(current_user),
                        db: Session = Depends(get_db)):
    images = []
    for f in files[:6]:
        data = await f.read()
        if len(data) > MAX_UPLOAD:
            raise HTTPException(413, "Photo is too large")
        images.append(data)
    if not images:
        raise HTTPException(400, "No photos uploaded")
    try:
        draft = importer.from_images(images)
    except ImportFailed as e:
        raise HTTPException(422, str(e))
    return _respond(db, user, draft, True)


@router.post("/document")
async def import_document(file: UploadFile = File(...), user: User = Depends(current_user),
                          db: Session = Depends(get_db)):
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "File is too large")
    try:
        draft = importer.from_document(data, file.filename or "", file.content_type or "")
    except ImportFailed as e:
        raise HTTPException(422, str(e))
    return _respond(db, user, draft, True)


@router.post("/backup")
async def import_backup(file: UploadFile = File(...), user: User = Depends(current_user),
                        db: Session = Depends(get_db)):
    """Restore a Mise export (export.json)."""
    import json
    try:
        data = json.loads(await file.read())
    except ValueError:
        raise HTTPException(400, "Not a valid export file")
    recipes = data.get("recipes") if isinstance(data, dict) else data
    if not isinstance(recipes, list):
        raise HTTPException(400, "Not a valid export file")
    collections = {c.name: c for c in db.scalars(select(Collection).where(Collection.owner_id == user.id))}
    cols = set(Recipe.__table__.columns.keys()) - {"id", "owner_id", "share_token", "created_at", "updated_at",
                                                   "copied_from_id", "last_cooked_at"}
    count = 0
    for item in recipes:
        if not isinstance(item, dict) or not item.get("title"):
            continue
        r = Recipe(owner_id=user.id, **{k: v for k, v in item.items() if k in cols})
        for name in item.get("collections") or []:
            if name not in collections:
                collections[name] = Collection(owner_id=user.id, name=name)
                db.add(collections[name])
            r.collections.append(collections[name])
        db.add(r)
        count += 1
    db.commit()
    return {"imported": count}
