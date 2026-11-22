"""Cooking journal, public profiles, follows and the friends feed."""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db
from ..models import Follow, JournalEntry, Recipe, User, now
from ..schemas import JournalIn
from ..serialize import journal_out, recipe_summary, user_public
from .recipes import save_upload

router = APIRouter(prefix="/api", tags=["social"])


# --- media -----------------------------------------------------------------
@router.post("/media")
async def upload_media(file: UploadFile = File(...), user: User = Depends(current_user)):
    return {"url": await save_upload(file)}


# --- journal ---------------------------------------------------------------
@router.get("/journal")
def my_journal(recipe_id: int | None = None, limit: int = 100, user: User = Depends(current_user),
               db: Session = Depends(get_db)):
    stmt = select(JournalEntry).where(JournalEntry.owner_id == user.id)
    if recipe_id:
        stmt = stmt.where(JournalEntry.recipe_id == recipe_id)
    rows = db.scalars(stmt.order_by(JournalEntry.cooked_at.desc()).limit(limit)).unique().all()
    return [journal_out(e) for e in rows]


@router.post("/journal")
def add_entry(body: JournalIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    recipe = None
    if body.recipe_id:
        recipe = db.get(Recipe, body.recipe_id)
        if not recipe or recipe.owner_id != user.id:
            raise HTTPException(404, "Recipe not found")
    e = JournalEntry(owner_id=user.id, recipe_id=body.recipe_id, text=body.text, rating=body.rating,
                     photo_url=body.photo_url, is_public=body.is_public, cooked_at=body.cooked_at or now())
    db.add(e)
    if recipe:
        recipe.last_cooked_at = e.cooked_at
        if body.rating:
            recipe.rating = body.rating
    db.commit()
    db.refresh(e)
    return journal_out(e)


@router.patch("/journal/{eid}")
def edit_entry(eid: int, body: JournalIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = db.get(JournalEntry, eid)
    if not e or e.owner_id != user.id:
        raise HTTPException(404, "Entry not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(e, k, v)
    db.commit()
    return journal_out(e)


@router.delete("/journal/{eid}")
def delete_entry(eid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = db.get(JournalEntry, eid)
    if not e or e.owner_id != user.id:
        raise HTTPException(404, "Entry not found")
    db.delete(e)
    db.commit()
    return {"ok": True}


# --- people ----------------------------------------------------------------
def _following_ids(db: Session, user: User) -> set[int]:
    return set(db.scalars(select(Follow.followee_id).where(Follow.follower_id == user.id)))


@router.get("/users")
def search_users(q: str = "", user: User = Depends(current_user), db: Session = Depends(get_db)):
    like = f"%{q.strip().lower()}%"
    rows = db.scalars(select(User).where(or_(func.lower(User.username).like(like),
                                              func.lower(User.display_name).like(like)))
                      .order_by(User.username).limit(50)).all()
    following = _following_ids(db, user)
    return [{**user_public(u), "following": u.id in following} for u in rows if u.id != user.id]


@router.get("/users/{username}")
def profile(username: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    u = db.scalar(select(User).where(func.lower(User.username) == username.lower()))
    if not u:
        raise HTTPException(404, "User not found")
    is_self = u.id == user.id
    base = {
        **user_public(u),
        "following": u.id in _following_ids(db, user),
        "followers": db.scalar(select(func.count(Follow.id)).where(Follow.followee_id == u.id)),
        "following_count": db.scalar(select(func.count(Follow.id)).where(Follow.follower_id == u.id)),
        "recipe_count": db.scalar(select(func.count(Recipe.id)).where(Recipe.owner_id == u.id)),
    }
    if u.is_private and not is_self:
        return {**base, "recipes": [], "journal": [], "hidden": True}
    rstmt = select(Recipe).where(Recipe.owner_id == u.id)
    jstmt = select(JournalEntry).where(JournalEntry.owner_id == u.id)
    if not is_self:
        rstmt = rstmt.where(Recipe.is_public == True)  # noqa: E712
        jstmt = jstmt.where(JournalEntry.is_public == True)  # noqa: E712
    recipes = db.scalars(rstmt.order_by(Recipe.created_at.desc()).limit(60)).unique().all()
    journal = db.scalars(jstmt.order_by(JournalEntry.cooked_at.desc()).limit(30)).unique().all()
    return {**base, "recipes": [recipe_summary(r) for r in recipes], "journal": [journal_out(e) for e in journal],
            "hidden": False}


@router.post("/users/{username}/follow")
def follow(username: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    u = db.scalar(select(User).where(func.lower(User.username) == username.lower()))
    if not u or u.id == user.id:
        raise HTTPException(404, "User not found")
    if not db.scalar(select(Follow).where(Follow.follower_id == user.id, Follow.followee_id == u.id)):
        db.add(Follow(follower_id=user.id, followee_id=u.id))
        db.commit()
    return {"following": True}


@router.delete("/users/{username}/follow")
def unfollow(username: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    u = db.scalar(select(User).where(func.lower(User.username) == username.lower()))
    if u:
        f = db.scalar(select(Follow).where(Follow.follower_id == user.id, Follow.followee_id == u.id))
        if f:
            db.delete(f)
            db.commit()
    return {"following": False}


@router.get("/feed")
def feed(limit: int = 60, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """What friends are cooking: public journal entries and newly saved public recipes."""
    ids = _following_ids(db, user)
    if not ids:
        return {"items": []}
    visible = select(User.id).where(User.id.in_(ids), User.is_private == False)  # noqa: E712
    entries = db.scalars(select(JournalEntry).where(JournalEntry.owner_id.in_(visible), JournalEntry.is_public == True)  # noqa: E712
                         .order_by(JournalEntry.cooked_at.desc()).limit(limit)).unique().all()
    recipes = db.scalars(select(Recipe).where(Recipe.owner_id.in_(visible), Recipe.is_public == True)  # noqa: E712
                         .order_by(Recipe.created_at.desc()).limit(limit)).unique().all()
    items = [{"type": "cooked", "at": e.cooked_at.isoformat(), "entry": journal_out(e)} for e in entries] + \
            [{"type": "saved", "at": r.created_at.isoformat(), "recipe": recipe_summary(r),
              "user": user_public(r.owner)} for r in recipes]
    items.sort(key=lambda x: x["at"], reverse=True)
    return {"items": items[:limit]}
