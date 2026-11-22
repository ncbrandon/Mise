from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import current_user, hash_password, make_token, verify_password
from ..config import get_settings
from ..db import get_db
from ..models import User
from ..schemas import LoginIn, PasswordChange, RegisterIn, UserPatch
from ..serialize import user_me

router = APIRouter(prefix="/api", tags=["account"])

VERSION = "1.0.0"


@router.get("/server")
def server_info(db: Session = Depends(get_db)):
    s = get_settings()
    has_users = db.scalar(select(func.count(User.id))) > 0
    return {
        "name": "Mise",
        "version": VERSION,
        "registration_open": s.allow_registration or not has_users,
        "ai": s.llm_enabled,
        "transcription": bool(s.transcribe_model) and s.llm_enabled,
        "public_url": s.public_url,
        "home_assistant": bool(s.home_assistant_url and s.home_assistant_token),
    }


@router.post("/auth/register")
def register(body: RegisterIn, db: Session = Depends(get_db)):
    s = get_settings()
    is_first = db.scalar(select(func.count(User.id))) == 0
    if not s.allow_registration and not is_first:
        raise HTTPException(403, "Registration is closed on this server")
    uname = body.username.strip().lower()
    if db.scalar(select(User).where(func.lower(User.username) == uname)):
        raise HTTPException(409, "That username is taken")
    if body.email and db.scalar(select(User).where(func.lower(User.email) == body.email.lower())):
        raise HTTPException(409, "That email is already registered")
    u = User(username=uname, email=body.email.lower() if body.email else None,
             password_hash=hash_password(body.password), display_name=body.display_name or body.username,
             is_admin=is_first)
    db.add(u)
    db.commit()
    return {"token": make_token(u), "user": user_me(u)}


@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    name = body.username.strip().lower()
    u = db.scalar(select(User).where((func.lower(User.username) == name) | (func.lower(User.email) == name)))
    if not u or not verify_password(body.password, u.password_hash):
        raise HTTPException(401, "Wrong username or password")
    return {"token": make_token(u), "user": user_me(u)}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return user_me(user)


@router.patch("/me")
def update_me(body: UserPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(user, k, v)
    db.commit()
    return user_me(user)


@router.post("/me/password")
def change_password(body: PasswordChange, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Current password is wrong")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    return {"ok": True}


@router.delete("/me")
def delete_me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(user)
    db.commit()
    return {"ok": True}
