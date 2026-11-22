"""Two-way sync between the Mise shopping list and a Home Assistant to-do list.

Uses Home Assistant's REST API with a long-lived access token and the `todo.*` services, so it works
with the built-in Shopping List (todo.shopping_list) or any other to-do list entity (Local To-do, Bring!,
Todoist, ...). Every call is best-effort: if Home Assistant is down, Mise keeps working.
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from ..config import get_settings

log = logging.getLogger("mise.homeassistant")


class HAError(Exception):
    pass


def enabled() -> bool:
    s = get_settings()
    return bool(s.home_assistant_url and s.home_assistant_token)


def _entity() -> str:
    return get_settings().home_assistant_todo_entity or "todo.shopping_list"


def _client() -> httpx.Client:
    s = get_settings()
    return httpx.Client(base_url=s.home_assistant_url.rstrip("/"), timeout=httpx.Timeout(10, connect=3),
                        headers={"Authorization": f"Bearer {s.home_assistant_token}"})


def _service(c: httpx.Client, service: str, data: dict, response: bool = False) -> dict:
    url = f"/api/services/todo/{service}" + ("?return_response" if response else "")
    try:
        r = c.post(url, json={"entity_id": _entity(), **data})
    except httpx.HTTPError as e:
        raise HAError(f"Can't reach Home Assistant ({type(e).__name__})") from e
    if r.status_code == 401:
        raise HAError("Home Assistant rejected the access token")
    if r.status_code >= 400:
        raise HAError(f"Home Assistant error {r.status_code}: {r.text[:200]}")
    try:
        return r.json() if r.content else {}
    except ValueError:
        return {}


def get_items(c: httpx.Client) -> dict[str, dict]:
    """uid -> {"summary", "status"} for every item on the list."""
    try:
        data = _service(c, "get_items", {"status": ["needs_action", "completed"]}, response=True)
        resp = data.get("service_response", data) if isinstance(data, dict) else {}
        items = (resp.get(_entity()) or {}).get("items")
        if items is not None:
            return {i["uid"]: {"summary": i.get("summary", ""), "status": i.get("status", "needs_action")}
                    for i in items if i.get("uid")}
    except HAError as e:
        if "reach" in str(e) or "access token" in str(e):
            raise
    # Older Home Assistant without service responses: the Shopping List integration's own API.
    try:
        r = c.get("/api/shopping_list")
        if r.status_code == 200:
            return {str(i["id"]): {"summary": i.get("name", ""), "status": "completed" if i.get("complete") else "needs_action"}
                    for i in r.json()}
    except (httpx.HTTPError, ValueError, KeyError):
        pass
    raise HAError("Couldn't read the Home Assistant list (check HOME_ASSISTANT_TODO_ENTITY)")


def push(rows: list, display) -> Optional[str]:
    """Create or rename the Home Assistant item for each row (ShoppingItem objects).
    `display(row)` returns the text to show. Sets row.ha_uid. Returns an error message or None."""
    if not enabled() or not rows:
        return None
    try:
        with _client() as c:
            added: list = []
            for row in rows:
                text = display(row)
                if row.ha_uid:
                    try:
                        _service(c, "update_item", {"item": row.ha_uid, "rename": text, "status": "needs_action"})
                        continue
                    except HAError:
                        row.ha_uid = None  # removed in Home Assistant: add it again
                _service(c, "add_item", {"item": text})
                added.append((row, text))
            if added:
                # add_item doesn't return an id; look the new items up by their text
                items = get_items(c)
                claimed = set()
                for row, text in added:
                    for uid, it in items.items():
                        if uid not in claimed and it["summary"] == text and it["status"] == "needs_action":
                            row.ha_uid = uid
                            claimed.add(uid)
                            break
                    else:
                        # Home Assistant also accepts the item's text as its identifier
                        row.ha_uid = text
        return None
    except HAError as e:
        log.warning("Home Assistant sync failed: %s", e)
        return str(e)


def set_done(uid: Optional[str], done: bool) -> Optional[str]:
    if not enabled() or not uid:
        return None
    try:
        with _client() as c:
            _service(c, "update_item", {"item": uid, "status": "completed" if done else "needs_action"})
        return None
    except HAError as e:
        log.warning("Home Assistant sync failed: %s", e)
        return str(e)


def rename(uid: Optional[str], text: str) -> Optional[str]:
    if not enabled() or not uid:
        return None
    try:
        with _client() as c:
            _service(c, "update_item", {"item": uid, "rename": text})
        return None
    except HAError as e:
        return str(e)


def remove(uids: list[str]) -> Optional[str]:
    uids = [u for u in uids if u]
    if not enabled() or not uids:
        return None
    try:
        with _client() as c:
            for u in uids:  # one at a time: one missing item shouldn't block the rest
                try:
                    _service(c, "remove_item", {"item": u})
                except HAError as e:
                    if "access token" in str(e) or "reach" in str(e):
                        raise  # Home Assistant is down or the token is wrong: stop
                    # otherwise the item was already gone in Home Assistant: fine
        return None
    except HAError as e:
        log.warning("Home Assistant sync failed: %s", e)
        return str(e)


def pull() -> tuple[Optional[dict], Optional[str]]:
    """Current Home Assistant items, or (None, error)."""
    if not enabled():
        return None, None
    try:
        with _client() as c:
            return get_items(c), None
    except HAError as e:
        log.warning("Home Assistant sync failed: %s", e)
        return None, str(e)
