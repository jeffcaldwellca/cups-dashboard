"""
CUPS page_log parsing, import (full + incremental), rotation handling,
and the background refresh thread.
"""
from __future__ import annotations

import re
import shlex
import sqlite3
import threading
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Optional

from .ad import enrich_users_from_ad
from .config import LOG_REFRESH_SECS, PAGE_LOG_PATH
from .db import get_db
from .models import DATE_RE, MONTHS, JobRecord

# ─── Background-thread controls (module-level singletons) ─────────────────────
_BG_STOP    = threading.Event()
_IMPORT_LOCK = threading.Lock()

# ─── Parsing helpers ───────────────────────────────────────────────────────────

def clean_token(value: str) -> str:
    cleaned = value.strip()
    while True:
        before = cleaned
        if cleaned.startswith('\\"'):
            cleaned = cleaned[2:]
        if cleaned.endswith('\\"'):
            cleaned = cleaned[:-2]
        cleaned = cleaned.strip('"').strip("'").strip()
        if cleaned == before:
            break
    return cleaned


def parse_int_token(value: str) -> int:
    try:
        return int(clean_token(value))
    except ValueError:
        return 0


def parse_explicit_impressions(tokens: list[str]) -> Optional[int]:
    for token in tokens:
        lower = token.lower()
        for prefix in ("impressions=", "impression=", "impressions:", "impression:"):
            if lower.startswith(prefix):
                parsed = parse_int_token(token[len(prefix):])
                return parsed if parsed >= 0 else 0
    return None


def estimate_sheets(impressions: int, sides: str) -> int:
    if impressions <= 0:
        return 0
    sides_value = (sides or "").strip().lower()
    if "two-sided" in sides_value or "duplex" in sides_value:
        return (impressions + 1) // 2
    return impressions


def parse_cups_date(value: str) -> Optional[datetime]:
    match = DATE_RE.match(value.strip())
    if not match:
        return None
    gd    = match.groupdict()
    month = MONTHS.get(gd["mon"])
    if month is None:
        return None
    return datetime(
        year=int(gd["year"]), month=month, day=int(gd["day"]),
        hour=int(gd["hour"]), minute=int(gd["minute"]), second=int(gd["second"]),
    )


def parse_page_log_line(line: str) -> Optional[JobRecord]:
    line_text = line.rstrip("\n").strip()
    if line_text.startswith('"') and line_text.endswith('"') and len(line_text) > 1:
        line_text = line_text[1:-1].strip()
    match = re.match(
        r'^\s*(?P<printer>\S+)\s+(?P<user>\S+)\s+(?P<job_id>\S+)'
        r'\s+\[(?P<date>[^\]]+)\]\s*(?P<rest>.*)$',
        line_text,
    )
    if not match:
        return None

    printer = clean_token(match.group("printer"))
    user    = clean_token(match.group("user"))
    job_id  = clean_token(match.group("job_id"))
    ts      = parse_cups_date(f'[{match.group("date")}]')
    if ts is None:
        return None

    rest = match.group("rest")
    try:
        tail_parts = shlex.split(rest) if rest else []
    except ValueError:
        tail_parts = rest.split() if rest else []

    pages = idx = 0
    if tail_parts and clean_token(tail_parts[0]).lower() == "total":
        if len(tail_parts) > 1:
            pages = parse_int_token(tail_parts[1])
        idx = 2
    elif tail_parts:
        pages = parse_int_token(tail_parts[0])
        idx   = 1

    billing  = clean_token(tail_parts[idx])     if len(tail_parts) > idx     else ""
    host     = clean_token(tail_parts[idx + 1]) if len(tail_parts) > idx + 1 else ""
    job_name = clean_token(tail_parts[idx + 2]) if len(tail_parts) > idx + 2 else ""
    media    = clean_token(tail_parts[idx + 3]) if len(tail_parts) > idx + 3 else ""
    sides    = clean_token(tail_parts[idx + 4]) if len(tail_parts) > idx + 4 else ""
    extras   = [clean_token(p) for p in tail_parts[idx + 5:]] if len(tail_parts) > idx + 5 else []

    explicit_impressions = parse_explicit_impressions(extras)
    impressions = explicit_impressions if explicit_impressions is not None else pages
    sheets      = estimate_sheets(impressions, sides)

    return JobRecord(
        printer=printer, user=user, job_id=job_id, timestamp=ts,
        pages=pages, impressions=impressions, sheets=sheets,
        billing=billing, host=host, job_name=job_name,
        media=media, sides=sides, raw_line=line_text,
    )

# ─── DB migration helpers (called from db.init_db) ────────────────────────────

def ensure_jobs_columns(conn: sqlite3.Connection) -> None:
    current = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    if "impressions" not in current:
        conn.execute("ALTER TABLE jobs ADD COLUMN impressions INTEGER NOT NULL DEFAULT 0")
    if "sheets" not in current:
        conn.execute("ALTER TABLE jobs ADD COLUMN sheets INTEGER NOT NULL DEFAULT 0")


def backfill_impressions_and_sheets(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        UPDATE jobs SET impressions = CASE
            WHEN impressions <= 0 THEN pages ELSE impressions END
        """
    )
    conn.execute(
        """
        UPDATE jobs SET sheets = CASE
            WHEN sheets <= 0 THEN
                CASE
                    WHEN lower(COALESCE(sides, '')) LIKE '%two-sided%'
                      OR lower(COALESCE(sides, '')) LIKE '%duplex%'
                    THEN CAST((impressions + 1) / 2 AS INTEGER)
                    ELSE impressions
                END
            ELSE sheets END
        """
    )
    conn.execute(
        """
        UPDATE jobs
        SET printer   = TRIM(REPLACE(printer,   '\\"', ''), '"'),
            user_name = TRIM(REPLACE(user_name, '\\"', ''), '"'),
            job_name  = TRIM(REPLACE(job_name,  '\\"', ''), '"'),
            media     = TRIM(REPLACE(media,     '\\"', ''), '"'),
            sides     = TRIM(REPLACE(sides,     '\\"', ''), '"')
        """
    )


def repair_historical_rows(conn: sqlite3.Connection) -> None:
    candidates = conn.execute(
        """
        SELECT id, raw_line FROM jobs
        WHERE printer   LIKE '"%' OR printer   LIKE '%"' OR printer   LIKE '%\\"%'
           OR user_name LIKE '"%' OR user_name LIKE '%"' OR user_name LIKE '%\\"%'
           OR job_name  LIKE '"%' OR job_name  LIKE '%"' OR job_name  LIKE '%\\"%'
           OR media     LIKE '"%' OR media     LIKE '%"' OR media     LIKE '%\\"%'
           OR sides     LIKE '"%' OR sides     LIKE '%"' OR sides     LIKE '%\\"%'
        """
    ).fetchall()
    for row in candidates:
        rec = parse_page_log_line(row["raw_line"])
        if rec is None:
            continue
        conn.execute(
            """
            UPDATE jobs
            SET printer = ?, user_name = ?, job_id = ?, job_ts = ?, year_month = ?,
                pages = ?, impressions = ?, sheets = ?,
                billing = ?, host = ?, job_name = ?, media = ?, sides = ?
            WHERE id = ?
            """,
            (
                rec.printer, rec.user, rec.job_id,
                rec.timestamp.isoformat(sep=" "), rec.timestamp.strftime("%Y-%m"),
                rec.pages, rec.impressions, rec.sheets,
                rec.billing, rec.host, rec.job_name, rec.media, rec.sides,
                row["id"],
            ),
        )

# ─── Import SQL ────────────────────────────────────────────────────────────────

_INSERT_SQL = """
    INSERT INTO jobs (
        printer, user_name, job_id, job_ts, year_month,
        pages, impressions, sheets,
        billing, host, job_name, media, sides, raw_line
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _rec_params(rec: JobRecord) -> tuple:
    return (
        rec.printer, rec.user, rec.job_id,
        rec.timestamp.isoformat(sep=" "), rec.timestamp.strftime("%Y-%m"),
        rec.pages, rec.impressions, rec.sheets,
        rec.billing, rec.host, rec.job_name, rec.media, rec.sides, rec.raw_line,
    )

# ─── Import state (inode + byte position) ─────────────────────────────────────

def _get_import_state() -> tuple[Optional[int], int]:
    try:
        with closing(get_db()) as conn:
            row = conn.execute(
                "SELECT log_inode, log_pos FROM import_state WHERE id = 1"
            ).fetchone()
            if row:
                return row["log_inode"], int(row["log_pos"] or 0)
    except sqlite3.OperationalError:
        pass
    return None, 0


def _set_import_state(inode: int, pos: int) -> None:
    with closing(get_db()) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO import_state (id, log_inode, log_pos, last_import)
            VALUES (1, ?, ?, ?)
            """,
            (inode, pos, datetime.now().isoformat(sep=" ")),
        )
        conn.commit()

# ─── Core drain helper ─────────────────────────────────────────────────────────

def _drain_file(fh, conn: sqlite3.Connection, start_pos: int,
                new_users: list) -> tuple[int, int, int]:
    """
    Read lines from an open binary file handle starting at start_pos.
    Returns (inserted, skipped, final_pos).
    """
    inserted = skipped = 0
    pos = start_pos
    fh.seek(start_pos)
    for raw_bytes in fh:
        line = raw_bytes.decode("utf-8", errors="replace")
        rec  = parse_page_log_line(line)
        if rec is None:
            skipped += 1
            pos = fh.tell()
            continue
        try:
            conn.execute(_INSERT_SQL, _rec_params(rec))
            inserted += 1
            new_users.append(rec.user)
        except sqlite3.IntegrityError:
            skipped += 1
        pos = fh.tell()
    return inserted, skipped, pos

# ─── Import functions ──────────────────────────────────────────────────────────

def import_page_log_incremental() -> tuple[int, int]:
    """
    Import only lines appended since the last run (binary mode for reliable
    byte offsets).

    Rotation-safe: when an inode change is detected, page_log.O is drained
    from the last known position before switching to the new page_log, closing
    the data gap that would otherwise occur during CUPS log rotation.
    """
    from .db import init_db  # avoid top-level circular import
    init_db()
    log_file = Path(PAGE_LOG_PATH)
    if not log_file.exists():
        return 0, 0

    stat          = log_file.stat()
    current_inode = stat.st_ino
    current_size  = stat.st_size
    saved_inode, saved_pos = _get_import_state()

    inserted  = 0
    skipped   = 0
    new_users: list[str] = []
    rotated   = saved_inode is not None and saved_inode != current_inode

    with closing(get_db()) as conn:
        if rotated:
            old_log = Path(PAGE_LOG_PATH + ".O")
            if old_log.exists():
                try:
                    old_stat = old_log.stat()
                    if old_stat.st_ino == saved_inode and saved_pos < old_stat.st_size:
                        with old_log.open("rb") as fh_old:
                            ins, skp, _ = _drain_file(fh_old, conn, saved_pos, new_users)
                            inserted += ins
                            skipped  += skp
                except OSError:
                    pass
            saved_pos = 0
        elif current_size < saved_pos:
            saved_pos = 0

        if saved_pos >= current_size:
            conn.commit()
            return inserted, skipped

        with log_file.open("rb") as fh:
            ins, skp, new_pos = _drain_file(fh, conn, saved_pos, new_users)
            inserted += ins
            skipped  += skp

        conn.commit()

    _set_import_state(current_inode, new_pos)
    if new_users:
        enrich_users_from_ad(list(set(new_users)))
    return inserted, skipped


def import_page_log() -> tuple[int, int]:
    """Full import: read the entire log from byte 0 and update state."""
    from .db import init_db
    init_db()
    log_file = Path(PAGE_LOG_PATH)
    if not log_file.exists():
        raise FileNotFoundError(f"page_log not found: {PAGE_LOG_PATH}")

    inserted  = 0
    skipped   = 0
    new_users: list[str] = []

    with closing(get_db()) as conn, log_file.open("rb") as fh:
        for raw_bytes in fh:
            line = raw_bytes.decode("utf-8", errors="replace")
            rec  = parse_page_log_line(line)
            if rec is None:
                skipped += 1
                continue
            try:
                conn.execute(_INSERT_SQL, _rec_params(rec))
                inserted += 1
                new_users.append(rec.user)
            except sqlite3.IntegrityError:
                skipped += 1
        conn.commit()

    stat = log_file.stat()
    _set_import_state(stat.st_ino, stat.st_size)
    if new_users:
        enrich_users_from_ad(list(set(new_users)))
    return inserted, skipped


def reset_and_reimport() -> tuple[int, int]:
    from .db import init_db
    init_db()
    with closing(get_db()) as conn:
        conn.execute("DELETE FROM jobs")
        conn.execute("DELETE FROM import_state")
        conn.commit()
    return import_page_log()

# ─── Background refresh thread ─────────────────────────────────────────────────

def _start_bg_refresh() -> threading.Thread:
    """Daemon thread that incrementally imports the log every LOG_REFRESH_SECS."""
    def _worker() -> None:
        while not _BG_STOP.wait(LOG_REFRESH_SECS):
            try:
                with _IMPORT_LOCK:
                    import_page_log_incremental()
            except Exception:  # noqa: BLE001
                pass
    t = threading.Thread(target=_worker, daemon=True, name="cups-log-refresh")
    t.start()
    return t
