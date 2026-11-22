from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db
from ..models import Collection, Recipe, User
from ..schemas import CollectionIn

router = APIRouter(prefix="/api/collections", tags=["collections"])


def _out(c: Collection) -> dict:
    cover = next((r.image_url for r in c.recipes if r.image_url), None)
    return {"id": c.id, "name": c.name, "icon": c.icon, "count": len(c.recipes), "image_url": cover}


def _get(db: Session, cid: int, user: User) -> Collection:
    c = db.get(Collection, cid)
    if not c or c.owner_id != user.id:
        raise HTTPException(404, "Collection not found")
    return c


@router.get("")
def list_collections(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Collection).where(Collection.owner_id == user.id).order_by(Collection.name)).all()
    return [_out(c) for c in rows]


@router.post("")
def create_collection(body: CollectionIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = Collection(owner_id=user.id, name=body.name.strip(), icon=body.icon)
    db.add(c)
    db.commit()
    return _out(c)


@router.patch("/{cid}")
def rename_collection(cid: int, body: CollectionIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _get(db, cid, user)
    c.name, c.icon = body.name.strip(), body.icon
    db.commit()
    return _out(c)


@router.delete("/{cid}")
def delete_collection(cid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(_get(db, cid, user))
    db.commit()
    return {"ok": True}


@router.post("/{cid}/recipes/{rid}")
def add_recipe(cid: int, rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _get(db, cid, user)
    r = db.get(Recipe, rid)
    if not r or r.owner_id != user.id:
        raise HTTPException(404, "Recipe not found")
    if r not in c.recipes:
        c.recipes.append(r)
    db.commit()
    return _out(c)


@router.delete("/{cid}/recipes/{rid}")
def remove_recipe(cid: int, rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _get(db, cid, user)
    c.recipes = [r for r in c.recipes if r.id != rid]
    db.commit()
    return _out(c)
