from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db
from ..models import Recipe, ShoppingItem, User
from ..schemas import ShoppingFromRecipeIn, ShoppingItemIn, ShoppingItemPatch
from ..serialize import scale_factor
from ..services.ingredients import Ingredient, normalize_name, parse_ingredient
from ..services.shopping import AISLES, aisle_for, display_item, merge_into, to_base

router = APIRouter(prefix="/api/shopping", tags=["shopping"])


def _item_out(i: ShoppingItem, system: str) -> dict:
    return {"id": i.id, "name": i.name, "quantity": i.quantity, "unit": i.unit, "aisle": i.aisle,
            "checked": i.checked, "sources": i.sources or [], "display": display_item(i.name, i.quantity, i.unit, system)}


def _list(db: Session, user: User, units: Optional[str]) -> dict:
    system = units or ("metric" if user.units == "metric" else "imperial")
    items = db.scalars(select(ShoppingItem).where(ShoppingItem.owner_id == user.id)
                       .order_by(ShoppingItem.position, ShoppingItem.id)).all()
    groups = []
    for aisle in AISLES + sorted({i.aisle for i in items} - set(AISLES)):
        rows = [_item_out(i, system) for i in items if i.aisle == aisle and not i.checked]
        if rows:
            groups.append({"aisle": aisle, "items": rows})
    checked = [_item_out(i, system) for i in items if i.checked]
    return {"aisles": groups, "checked": checked, "count": sum(len(g["items"]) for g in groups)}


@router.get("")
def get_list(units: Optional[str] = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _list(db, user, units)


def _merge(db: Session, user: User, ingredients: list[Ingredient], factor: float, title: Optional[str]) -> None:
    rows = db.scalars(select(ShoppingItem).where(ShoppingItem.owner_id == user.id, ShoppingItem.checked == False)).all()  # noqa: E712
    items = [{"_row": r, "name": r.name, "key": r.key, "quantity": r.quantity, "unit": r.unit, "aisle": r.aisle,
              "checked": False, "sources": list(r.sources or [])} for r in rows]
    for ing in ingredients:
        merge_into(items, ing, factor, title)
    for it in items:
        row = it.get("_row")
        if row is None:
            db.add(ShoppingItem(owner_id=user.id, name=it["name"], key=it["key"], quantity=it["quantity"],
                                unit=it["unit"], aisle=it["aisle"], sources=it["sources"]))
        else:
            row.quantity, row.unit, row.sources = it["quantity"], it["unit"], it["sources"]
    db.commit()


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
    _merge(db, user, ings, factor, r.title)
    return _list(db, user, None)


@router.post("/items")
def add_item(body: ShoppingItemIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    lines = [l for l in body.text.splitlines() if l.strip()]
    _merge(db, user, [parse_ingredient(l) for l in lines], 1.0, None)
    return _list(db, user, None)


@router.patch("/items/{iid}")
def update_item(iid: int, body: ShoppingItemPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    it = db.get(ShoppingItem, iid)
    if not it or it.owner_id != user.id:
        raise HTTPException(404, "Item not found")
    if body.checked is not None:
        it.checked = body.checked
    if body.text is not None:
        ing = parse_ingredient(body.text)
        q, u = to_base(ing.quantity, ing.unit)
        it.name, it.key, it.quantity, it.unit = ing.name, normalize_name(ing.name), q, u
        if body.aisle is None:
            it.aisle = aisle_for(ing.name)
    if body.aisle is not None:
        it.aisle = body.aisle
    db.commit()
    return _list(db, user, None)


@router.delete("/items/{iid}")
def delete_item(iid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    it = db.get(ShoppingItem, iid)
    if not it or it.owner_id != user.id:
        raise HTTPException(404, "Item not found")
    db.delete(it)
    db.commit()
    return _list(db, user, None)


@router.post("/clear-checked")
def clear_checked(user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.execute(delete(ShoppingItem).where(ShoppingItem.owner_id == user.id, ShoppingItem.checked == True))  # noqa: E712
    db.commit()
    return _list(db, user, None)


@router.delete("")
def clear_all(user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.execute(delete(ShoppingItem).where(ShoppingItem.owner_id == user.id))
    db.commit()
    return _list(db, user, None)
