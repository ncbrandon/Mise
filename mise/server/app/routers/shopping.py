from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db
from ..models import Recipe, ShoppingItem, User
from ..schemas import ShoppingFromRecipeIn, ShoppingItemIn, ShoppingItemPatch
from ..serialize import scale_factor
from ..services import homeassistant as ha
from ..services.ingredients import Ingredient, normalize_name, parse_ingredient
from ..services.shopping import AISLES, aisle_for, display_item, merge_into, to_base

router = APIRouter(prefix="/api/shopping", tags=["shopping"])


def _system(user: User, units: Optional[str] = None) -> str:
    return units or ("metric" if user.units == "metric" else "imperial")


def _text(row: ShoppingItem, system: str) -> str:
    return display_item(row.name, row.quantity, row.unit, system)


def _item_out(i: ShoppingItem, system: str) -> dict:
    return {"id": i.id, "name": i.name, "quantity": i.quantity, "unit": i.unit, "aisle": i.aisle,
            "checked": i.checked, "sources": i.sources or [], "display": _text(i, system),
            "synced": bool(i.ha_uid)}


def _list(db: Session, user: User, units: Optional[str], ha_error: Optional[str] = None) -> dict:
    system = _system(user, units)
    items = db.scalars(select(ShoppingItem).where(ShoppingItem.owner_id == user.id)
                       .order_by(ShoppingItem.position, ShoppingItem.id)).all()
    groups = []
    for aisle in AISLES + sorted({i.aisle for i in items} - set(AISLES)):
        rows = [_item_out(i, system) for i in items if i.aisle == aisle and not i.checked]
        if rows:
            groups.append({"aisle": aisle, "items": rows})
    checked = [_item_out(i, system) for i in items if i.checked]
    return {"aisles": groups, "checked": checked, "count": sum(len(g["items"]) for g in groups),
            "home_assistant": {"enabled": ha.enabled(), "entity": ha._entity() if ha.enabled() else None,
                               "error": ha_error}}


def _pull_from_ha(db: Session, user: User) -> Optional[str]:
    """Apply changes made in Home Assistant: checked off there -> checked here; removed there -> removed here."""
    rows = db.scalars(select(ShoppingItem).where(ShoppingItem.owner_id == user.id, ShoppingItem.ha_uid.is_not(None))).all()
    if not rows:
        return None
    items, err = ha.pull()
    if items is None:
        return err
    by_text = {}
    for uid, it in items.items():
        by_text.setdefault(it["summary"], uid)
    for row in rows:
        it = items.get(row.ha_uid)
        if it is None and row.ha_uid in by_text:  # identified by text: upgrade to the real id
            row.ha_uid = by_text[row.ha_uid]
            it = items[row.ha_uid]
        if it is None:
            db.delete(row)  # removed in Home Assistant
        else:
            row.checked = it["status"] == "completed"
    db.commit()
    return None


def _push_unsynced(db: Session, user: User) -> Optional[str]:
    """Send items that never made it to Home Assistant (e.g. added while it was offline)."""
    rows = db.scalars(select(ShoppingItem).where(ShoppingItem.owner_id == user.id, ShoppingItem.ha_uid.is_(None),
                                                 ShoppingItem.checked == False)).all()  # noqa: E712
    if not rows:
        return None
    system = _system(user)
    err = ha.push(list(rows), lambda r: _text(r, system))
    db.commit()
    return err


@router.get("")
def get_list(units: Optional[str] = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    err = None
    if ha.enabled():
        err = _pull_from_ha(db, user) or _push_unsynced(db, user)
    return _list(db, user, units, err)


def _merge(db: Session, user: User, ingredients: list[Ingredient], factor: float, title: Optional[str]) -> Optional[str]:
    rows = db.scalars(select(ShoppingItem).where(ShoppingItem.owner_id == user.id, ShoppingItem.checked == False)).all()  # noqa: E712
    items = [{"_row": r, "_before": (r.quantity, r.unit), "name": r.name, "key": r.key, "quantity": r.quantity,
              "unit": r.unit, "aisle": r.aisle, "checked": False, "sources": list(r.sources or [])} for r in rows]
    for ing in ingredients:
        merge_into(items, ing, factor, title)
    changed: list[ShoppingItem] = []
    for it in items:
        row = it.get("_row")
        if row is None:
            row = ShoppingItem(owner_id=user.id, name=it["name"], key=it["key"], quantity=it["quantity"],
                               unit=it["unit"], aisle=it["aisle"], sources=it["sources"])
            db.add(row)
            changed.append(row)
        else:
            if (it["quantity"], it["unit"]) != it["_before"]:
                changed.append(row)
            row.quantity, row.unit, row.sources = it["quantity"], it["unit"], it["sources"]
    db.flush()
    system = _system(user)
    err = ha.push(changed, lambda r: _text(r, system))
    db.commit()
    return err


@router.post("/recipe")
def add_recipe(body: ShoppingFromRecipeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = db.get(Recipe, body.recipe_id)
    if not r or r.owner_id != user.id:
        raise HTTPException(404, "Recipe not found")
    factor, _ = scale_factor(r, body.servings, body.scale)
    ings = [Ingredient.from_dict(i) for i in r.ingredients or []]
    if body.ingredient_indexes is not None:
        wanted = set(body.ingredient_indexes)
        ings = [i for n, i in enumerate(ings) if n in wanted]
    err = _merge(db, user, ings, factor, r.title)
    return _list(db, user, None, err)


@router.post("/items")
def add_item(body: ShoppingItemIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    lines = [l for l in body.text.splitlines() if l.strip()]
    err = _merge(db, user, [parse_ingredient(l) for l in lines], 1.0, None)
    return _list(db, user, None, err)


def _own_item(db: Session, iid: int, user: User) -> ShoppingItem:
    it = db.get(ShoppingItem, iid)
    if not it or it.owner_id != user.id:
        raise HTTPException(404, "Item not found")
    return it


@router.patch("/items/{iid}")
def update_item(iid: int, body: ShoppingItemPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    it = _own_item(db, iid, user)
    err = None
    if body.checked is not None and body.checked != it.checked:
        it.checked = body.checked
        err = ha.set_done(it.ha_uid, body.checked)
    if body.text is not None:
        ing = parse_ingredient(body.text)
        q, u = to_base(ing.quantity, ing.unit)
        it.name, it.key, it.quantity, it.unit = ing.name, normalize_name(ing.name), q, u
        if body.aisle is None:
            it.aisle = aisle_for(ing.name)
        err = ha.rename(it.ha_uid, _text(it, _system(user))) or err
    if body.aisle is not None:
        it.aisle = body.aisle
    db.commit()
    return _list(db, user, None, err)


@router.delete("/items/{iid}")
def delete_item(iid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    it = _own_item(db, iid, user)
    err = ha.remove([it.ha_uid])
    db.delete(it)
    db.commit()
    return _list(db, user, None, err)


@router.post("/clear-checked")
def clear_checked(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(ShoppingItem).where(ShoppingItem.owner_id == user.id, ShoppingItem.checked == True)).all()  # noqa: E712
    err = ha.remove([r.ha_uid for r in rows])
    for r in rows:
        db.delete(r)
    db.commit()
    return _list(db, user, None, err)


@router.delete("")
def clear_all(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(ShoppingItem).where(ShoppingItem.owner_id == user.id)).all()
    err = ha.remove([r.ha_uid for r in rows])
    for r in rows:
        db.delete(r)
    db.commit()
    return _list(db, user, None, err)


@router.post("/home-assistant/test")
def test_home_assistant(user: User = Depends(current_user)):
    """Check the connection settings from the Settings page."""
    if not ha.enabled():
        return {"ok": False, "message": "Home Assistant isn't configured on the server."}
    items, err = ha.pull()
    if items is None:
        return {"ok": False, "message": err}
    return {"ok": True, "message": f"Connected to {ha._entity()} ({len(items)} items on the list)."}
