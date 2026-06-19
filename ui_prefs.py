"""
Server-side storage for UI-only preferences that previously lived in
browser localStorage. Per-device localStorage means: presets don't
appear on other devices, the column layout you carefully arranged
on your laptop is gone on your phone, the section you collapsed at
home is open again at work, etc. Postgres-backed prefs fix that.

Single-tenant: there's no per-user concept (the app has no auth).
All prefs are visible from every device that can reach the deployment.

Schema is a simple key/value bag — easier to add new keys than
adding a column per pref:

    CREATE TABLE ui_prefs (
        key         TEXT PRIMARY KEY,
        value       JSONB NOT NULL,
        updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    );

Values are stored as JSON so booleans / arrays / objects round-trip
without per-type serialisation logic on the client.
"""

from __future__ import annotations

import json
import logging

import snapshots

log = logging.getLogger("ui_prefs")

# Known keys — kept here as documentation, not as a guard. The JS
# adapter is the single source of truth for which keys exist; if a new
# UI control adds a new key, no Python change is needed.
KNOWN_KEYS: tuple[str, ...] = (
    "match_columns_order",         # results-table column order (array of keys)
    "match_columns_hidden",        # set of hidden column keys (array)
    "collapse_filters",            # 9 collapsed-section booleans
    "collapse_diagnose",
    "collapse_rules",
    "collapse_picks",
    "collapse_momentum",
    "collapse_momentum_diagnose",
    "collapse_setups",
    "collapse_options_history",
    "collapse_options_scan",
    "app_tab",                     # "stock" | "options"
    "options_history_view",        # "all" | "today" | etc.
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ui_prefs (
    key         TEXT PRIMARY KEY,
    value       JSONB NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def init_tables() -> None:
    if not snapshots.enabled():
        return
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(_SCHEMA)
    except Exception as exc:
        log.warning("ui_prefs.init_tables failed: %s", exc)


def get_all() -> dict:
    """Read every saved pref as `{key: value}`. Returns {} when the DB
    is unset or unreachable so the page render keeps working — the
    client falls back to its built-in HTML defaults."""
    if not snapshots.enabled():
        return {}
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute("SELECT key, value FROM ui_prefs")
            rows = cur.fetchall()
    except Exception as exc:
        log.warning("ui_prefs.get_all failed: %s", exc)
        return {}
    out: dict = {}
    for k, v in rows:
        # psycopg2 already decodes JSONB to Python types (str / bool /
        # list / dict / int / float / None) — assign verbatim. The
        # previous version tried to re-json.loads strings, which broke
        # any pref whose value was a bare string ("options" isn't valid
        # JSON on its own, so json.loads raised and the row was silently
        # dropped — that's what was making get_all() miss app_tab).
        out[k] = v
    return out


def set_pref(key: str, value) -> dict:
    """Upsert one preference. Returns `{ok: bool, error?: str}`."""
    if not snapshots.enabled():
        return {"ok": False, "error": "no_db"}
    if not isinstance(key, str) or not key.strip():
        return {"ok": False, "error": "empty_key"}
    key = key.strip()
    if len(key) > 80:
        return {"ok": False, "error": "key_too_long"}
    try:
        payload = json.dumps(value)
    except (TypeError, ValueError):
        return {"ok": False, "error": "unserialisable_value"}
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(
                "INSERT INTO ui_prefs (key, value, updated_at) "
                "VALUES (%s, %s, now()) "
                "ON CONFLICT (key) DO UPDATE SET "
                "value = EXCLUDED.value, updated_at = now()",
                (key, payload),
            )
        return {"ok": True}
    except Exception as exc:
        log.warning("ui_prefs.set_pref(%s) failed: %s", key, exc)
        return {"ok": False, "error": "db_error", "detail": str(exc)}


def delete_pref(key: str) -> dict:
    if not snapshots.enabled():
        return {"ok": False, "error": "no_db"}
    if not isinstance(key, str) or not key.strip():
        return {"ok": False, "error": "empty_key"}
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute("DELETE FROM ui_prefs WHERE key = %s", (key.strip(),))
        return {"ok": True}
    except Exception as exc:
        log.warning("ui_prefs.delete_pref(%s) failed: %s", key, exc)
        return {"ok": False, "error": "db_error", "detail": str(exc)}
