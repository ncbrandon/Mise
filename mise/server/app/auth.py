from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import User

bearer = HTTPBearer(auto_error=False)


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode()[:72], bcrypt.gensalt()).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode()[:72], hashed.encode())
    except ValueError:
        return False


def make_token(user: User) -> str:
    s = get_settings()
    payload = {"sub": str(user.id), "exp": datetime.now(timezone.utc) + timedelta(days=s.token_days)}
    return jwt.encode(payload, s.secret_key, algorithm="HS256")


def _user_from_token(token: str, db: Session) -> Optional[User]:
    try:
        payload = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    return db.get(User, int(payload.get("sub", 0)))


def current_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
                 db: Session = Depends(get_db)) -> User:
    if not creds:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    user = _user_from_token(creds.credentials, db)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired, sign in again")
    return user


def optional_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
                  db: Session = Depends(get_db)) -> Optional[User]:
    if not creds:
        return None
    return _user_from_token(creds.credentials, db)
