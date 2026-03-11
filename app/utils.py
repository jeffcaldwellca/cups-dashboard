"""
Shared utilities: HTML escaping, query helpers, CSRF, AD display, CSV,
month helpers, and the month-filter form fragment.
"""
from __future__ import annotations

import html as _html
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime
from typing import Iterable, Optional

from flask import Response, request, session

from .ad import get_cached_ad_user
from .db import get_db

# ─── HTML / string helpers ─────────────────────────────────────────────────────

def h(value: object) -> str:
    return _html.escape("" if value is None else str(value), quote=True)

# ─── Query helpers ─────────────────────────────────────────────────────────────

def scalar(query: str, params: tuple = ()) -> int:
    with closing(get_db()) as conn:
        row = conn.execute(query, params).fetchone()
        if not row:
            return 0
        return int(row[0] or 0)


def rows(query: str, params: tuple = ()) -> list[sqlite3.Row]:
    with closing(get_db()) as conn:
        return list(conn.execute(query, params).fetchall())


def available_months() -> list[str]:
    result = rows("SELECT DISTINCT year_month FROM jobs ORDER BY year_month DESC")
    return [r[0] for r in result]


def current_month_fallback() -> str:
    months = available_months()
    return months[0] if months else datetime.now().strftime("%Y-%m")


def last_import_time() -> str:
    try:
        with closing(get_db()) as conn:
            row = conn.execute(
                "SELECT last_import FROM import_state WHERE id = 1"
            ).fetchone()
            return row["last_import"] if row and row["last_import"] else "Never"
    except sqlite3.OperationalError:
        return "Never"

# ─── CSRF helpers ──────────────────────────────────────────────────────────────

def csrf_token() -> str:
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    return session["csrf_token"]


def verify_csrf() -> bool:
    submitted = request.form.get("csrf_token", "")
    expected  = session.get("csrf_token", "")
    if not submitted or not expected:
        return False
    return secrets.compare_digest(submitted, expected)

# ─── AD display helper ─────────────────────────────────────────────────────────

def ad_display(sam: str, ad_cfg: dict) -> str:
    """Return enriched display string if AD is enabled and user is cached."""
    if not ad_cfg.get("enabled"):
        return h(sam)
    ttl  = int(ad_cfg.get("cache_ttl_hours", 24))
    info = get_cached_ad_user(sam, ttl)
    if info and info.get("display_name"):
        return (
            f'{h(info["display_name"])} '
            f'<span class="muted" style="font-size:.82rem;">({h(sam)})</span>'
        )
    return h(sam)

# ─── Color mode badge ──────────────────────────────────────────────────────────

_BW_MODES = frozenset({
    "monochrome", "process-monochrome", "auto-monochrome",
    "bi-level", "process-bi-level", "highlight",
})


def color_mode_badge(mode: str) -> str:
    """Return an HTML badge for a print-color-mode value."""
    m = (mode or "").strip().lower()
    if m == "color":
        return '<span style="color:#0a7;font-weight:600;white-space:nowrap">&#9632; Color</span>'
    if m in _BW_MODES:
        return '<span style="color:#555;font-weight:600;white-space:nowrap">&#9633; B&amp;W</span>'
    return '<span class="muted">-</span>'

# ─── CSV response ──────────────────────────────────────────────────────────────

def csv_response(filename: str, header: list[str], data_rows: Iterable[Iterable]) -> Response:
    def generate():
        yield ",".join(header) + "\n"
        for row in data_rows:
            escaped = []
            for item in row:
                text = "" if item is None else str(item)
                if any(ch in text for ch in [",", '"', "\n"]):
                    text = '"' + text.replace('"', '""') + '"'
                escaped.append(text)
            yield ",".join(escaped) + "\n"

    return Response(
        generate(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )

# ─── Month-filter form ─────────────────────────────────────────────────────────

def month_filter_form(selected_month: str) -> str:
    options = []
    for m in available_months():
        sel = "selected" if m == selected_month else ""
        options.append(f'<option value="{h(m)}" {sel}>{h(m)}</option>')
    if not options:
        options.append(
            f'<option value="{h(selected_month)}" selected>{h(selected_month)}</option>'
        )
    return f"""
    <form method="get" class="filters">
      <div class="field">
        <label for="month">Reporting Month</label>
        <select name="month" id="month">{''.join(options)}</select>
      </div>
      <div class="field">
        <button type="submit">Apply Filter</button>
      </div>
    </form>
    """
