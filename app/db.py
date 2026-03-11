"""
Database connection, schema initialisation, config key/value store, and
AD config defaults.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Optional

from .config import DB_PATH

# ─── AD config defaults ────────────────────────────────────────────────────────

_AD_DEFAULTS: dict = {
    "enabled":           False,
    "server":            "",
    "port":              389,
    "use_ssl":           False,
    "verify_ssl":        True,
    "auth_method":       "simple",
    "bind_dn":           "",
    "bind_password":     "",
    "base_dn":           "",
    "user_search_base":  "",
    "username_attr":     "sAMAccountName",
    "display_name_attr": "displayName",
    "email_attr":        "mail",
    "department_attr":   "department",
    "title_attr":        "title",
    "cache_ttl_hours":   24,
}

# ─── Connection ────────────────────────────────────────────────────────────────

def ensure_db_dir() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)


def get_db() -> sqlite3.Connection:
    ensure_db_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ─── Schema ────────────────────────────────────────────────────────────────────

def init_db() -> None:
    # Import here to avoid circular dependency (importer → db → importer).
    from .importer import ensure_jobs_columns, backfill_impressions_and_sheets, repair_historical_rows, backfill_color_mode
    with closing(get_db()) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                printer     TEXT    NOT NULL,
                user_name   TEXT    NOT NULL,
                job_id      TEXT    NOT NULL,
                job_ts      TEXT    NOT NULL,
                year_month  TEXT    NOT NULL,
                pages       INTEGER NOT NULL,
                impressions INTEGER NOT NULL DEFAULT 0,
                sheets      INTEGER NOT NULL DEFAULT 0,
                billing     TEXT,
                host        TEXT,
                job_name    TEXT,
                media       TEXT,
                sides       TEXT,
                color_mode  TEXT    NOT NULL DEFAULT '',
                raw_line    TEXT    NOT NULL,
                UNIQUE(raw_line)
            );
            CREATE INDEX IF NOT EXISTS idx_jobs_user    ON jobs(user_name);
            CREATE INDEX IF NOT EXISTS idx_jobs_printer ON jobs(printer);
            CREATE INDEX IF NOT EXISTS idx_jobs_ym      ON jobs(year_month);
            CREATE INDEX IF NOT EXISTS idx_jobs_ts      ON jobs(job_ts);

            CREATE TABLE IF NOT EXISTS app_config (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS ad_user_cache (
                sam_account  TEXT PRIMARY KEY,
                display_name TEXT,
                email        TEXT,
                department   TEXT,
                title        TEXT,
                cached_at    TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS import_state (
                id          INTEGER PRIMARY KEY CHECK (id = 1),
                log_inode   INTEGER,
                log_pos     INTEGER NOT NULL DEFAULT 0,
                last_import TEXT
            );
            """
        )
        ensure_jobs_columns(conn)
        backfill_impressions_and_sheets(conn)
        repair_historical_rows(conn)
        backfill_color_mode(conn)
        conn.commit()

# ─── Config key/value helpers ──────────────────────────────────────────────────

def get_config(key: str) -> Optional[str]:
    try:
        with closing(get_db()) as conn:
            row = conn.execute(
                "SELECT value FROM app_config WHERE key = ?", (key,)
            ).fetchone()
            return row[0] if row else None
    except sqlite3.OperationalError:
        return None


def set_config(key: str, value: str) -> None:
    with closing(get_db()) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO app_config (key, value) VALUES (?, ?)",
            (key, value),
        )
        conn.commit()


def get_ad_config() -> dict:
    """Return merged AD config (DB values override defaults)."""
    cfg = dict(_AD_DEFAULTS)
    raw = get_config("ad_config")
    if raw:
        try:
            cfg.update(json.loads(raw))
        except json.JSONDecodeError:
            pass
    return cfg
