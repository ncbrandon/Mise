import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from .config import get_settings
from .db import Base, engine
from . import models  # noqa: F401  (register tables)
from .routers import account, collections, export, imports, recipes, shopping, social, web

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("mise")


def _wait_for_db(tries: int = 30) -> None:
    for n in range(tries):
        try:
            with engine.connect() as c:
                c.execute(text("select 1"))
            return
        except OperationalError:
            log.info("waiting for database (%d/%d)...", n + 1, tries)
            time.sleep(2)
    raise RuntimeError("Database is not reachable")


# Columns added after the first release (create_all doesn't alter existing tables).
MIGRATIONS = [
    "ALTER TABLE shopping_items ADD COLUMN IF NOT EXISTS ha_uid VARCHAR(100)",
]


def _migrate() -> None:
    with engine.begin() as c:
        for sql in MIGRATIONS:
            c.execute(text(sql))


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    if s.secret_key == "change-me":
        log.warning("SECRET_KEY is the default. Set a long random SECRET_KEY in the stack environment!")
    _wait_for_db()
    Base.metadata.create_all(engine)
    _migrate()
    os.makedirs(s.media_dir, exist_ok=True)
    log.info("Mise ready. AI: %s", "on (" + s.llm_model + ")" if s.llm_enabled else "off")
    yield


app = FastAPI(title="Mise", version=account.VERSION, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
def health():
    return {"ok": True}


for r in (account.router, recipes.router, imports.router, collections.router, shopping.router,
          social.router, export.router):
    app.include_router(r)

os.makedirs(get_settings().media_dir, exist_ok=True)
app.mount("/media", StaticFiles(directory=get_settings().media_dir), name="media")

# must be last: contains the catch-all reader route
app.include_router(web.router)
