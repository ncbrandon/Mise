import io
import json
import re
import zipfile
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db
from ..models import Collection, JournalEntry, Recipe, User
from ..serialize import journal_out, recipe_export, user_me

router = APIRouter(prefix="/api", tags=["export"])


def _data(db: Session, user: User) -> dict:
    recipes = db.scalars(select(Recipe).where(Recipe.owner_id == user.id).order_by(Recipe.created_at)).unique().all()
    cols = db.scalars(select(Collection).where(Collection.owner_id == user.id)).all()
    journal = db.scalars(select(JournalEntry).where(JournalEntry.owner_id == user.id)).unique().all()
    return {
        "format": "mise-export",
        "version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "user": user_me(user),
        "recipes": [recipe_export(r) for r in recipes],
        "collections": [{"name": c.name, "icon": c.icon} for c in cols],
        "journal": [journal_out(e) for e in journal],
    }


def _markdown(r: dict) -> str:
    lines = [f"# {r['title']}", ""]
    if r.get("description"):
        lines += [r["description"], ""]
    meta = []
    if r.get("servings_text") or r.get("servings"):
        meta.append(f"Serves: {r.get('servings_text') or r.get('servings')}")
    for k, label in (("prep_time", "Prep"), ("cook_time", "Cook"), ("total_time", "Total")):
        if r.get(k):
            meta.append(f"{label}: {r[k]} min")
    if r.get("source_url"):
        meta.append(f"Source: {r['source_url']}")
    if meta:
        lines += [" · ".join(meta), ""]
    lines += ["## Ingredients", ""]
    group = None
    for i in r.get("ingredients") or []:
        if i.get("group") != group:
            group = i.get("group")
            if group:
                lines += ["", f"**{group}**"]
        lines.append(f"- {i.get('raw')}")
    lines += ["", "## Steps", ""]
    sec = None
    n = 0
    for s in r.get("steps") or []:
        if s.get("section") != sec:
            sec = s.get("section")
            if sec:
                lines += ["", f"**{sec}**"]
        n += 1
        lines.append(f"{n}. {s.get('text')}")
    if r.get("notes"):
        lines += ["", "## Notes", "", r["notes"]]
    return "\n".join(lines) + "\n"


@router.get("/export.json")
def export_json(user: User = Depends(current_user), db: Session = Depends(get_db)):
    body = json.dumps(_data(db, user), ensure_ascii=False, indent=2)
    return Response(body, media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="mise-export.json"'})


@router.get("/export.zip")
def export_zip(user: User = Depends(current_user), db: Session = Depends(get_db)):
    data = _data(db, user)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mise-export.json", json.dumps(data, ensure_ascii=False, indent=2))
        used = set()
        for r in data["recipes"]:
            slug = re.sub(r"[^a-z0-9]+", "-", r["title"].lower()).strip("-")[:60] or "recipe"
            name, n = slug, 2
            while name in used:
                name, n = f"{slug}-{n}", n + 1
            used.add(name)
            z.writestr(f"recipes/{name}.md", _markdown(r))
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="mise-export.zip"'})
