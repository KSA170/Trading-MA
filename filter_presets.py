"""
Server-side storage for the screener's named filter presets.

Each preset is a row in `filter_presets`:
    name           TEXT PRIMARY KEY   (case-insensitive uniqueness via LOWER)
    state          JSONB              ({inputs, toggles, exchanges})
    last_used_at   TIMESTAMPTZ        (NULL until first selected)
    updated_at     TIMESTAMPTZ        (auto-set on insert / update)

"Last used" is whichever row has the most recent `last_used_at` —
that lets the screener auto-load it on page open from any device.
Cap is enforced application-side at MAX_PRESETS (= 5) so a new name
beyond the cap is rejected without clobbering an existing slot;
overwriting an existing name is always allowed.

No per-user concept — the app is single-tenant. All presets are
visible from every device that can reach the deployment.
"""

from __future__ import annotations

import json
import logging

import snapshots

log = logging.getLogger("filter_presets")

MAX_PRESETS: int = 5
MAX_NAME_LEN: int = 40

_SCHEMA = """
CREATE TABLE IF NOT EXISTS filter_presets (
    name           TEXT PRIMARY KEY,
    state          JSONB NOT NULL,
    last_used_at   TIMESTAMPTZ,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def init_tables() -> None:
    if not snapshots.enabled():
        return
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(_SCHEMA)
    except Exception as exc:
        log.warning("filter_presets.init_tables failed: %s", exc)


def _normalise_name(name: str) -> str:
    """Trim whitespace and clamp length. Empty input → empty string;
    caller handles that as an error."""
    if not isinstance(name, str):
        return ""
    cleaned = name.strip()
    if len(cleaned) > MAX_NAME_LEN:
        cleaned = cleaned[:MAX_NAME_LEN]
    return cleaned


def list_presets() -> dict:
    """Return `{presets: [{name, state, last_used_at}], last_used: str|null,
    max: 5}`. Presets are ordered by name (case-insensitive) so the UI
    dropdown is stable across sessions."""
    out = {"presets": [], "last_used": None, "max": MAX_PRESETS}
    if not snapshots.enabled():
        return out
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(
                "SELECT name, state, last_used_at "
                "FROM filter_presets ORDER BY LOWER(name)"
            )
            rows = cur.fetchall()
    except Exception as exc:
        log.warning("filter_presets.list_presets failed: %s", exc)
        return out

    last_name = None
    last_ts = None
    for name, state, last_used_at in rows:
        # psycopg2 returns JSONB as dict, but accept str just in case.
        if isinstance(state, str):
            try:
                state = json.loads(state)
            except Exception:
                state = {}
        out["presets"].append({
            "name": name,
            "state": state if isinstance(state, dict) else {},
            "last_used_at": last_used_at.isoformat() if last_used_at else None,
        })
        if last_used_at is not None and (last_ts is None or last_used_at > last_ts):
            last_ts = last_used_at
            last_name = name
    out["last_used"] = last_name
    return out


def save_preset(name: str, state: dict) -> dict:
    """Insert-or-update a named preset. Enforces the 5-cap on *new*
    names (overwriting an existing name is always allowed). Touches
    `last_used_at = now()` since saving is itself a "use" signal.

    Returns `{ok: bool, error?: str, name?: str}`. Errors:
      "no_db"        — DATABASE_URL unset
      "empty_name"   — name was empty after trimming
      "cap_reached"  — MAX_PRESETS already exist and this is a new name
      "db_error"     — transient DB exception (full text logged)
    """
    if not snapshots.enabled():
        return {"ok": False, "error": "no_db"}
    clean = _normalise_name(name)
    if not clean:
        return {"ok": False, "error": "empty_name"}
    if not isinstance(state, dict):
        return {"ok": False, "error": "bad_state"}
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            # Check for existing row (case-insensitive) AND count atomically
            # in one trip — avoids race where two devices both think they're
            # under the cap.
            cur.execute(
                "SELECT name FROM filter_presets WHERE LOWER(name) = LOWER(%s)",
                (clean,),
            )
            existing = cur.fetchone()
            if existing is None:
                cur.execute("SELECT COUNT(*) FROM filter_presets")
                count = int(cur.fetchone()[0] or 0)
                if count >= MAX_PRESETS:
                    return {"ok": False, "error": "cap_reached", "max": MAX_PRESETS}
            # If overwriting under a different-cased name (e.g. "Default"
            # vs "default"), keep the existing capitalization so the UI
            # doesn't appear to lose the entry.
            final_name = existing[0] if existing else clean
            cur.execute(
                "INSERT INTO filter_presets (name, state, last_used_at, updated_at) "
                "VALUES (%s, %s, now(), now()) "
                "ON CONFLICT (name) DO UPDATE SET "
                "state = EXCLUDED.state, "
                "last_used_at = now(), "
                "updated_at = now()",
                (final_name, json.dumps(state)),
            )
            return {"ok": True, "name": final_name}
    except Exception as exc:
        log.warning("filter_presets.save_preset failed: %s", exc)
        return {"ok": False, "error": "db_error", "detail": str(exc)}


def delete_preset(name: str) -> dict:
    if not snapshots.enabled():
        return {"ok": False, "error": "no_db"}
    clean = _normalise_name(name)
    if not clean:
        return {"ok": False, "error": "empty_name"}
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(
                "DELETE FROM filter_presets WHERE LOWER(name) = LOWER(%s)",
                (clean,),
            )
        return {"ok": True}
    except Exception as exc:
        log.warning("filter_presets.delete_preset failed: %s", exc)
        return {"ok": False, "error": "db_error", "detail": str(exc)}


def mark_used(name: str) -> dict:
    """Update last_used_at without otherwise touching the row. Called
    when the user picks a preset from the dropdown, so the next page
    load (from any device) auto-applies the same one."""
    if not snapshots.enabled():
        return {"ok": False, "error": "no_db"}
    clean = _normalise_name(name)
    if not clean:
        return {"ok": False, "error": "empty_name"}
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(
                "UPDATE filter_presets SET last_used_at = now() "
                "WHERE LOWER(name) = LOWER(%s)",
                (clean,),
            )
        return {"ok": True}
    except Exception as exc:
        log.warning("filter_presets.mark_used failed: %s", exc)
        return {"ok": False, "error": "db_error", "detail": str(exc)}


def clear_last_used() -> dict:
    """Used by 'Reset to built-in' — clears every row's last_used_at so
    the next page open doesn't auto-apply any preset."""
    if not snapshots.enabled():
        return {"ok": False, "error": "no_db"}
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute("UPDATE filter_presets SET last_used_at = NULL")
        return {"ok": True}
    except Exception as exc:
        log.warning("filter_presets.clear_last_used failed: %s", exc)
        return {"ok": False, "error": "db_error", "detail": str(exc)}
