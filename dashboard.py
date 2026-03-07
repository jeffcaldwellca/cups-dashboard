#!/usr/bin/env python3
"""
CUPS Internal Dashboard

A small Flask dashboard for viewing CUPS usage statistics from page_log.

Features:
- Dashboard overview
- Monthly totals
- Usage by user
- Usage by printer
- Recent jobs
- CSV export endpoints
- Optional SQLite cache/rebuild

IMPORTANT - Log Format Requirements:
- page_log MUST use standard CUPS format with date: [DD/Mon/YYYY:HH:MM:SS -TZ]
- Example valid date: [06/Mar/2026:09:15:01 -0500]
- Lines with non-standard formats will be skipped (no error, just ignored)
- If dashboard shows no data, verify log format: head -n 5 /var/log/cups/page_log

Default assumptions:
- page_log path: /var/log/cups/page_log
- date format from CUPS page_log like: [06/Mar/2026:09:15:01 -0500]

Run:
  python3 cups_dashboard_app.py

Recommended:
  python3 -m venv .venv
  source .venv/bin/activate
  pip install flask

Then browse:
  http://127.0.0.1:5000
"""

from __future__ import annotations

import csv
import html
import os
import re
import shlex
import sqlite3
import threading
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from flask import Flask, Response, abort, redirect, render_template_string, request, url_for

APP_TITLE = "CUPS Internal Dashboard"
DEFAULT_PAGE_LOG_PATH = "/var/log/cups/page_log"
DEFAULT_DB_PATH = "./cups_dashboard.db"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 962
DEFAULT_DEBUG = False

PAGE_LOG_PATH = os.environ.get("CUPS_PAGE_LOG", DEFAULT_PAGE_LOG_PATH)
DB_PATH = os.environ.get("CUPS_DASH_DB", DEFAULT_DB_PATH)
HOST = os.environ.get("CUPS_DASH_HOST", DEFAULT_HOST)
PORT = int(os.environ.get("CUPS_DASH_PORT", str(DEFAULT_PORT)))
DEBUG = os.environ.get("CUPS_DASH_DEBUG", "1" if DEFAULT_DEBUG else "0") == "1"

app = Flask(__name__)
STARTUP_INIT_DONE = False
STARTUP_LOCK = threading.Lock()

MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}

DATE_RE = re.compile(
    r"^\[(?P<day>\d{1,2})/(?P<mon>[A-Za-z]{3})/(?P<year>\d{4}):"
    r"(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})"
    r"(?:\s+(?P<offset>[+-]\d{4}|[A-Za-z_/\-+]+))?\]$"
)

BASE_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ title }}</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.1/font/bootstrap-icons.css" rel="stylesheet">
  <style>
    :root {
      --primary-color: #007bff;
      --primary-hover: #0056b3;
      --light-color: #f8f9fa;
      --border-color: #dee2e6;
      --text-muted: #6c757d;
      --success-color: #28a745;
    }
    * {
      box-sizing: border-box;
    }
    body {
      margin: 0;
      color: #212529;
      font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
      line-height: 1.6;
      background: linear-gradient(180deg, #f5f8fc 0%, #eef3fa 100%);
    }
    a { color: var(--primary-color); text-decoration: none; }
    a:hover { text-decoration: underline; }
    .shell {
      max-width: 1240px;
      margin: 0 auto;
      padding: 1.25rem 1rem 2rem 1rem;
    }
    .topbar {
      display: flex;
      gap: 1rem;
      flex-wrap: wrap;
      align-items: flex-start;
      justify-content: space-between;
    }
    .brand-tag {
      display: inline-flex;
      align-items: center;
      gap: 0.45rem;
      border-radius: 999px;
      border: 1px solid rgba(0, 123, 255, 0.2);
      background: rgba(0, 123, 255, 0.1);
      color: var(--primary-color);
      font-size: 0.74rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      padding: 0.24rem 0.56rem;
      margin-bottom: 0.45rem;
    }
    .brand-title {
      font-size: 1.45rem;
      font-weight: 700;
      color: #1f2a37;
      line-height: 1.2;
      margin-bottom: 0.1rem;
    }
    .nav {
      display: flex;
      gap: 0.45rem;
      flex-wrap: wrap;
    }
    .nav a {
      border: 1px solid var(--border-color);
      color: #495057;
      background: #fff;
      border-radius: 0.45rem;
      padding: 0.44rem 0.72rem;
      font-size: 0.875rem;
      font-weight: 600;
      transition: all 0.2s ease;
    }
    .nav a:hover {
      color: var(--primary-color);
      border-color: rgba(0, 123, 255, 0.42);
      text-decoration: none;
      transform: translateY(-1px);
    }
    .nav a.active {
      color: #fff;
      border-color: var(--primary-color);
      background: linear-gradient(135deg, var(--primary-color), var(--primary-hover));
      box-shadow: 0 0.4rem 0.9rem rgba(0, 123, 255, 0.22);
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 1rem;
      margin-bottom: 1rem;
    }
    .card {
      background: #fff;
      border: 1px solid var(--border-color);
      border-radius: 0.7rem;
      padding: 1rem 1.1rem;
      box-shadow: 0 0.3rem 1rem rgba(0, 0, 0, 0.08);
      transition: all 0.24s ease;
      animation: fade-slide-in 300ms ease both;
    }
    .card:hover {
      transform: translateY(-2px);
      box-shadow: 0 0.5rem 1.2rem rgba(0, 0, 0, 0.12);
    }
    .card h3, .card h2 {
      margin-top: 0;
      margin-bottom: 0.5rem;
      color: #212529;
    }
    h2 {
      font-size: 1.06rem;
      font-weight: 700;
    }
    .metric {
      font-size: 1.95rem;
      font-weight: 700;
      margin: 0.38rem 0;
      color: #1f2a37;
    }
    .muted {
      color: var(--text-muted);
      font-size: 0.92rem;
    }
    .two-col {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 1rem;
      margin-bottom: 1rem;
    }
    .two-col > .card {
      min-width: 0;
    }
    @media (max-width: 900px) {
      .two-col { grid-template-columns: 1fr; }
    }
    table {
      width: 100%;
      border-collapse: collapse;
      overflow: hidden;
      border-radius: 0.5rem;
      font-size: 0.9rem;
    }
    .table-wrap {
      overflow-x: auto;
      border: 1px solid var(--border-color);
      border-radius: 0.5rem;
      background: white;
      max-width: 100%;
    }
    .table-wrap table {
      margin-top: 0;
      min-width: 620px;
    }
    th, td {
      text-align: left;
      padding: 0.62rem 0.7rem;
      border-bottom: 1px solid var(--border-color);
      vertical-align: top;
    }
    th {
      background: #f8f9fa;
      color: #495057;
      font-weight: 600;
    }
    tr:hover td {
      background: rgba(0, 123, 255, 0.03);
    }
    .metric-card {
      position: relative;
      overflow: hidden;
    }
    .metric-card::before {
      content: "";
      position: absolute;
      inset: 0 0 auto 0;
      height: 3px;
      background: linear-gradient(90deg, var(--primary-color), #17a2b8);
      opacity: 0.95;
    }
    .filters {
      display: flex;
      gap: 0.75rem;
      flex-wrap: wrap;
      align-items: end;
      margin-bottom: 1rem;
      padding: 0.95rem;
      border-radius: 0.7rem;
      border: 1px solid var(--border-color);
      background: #fff;
    }
    .field {
      display: flex;
      flex-direction: column;
      gap: 6px;
      min-width: 180px;
    }
    label {
      font-size: 0.82rem;
      font-weight: 600;
      color: #495057;
    }
    input, select {
      padding: 0.5rem 0.66rem;
      border-radius: 0.45rem;
      border: 1px solid #ced4da;
      background: white;
      color: #212529;
    }
    input:focus, select:focus {
      outline: none;
      border-color: var(--primary-color);
      box-shadow: 0 0 0 0.2rem rgba(0, 123, 255, 0.25);
    }
    button {
      padding: 0.52rem 0.88rem;
      border-radius: 0.45rem;
      border: 1px solid var(--primary-color);
      background: linear-gradient(135deg, var(--primary-color), var(--primary-hover));
      color: white;
      font-weight: 600;
      cursor: pointer;
    }
    button:hover {
      filter: brightness(1.03);
      transform: translateY(-1px);
    }
    .pill {
      display: inline-block;
      padding: 0.2rem 0.5rem;
      border-radius: 999px;
      background: rgba(0, 123, 255, 0.1);
      color: var(--primary-color);
      border: 1px solid rgba(0, 123, 255, 0.24);
      font-size: 0.74rem;
      font-weight: 600;
    }
    .footer {
      margin-top: 1.2rem;
      color: var(--text-muted);
      font-size: 0.82rem;
    }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
    .action-link {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      margin-bottom: 0.55rem;
      font-size: 0.84rem;
      font-weight: 600;
      color: var(--primary-color);
    }
    .setup-panel {
      margin-top: 0.95rem;
      border: 1px solid var(--border-color);
      border-radius: 0.65rem;
      background: #fff;
      overflow: hidden;
    }
    .setup-panel summary {
      cursor: pointer;
      list-style: none;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 0.72rem 0.86rem;
      font-weight: 600;
      color: #212529;
      background: #f8f9fa;
      transition: background-color 160ms ease;
    }
    .setup-panel summary::-webkit-details-marker { display: none; }
    .setup-panel summary:hover {
      background: #eef5ff;
    }
    .setup-panel summary .chev {
      font-size: 12px;
      color: #6c757d;
      transition: transform 150ms ease;
    }
    .setup-panel[open] summary .chev {
      transform: rotate(180deg);
    }
    .setup-body {
      padding: 0.85rem;
      border-top: 1px solid var(--border-color);
      color: #495057;
      font-size: 0.82rem;
    }
    .setup-body h4 {
      margin: 0 0 8px 0;
      font-size: 0.82rem;
      color: #212529;
    }
    .setup-grid {
      display: grid;
      grid-template-columns: 1.2fr 1fr 1fr;
      gap: 0.62rem;
      margin-top: 0.52rem;
    }
    .setup-grid > div {
      padding: 0.62rem;
      border: 1px solid var(--border-color);
      border-radius: 0.52rem;
      background: #fff;
    }
    .setup-grid .head {
      font-size: 11px;
      letter-spacing: 0.03em;
      text-transform: uppercase;
      color: #6c757d;
      margin-bottom: 0.2rem;
      font-weight: 700;
    }
    .setup-note {
      margin-top: 0.62rem;
      color: #495057;
    }
    .mono-chip {
      display: inline-flex;
      margin-top: 2px;
      padding: 2px 6px;
      border-radius: 6px;
      background: #f8f9fa;
      border: 1px solid var(--border-color);
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 12px;
      color: #343a40;
      word-break: break-all;
    }
    .card:nth-of-type(1) { animation-delay: 30ms; }
    .card:nth-of-type(2) { animation-delay: 70ms; }
    .card:nth-of-type(3) { animation-delay: 110ms; }
    @keyframes fade-slide-in {
      from { opacity: 0; transform: translateY(8px); }
      to { opacity: 1; transform: translateY(0); }
    }
    @media (max-width: 960px) {
      .setup-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <div class="card mb-4">
      <div class="topbar">
      <div>
          <div class="brand-tag"><i class="bi bi-graph-up-arrow"></i> Internal Reporting</div>
          <div class="brand-title">{{ title }}</div>
          <div class="muted">CUPS usage, trend visibility, and monthly reporting</div>
      </div>
        <div class="nav">
          <a href="{{ url_for('dashboard') }}" class="{{ 'active' if current_path == url_for('dashboard') else '' }}">Dashboard</a>
          <a href="{{ url_for('users_page') }}" class="{{ 'active' if current_path == url_for('users_page') else '' }}">Users</a>
          <a href="{{ url_for('printers_page') }}" class="{{ 'active' if current_path == url_for('printers_page') else '' }}">Printers</a>
          <a href="{{ url_for('jobs_page') }}" class="{{ 'active' if current_path == url_for('jobs_page') else '' }}">Recent Jobs</a>
          <a href="{{ url_for('monthly_page') }}" class="{{ 'active' if current_path == url_for('monthly_page') else '' }}">Monthly</a>
          <a href="{{ url_for('rebuild_db') }}" class="{{ 'active' if current_path == url_for('rebuild_db') else '' }}">Rebuild DB</a>
        </div>
      </div>
      <details class="setup-panel">
        <summary>
          <span>Setup, Environment, and Accepted `page_log` Format</span>
          <span class="chev">&#9660;</span>
        </summary>
        <div class="setup-body">
          <h4>Expected CUPS `page_log` line structure</h4>
          <div>Required base tokens:</div>
          <div class="mono-chip">printer user job-id [DD/Mon/YYYY:HH:MM:SS -TZ]</div>
          <div class="setup-note">Accepted page-count variants:</div>
          <div class="mono-chip">... total PAGES [billing] [host] [job-name] [media] [sides]</div>
          <div class="mono-chip">... PAGES [billing] [host] [job-name] [media] [sides]</div>

          <div class="setup-note">Environment variables:</div>
          <div class="setup-grid">
            <div>
              <div class="head">Variable</div>
              <div class="mono">CUPS_PAGE_LOG</div>
              <div class="mono">CUPS_DASH_DB</div>
              <div class="mono">CUPS_DASH_HOST</div>
              <div class="mono">CUPS_DASH_PORT</div>
              <div class="mono">CUPS_DASH_DEBUG</div>
            </div>
            <div>
              <div class="head">Current</div>
              <div class="mono-chip">{{ current_page_log_path }}</div>
              <div class="mono-chip">{{ current_db_path }}</div>
              <div class="mono-chip">{{ current_host }}</div>
              <div class="mono-chip">{{ current_port }}</div>
              <div class="mono-chip">{{ '1' if current_debug else '0' }}</div>
            </div>
            <div>
              <div class="head">Default</div>
              <div class="mono-chip">{{ default_page_log_path }}</div>
              <div class="mono-chip">{{ default_db_path }}</div>
              <div class="mono-chip">{{ default_host }}</div>
              <div class="mono-chip">{{ default_port }}</div>
              <div class="mono-chip">{{ '1' if default_debug else '0' }}</div>
            </div>
          </div>
        </div>
      </details>
    </div>
    {{ body|safe }}
    <div class="footer">
      Source log: <span class="mono">{{ log_path }}</span> &nbsp; | &nbsp;
      SQLite cache: <span class="mono">{{ db_path }}</span>
    </div>
  </div>
</body>
</html>
"""


@dataclass
class JobRecord:
    printer: str
    user: str
    job_id: str
    timestamp: datetime
    pages: int
    impressions: int
    sheets: int
    billing: str
    host: str
    job_name: str
    media: str
    sides: str
    raw_line: str


def ensure_db_dir() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)


def get_db() -> sqlite3.Connection:
    ensure_db_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with closing(get_db()) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                printer TEXT NOT NULL,
                user_name TEXT NOT NULL,
                job_id TEXT NOT NULL,
                job_ts TEXT NOT NULL,
                year_month TEXT NOT NULL,
                pages INTEGER NOT NULL,
                impressions INTEGER NOT NULL DEFAULT 0,
                sheets INTEGER NOT NULL DEFAULT 0,
                billing TEXT,
                host TEXT,
                job_name TEXT,
                media TEXT,
                sides TEXT,
                raw_line TEXT NOT NULL,
                UNIQUE(raw_line)
            );

            CREATE INDEX IF NOT EXISTS idx_jobs_user ON jobs(user_name);
            CREATE INDEX IF NOT EXISTS idx_jobs_printer ON jobs(printer);
            CREATE INDEX IF NOT EXISTS idx_jobs_ym ON jobs(year_month);
            CREATE INDEX IF NOT EXISTS idx_jobs_ts ON jobs(job_ts);
            """
        )
        ensure_jobs_columns(conn)
        backfill_impressions_and_sheets(conn)
        repair_historical_rows(conn)
        conn.commit()


def parse_cups_date(value: str) -> Optional[datetime]:
    match = DATE_RE.match(value.strip())
    if not match:
        return None

    gd = match.groupdict()
    month = MONTHS.get(gd["mon"])
    if month is None:
        return None

    return datetime(
        year=int(gd["year"]),
        month=month,
        day=int(gd["day"]),
        hour=int(gd["hour"]),
        minute=int(gd["minute"]),
        second=int(gd["second"]),
    )


def parse_page_log_line(line: str) -> Optional[JobRecord]:
    line_text = line.rstrip("\n").strip()
    # Some deployments wrap the entire page_log entry in double quotes.
    if line_text.startswith('"') and line_text.endswith('"') and len(line_text) > 1:
        line_text = line_text[1:-1].strip()
    match = re.match(
        r'^\s*(?P<printer>\S+)\s+(?P<user>\S+)\s+(?P<job_id>\S+)\s+\[(?P<date>[^\]]+)\]\s*(?P<rest>.*)$',
        line_text,
    )
    if not match:
        return None

    printer = clean_token(match.group("printer"))
    user = clean_token(match.group("user"))
    job_id = clean_token(match.group("job_id"))
    date_str = f'[{match.group("date")}]'
    ts = parse_cups_date(date_str)
    if ts is None:
        return None

    rest = match.group("rest")
    try:
        tail_parts = shlex.split(rest) if rest else []
    except ValueError:
        tail_parts = rest.split() if rest else []

    # Support:
    # - total PAGES ...
    # - PAGES ...
    pages = 0
    idx = 0
    if tail_parts and clean_token(tail_parts[0]).lower() == "total":
        if len(tail_parts) > 1:
            pages = parse_int_token(tail_parts[1])
        idx = 2
    elif tail_parts:
        pages = parse_int_token(tail_parts[0])
        idx = 1

    billing = clean_token(tail_parts[idx]) if len(tail_parts) > idx else ""
    host = clean_token(tail_parts[idx + 1]) if len(tail_parts) > idx + 1 else ""
    job_name = clean_token(tail_parts[idx + 2]) if len(tail_parts) > idx + 2 else ""
    media = clean_token(tail_parts[idx + 3]) if len(tail_parts) > idx + 3 else ""
    sides = clean_token(tail_parts[idx + 4]) if len(tail_parts) > idx + 4 else ""
    extras = [clean_token(p) for p in tail_parts[idx + 5 :]] if len(tail_parts) > idx + 5 else []

    explicit_impressions = parse_explicit_impressions(extras)
    impressions = explicit_impressions if explicit_impressions is not None else pages
    sheets = estimate_sheets(impressions, sides)

    return JobRecord(
        printer=printer,
        user=user,
        job_id=job_id,
        timestamp=ts,
        pages=pages,
        impressions=impressions,
        sheets=sheets,
        billing=billing,
        host=host,
        job_name=job_name,
        media=media,
        sides=sides,
        raw_line=line_text,
    )


def clean_token(value: str) -> str:
    cleaned = value.strip()
    # Handle common malformed leading/trailing escapes and quotes from page_log tokens.
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


def h(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def parse_int_token(value: str) -> int:
    cleaned = clean_token(value)
    try:
        return int(cleaned)
    except ValueError:
        return 0


def parse_explicit_impressions(tokens: list[str]) -> Optional[int]:
    for token in tokens:
        lower = token.lower()
        for prefix in ("impressions=", "impression=", "impressions:", "impression:"):
            if lower.startswith(prefix):
                value = token[len(prefix):]
                parsed = parse_int_token(value)
                return parsed if parsed >= 0 else 0
    return None


def estimate_sheets(impressions: int, sides: str) -> int:
    if impressions <= 0:
        return 0
    sides_value = (sides or "").strip().lower()
    if "two-sided" in sides_value or "duplex" in sides_value:
        return (impressions + 1) // 2
    return impressions


def ensure_jobs_columns(conn: sqlite3.Connection) -> None:
    current = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    if "impressions" not in current:
        conn.execute("ALTER TABLE jobs ADD COLUMN impressions INTEGER NOT NULL DEFAULT 0")
    if "sheets" not in current:
        conn.execute("ALTER TABLE jobs ADD COLUMN sheets INTEGER NOT NULL DEFAULT 0")


def backfill_impressions_and_sheets(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        UPDATE jobs
        SET impressions = CASE
            WHEN impressions <= 0 THEN pages
            ELSE impressions
        END
        """
    )
    conn.execute(
        """
        UPDATE jobs
        SET sheets = CASE
            WHEN sheets <= 0 THEN
                CASE
                    WHEN lower(COALESCE(sides, '')) LIKE '%two-sided%'
                      OR lower(COALESCE(sides, '')) LIKE '%duplex%'
                    THEN CAST((impressions + 1) / 2 AS INTEGER)
                    ELSE impressions
                END
            ELSE sheets
        END
        """
    )
    # Extra normalization for legacy rows that may contain escaped quotes.
    conn.execute(
        """
        UPDATE jobs
        SET printer = TRIM(REPLACE(printer, '\\"', ''), '"'),
            user_name = TRIM(REPLACE(user_name, '\\"', ''), '"'),
            job_name = TRIM(REPLACE(job_name, '\\"', ''), '"'),
            media = TRIM(REPLACE(media, '\\"', ''), '"'),
            sides = TRIM(REPLACE(sides, '\\"', ''), '"')
        """
    )


def repair_historical_rows(conn: sqlite3.Connection) -> None:
    candidates = conn.execute(
        """
        SELECT id, raw_line
        FROM jobs
        WHERE printer LIKE '"%' OR printer LIKE '%"' OR printer LIKE '%\\"%'
           OR user_name LIKE '"%' OR user_name LIKE '%"' OR user_name LIKE '%\\"%'
           OR job_name LIKE '"%' OR job_name LIKE '%"' OR job_name LIKE '%\\"%'
           OR media LIKE '"%' OR media LIKE '%"' OR media LIKE '%\\"%'
           OR sides LIKE '"%' OR sides LIKE '%"' OR sides LIKE '%\\"%'
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
                rec.printer,
                rec.user,
                rec.job_id,
                rec.timestamp.isoformat(sep=" "),
                rec.timestamp.strftime("%Y-%m"),
                rec.pages,
                rec.impressions,
                rec.sheets,
                rec.billing,
                rec.host,
                rec.job_name,
                rec.media,
                rec.sides,
                row["id"],
            ),
        )

def import_page_log() -> tuple[int, int]:
    init_db()
    log_file = Path(PAGE_LOG_PATH)
    if not log_file.exists():
        raise FileNotFoundError(f"page_log not found: {PAGE_LOG_PATH}")

    inserted = 0
    skipped = 0

    with closing(get_db()) as conn, log_file.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            rec = parse_page_log_line(line)
            if rec is None:
                skipped += 1
                continue

            try:
                conn.execute(
                    """
                    INSERT INTO jobs (
                        printer, user_name, job_id, job_ts, year_month, pages, impressions, sheets,
                        billing, host, job_name, media, sides, raw_line
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rec.printer,
                        rec.user,
                        rec.job_id,
                        rec.timestamp.isoformat(sep=" "),
                        rec.timestamp.strftime("%Y-%m"),
                        rec.pages,
                        rec.impressions,
                        rec.sheets,
                        rec.billing,
                        rec.host,
                        rec.job_name,
                        rec.media,
                        rec.sides,
                        rec.raw_line,
                    ),
                )
                inserted += 1
            except sqlite3.IntegrityError:
                skipped += 1

        conn.commit()

    return inserted, skipped


def reset_and_reimport() -> tuple[int, int]:
    init_db()
    with closing(get_db()) as conn:
        conn.execute("DELETE FROM jobs")
        conn.commit()
    return import_page_log()


def scalar(query: str, params: tuple = ()) -> int:
    with closing(get_db()) as conn:
        row = conn.execute(query, params).fetchone()
        if not row:
            return 0
        value = row[0]
        return int(value or 0)


def rows(query: str, params: tuple = ()) -> list[sqlite3.Row]:
    with closing(get_db()) as conn:
        return list(conn.execute(query, params).fetchall())


def available_months() -> list[str]:
    result = rows("SELECT DISTINCT year_month FROM jobs ORDER BY year_month DESC")
    return [r[0] for r in result]


def current_month_fallback() -> str:
    months = available_months()
    return months[0] if months else datetime.now().strftime("%Y-%m")


def render_page(body: str, title: str = APP_TITLE):
    return render_template_string(
        BASE_TEMPLATE,
        body=body,
        title=title,
        log_path=PAGE_LOG_PATH,
        db_path=DB_PATH,
        current_path=request.path,
        current_page_log_path=PAGE_LOG_PATH,
        current_db_path=DB_PATH,
        current_host=HOST,
        current_port=PORT,
        current_debug=DEBUG,
        default_page_log_path=DEFAULT_PAGE_LOG_PATH,
        default_db_path=DEFAULT_DB_PATH,
        default_host=DEFAULT_HOST,
        default_port=DEFAULT_PORT,
        default_debug=DEFAULT_DEBUG,
    )


def month_filter_form(selected_month: str) -> str:
    options = []
    for m in available_months():
        sel = "selected" if m == selected_month else ""
        options.append(f'<option value="{h(m)}" {sel}>{h(m)}</option>')
    if not options:
        options.append(f'<option value="{h(selected_month)}" selected>{h(selected_month)}</option>')
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


@app.before_request
def startup_once() -> None:
    global STARTUP_INIT_DONE
    if STARTUP_INIT_DONE:
        return
    with STARTUP_LOCK:
        if STARTUP_INIT_DONE:
            return
        init_db()
        if Path(PAGE_LOG_PATH).exists():
            import_page_log()
        STARTUP_INIT_DONE = True


@app.route("/")
def dashboard():
    month = request.args.get("month", current_month_fallback())

    total_pages = scalar("SELECT COALESCE(SUM(pages),0) FROM jobs WHERE year_month = ?", (month,))
    total_impressions = scalar("SELECT COALESCE(SUM(impressions),0) FROM jobs WHERE year_month = ?", (month,))
    total_sheets = scalar("SELECT COALESCE(SUM(sheets),0) FROM jobs WHERE year_month = ?", (month,))
    total_jobs = scalar("SELECT COUNT(*) FROM jobs WHERE year_month = ?", (month,))
    unique_users = scalar("SELECT COUNT(DISTINCT user_name) FROM jobs WHERE year_month = ?", (month,))
    unique_printers = scalar("SELECT COUNT(DISTINCT printer) FROM jobs WHERE year_month = ?", (month,))

    top_users = rows(
        """
        SELECT user_name, COUNT(*) AS jobs, COALESCE(SUM(pages),0) AS pages,
               COALESCE(SUM(impressions),0) AS impressions,
               COALESCE(SUM(sheets),0) AS sheets
        FROM jobs WHERE year_month = ?
        GROUP BY user_name
        ORDER BY impressions DESC, jobs DESC, user_name ASC
        LIMIT 10
        """,
        (month,),
    )
    top_printers = rows(
        """
        SELECT printer, COUNT(*) AS jobs, COALESCE(SUM(pages),0) AS pages,
               COALESCE(SUM(impressions),0) AS impressions,
               COALESCE(SUM(sheets),0) AS sheets
        FROM jobs WHERE year_month = ?
        GROUP BY printer
        ORDER BY impressions DESC, jobs DESC, printer ASC
        LIMIT 10
        """,
        (month,),
    )
    recent = rows(
        """
        SELECT printer, user_name, job_name, pages, impressions, sheets, job_ts
        FROM jobs
        ORDER BY job_ts DESC
        LIMIT 10
        """
    )

    body = month_filter_form(month) + f"""
    <div class="grid">
      <div class="card metric-card"><div class="muted">Month</div><div class="metric">{h(month)}</div></div>
      <div class="card metric-card"><div class="muted">Impressions</div><div class="metric">{total_impressions}</div></div>
      <div class="card metric-card"><div class="muted">Sheets (Est.)</div><div class="metric">{total_sheets}</div></div>
      <div class="card metric-card"><div class="muted">Pages</div><div class="metric">{total_pages}</div></div>
      <div class="card metric-card"><div class="muted">Jobs</div><div class="metric">{total_jobs}</div></div>
      <div class="card metric-card"><div class="muted">Users</div><div class="metric">{unique_users}</div></div>
      <div class="card metric-card"><div class="muted">Printers</div><div class="metric">{unique_printers}</div></div>
    </div>

    <div class="two-col">
      <div class="card">
        <h2>Top Users <span class="pill">{h(month)}</span></h2>
        <div class="table-wrap">
          <table>
            <tr><th>User</th><th>Jobs</th><th>Impressions</th><th>Sheets</th><th>Pages</th></tr>
            {''.join(f'<tr><td><a href="{url_for("users_page", month=month, user=r["user_name"])}">{h(r["user_name"])}</a></td><td>{r["jobs"]}</td><td>{r["impressions"]}</td><td>{r["sheets"]}</td><td>{r["pages"]}</td></tr>' for r in top_users)}
          </table>
        </div>
      </div>
      <div class="card">
        <h2>Top Printers <span class="pill">{h(month)}</span></h2>
        <div class="table-wrap">
          <table>
            <tr><th>Printer</th><th>Jobs</th><th>Impressions</th><th>Sheets</th><th>Pages</th></tr>
            {''.join(f'<tr><td><a href="{url_for("printers_page", month=month, printer=r["printer"])}">{h(r["printer"])}</a></td><td>{r["jobs"]}</td><td>{r["impressions"]}</td><td>{r["sheets"]}</td><td>{r["pages"]}</td></tr>' for r in top_printers)}
          </table>
        </div>
      </div>
    </div>

    <div class="card">
      <h2>Recent Jobs</h2>
      <div class="table-wrap">
        <table>
          <tr><th>Time</th><th>User</th><th>Printer</th><th>Job Name</th><th>Impressions</th><th>Sheets</th><th>Pages</th></tr>
          {''.join(f'<tr><td>{h(r["job_ts"])}</td><td>{h(r["user_name"])}</td><td>{h(r["printer"])}</td><td>{h(r["job_name"] or "-")}</td><td>{r["impressions"]}</td><td>{r["sheets"]}</td><td>{r["pages"]}</td></tr>' for r in recent)}
        </table>
      </div>
    </div>
    """
    return render_page(body)


@app.route("/users")
def users_page():
    month = request.args.get("month", current_month_fallback())
    user = clean_token(request.args.get("user", ""))

    summary_query = """
        SELECT user_name, COUNT(*) AS jobs, COALESCE(SUM(pages),0) AS pages,
               COALESCE(SUM(impressions),0) AS impressions,
               COALESCE(SUM(sheets),0) AS sheets
        FROM jobs
        WHERE year_month = ?
    """
    summary_params: tuple = (month,)
    if user:
        summary_query += " AND user_name = ?"
        summary_params = (month, user)
    summary_query += """
        GROUP BY user_name
        ORDER BY impressions DESC, jobs DESC, user_name ASC
    """
    summary = rows(summary_query, summary_params)

    detail = []
    if user:
        detail = rows(
            """
            SELECT job_ts, printer, job_name, pages, impressions, sheets, media, sides
            FROM jobs
            WHERE year_month = ? AND user_name = ?
            ORDER BY job_ts DESC
            LIMIT 100
            """,
            (month, user),
        )

    body = month_filter_form(month) + f"""
    <div class="card">
      <h2>Usage by User <span class="pill">{h(month)}</span></h2>
      <a class="action-link" href="{url_for('export_users_csv', month=month)}">Export CSV</a>
      {'<div class="muted">Filtered by user: <span class="mono-chip">' + h(user) + '</span> &nbsp; <a href="' + url_for("users_page", month=month) + '">Clear</a></div>' if user else ''}
      <div class="table-wrap">
        <table>
          <tr><th>User</th><th>Jobs</th><th>Impressions</th><th>Sheets</th><th>Pages</th></tr>
          {''.join(f'<tr><td><a href="{url_for("users_page", month=month, user=r["user_name"])}">{h(r["user_name"])}</a></td><td>{r["jobs"]}</td><td>{r["impressions"]}</td><td>{r["sheets"]}</td><td>{r["pages"]}</td></tr>' for r in summary)}
        </table>
      </div>
    </div>
    """

    if user:
        body += f"""
        <div class="card">
          <h2>Recent Jobs for {h(user)}</h2>
          <div class="table-wrap">
            <table>
              <tr><th>Time</th><th>Printer</th><th>Job Name</th><th>Impressions</th><th>Sheets</th><th>Pages</th><th>Media</th><th>Sides</th></tr>
              {''.join(f'<tr><td>{h(r["job_ts"])}</td><td>{h(r["printer"])}</td><td>{h(r["job_name"] or "-")}</td><td>{r["impressions"]}</td><td>{r["sheets"]}</td><td>{r["pages"]}</td><td>{h(r["media"] or "-")}</td><td>{h(r["sides"] or "-")}</td></tr>' for r in detail)}
            </table>
          </div>
        </div>
        """

    return render_page(body)


@app.route("/printers")
def printers_page():
    month = request.args.get("month", current_month_fallback())
    printer = clean_token(request.args.get("printer", ""))

    summary_query = """
        SELECT printer, COUNT(*) AS jobs, COALESCE(SUM(pages),0) AS pages,
               COALESCE(SUM(impressions),0) AS impressions,
               COALESCE(SUM(sheets),0) AS sheets
        FROM jobs
        WHERE year_month = ?
    """
    summary_params: tuple = (month,)
    if printer:
        summary_query += " AND printer = ?"
        summary_params = (month, printer)
    summary_query += """
        GROUP BY printer
        ORDER BY impressions DESC, jobs DESC, printer ASC
    """
    summary = rows(summary_query, summary_params)

    detail = []
    if printer:
        detail = rows(
            """
            SELECT job_ts, user_name, job_name, pages, impressions, sheets, media, sides
            FROM jobs
            WHERE year_month = ? AND printer = ?
            ORDER BY job_ts DESC
            LIMIT 100
            """,
            (month, printer),
        )

    body = month_filter_form(month) + f"""
    <div class="card">
      <h2>Usage by Printer <span class="pill">{h(month)}</span></h2>
      <a class="action-link" href="{url_for('export_printers_csv', month=month)}">Export CSV</a>
      {'<div class="muted">Filtered by printer: <span class="mono-chip">' + h(printer) + '</span> &nbsp; <a href="' + url_for("printers_page", month=month) + '">Clear</a></div>' if printer else ''}
      <div class="table-wrap">
        <table>
          <tr><th>Printer</th><th>Jobs</th><th>Impressions</th><th>Sheets</th><th>Pages</th></tr>
          {''.join(f'<tr><td><a href="{url_for("printers_page", month=month, printer=r["printer"])}">{h(r["printer"])}</a></td><td>{r["jobs"]}</td><td>{r["impressions"]}</td><td>{r["sheets"]}</td><td>{r["pages"]}</td></tr>' for r in summary)}
        </table>
      </div>
    </div>
    """

    if printer:
        body += f"""
        <div class="card">
          <h2>Recent Jobs for {h(printer)}</h2>
          <div class="table-wrap">
            <table>
              <tr><th>Time</th><th>User</th><th>Job Name</th><th>Impressions</th><th>Sheets</th><th>Pages</th><th>Media</th><th>Sides</th></tr>
              {''.join(f'<tr><td>{h(r["job_ts"])}</td><td>{h(r["user_name"])}</td><td>{h(r["job_name"] or "-")}</td><td>{r["impressions"]}</td><td>{r["sheets"]}</td><td>{r["pages"]}</td><td>{h(r["media"] or "-")}</td><td>{h(r["sides"] or "-")}</td></tr>' for r in detail)}
            </table>
          </div>
        </div>
        """

    return render_page(body)


@app.route("/jobs")
def jobs_page():
    month = request.args.get("month", "").strip()
    if month:
        recent = rows(
            """
            SELECT job_ts, user_name, printer, job_name, pages, impressions, sheets, media, sides, host
            FROM jobs
            WHERE year_month = ?
            ORDER BY job_ts DESC
            LIMIT 250
            """,
            (month,),
        )
    else:
        recent = rows(
            """
            SELECT job_ts, user_name, printer, job_name, pages, impressions, sheets, media, sides, host
            FROM jobs
            ORDER BY job_ts DESC
            LIMIT 250
            """
        )

    body = month_filter_form(month or current_month_fallback()) + f"""
    <div class="card">
      <h2>Recent Jobs {'<span class="pill">' + h(month) + '</span>' if month else ''}</h2>
      <div class="table-wrap">
        <table>
          <tr><th>Time</th><th>User</th><th>Printer</th><th>Job Name</th><th>Impressions</th><th>Sheets</th><th>Pages</th><th>Media</th><th>Sides</th><th>Host</th></tr>
          {''.join(f'<tr><td>{h(r["job_ts"])}</td><td>{h(r["user_name"])}</td><td>{h(r["printer"])}</td><td>{h(r["job_name"] or "-")}</td><td>{r["impressions"]}</td><td>{r["sheets"]}</td><td>{r["pages"]}</td><td>{h(r["media"] or "-")}</td><td>{h(r["sides"] or "-")}</td><td>{h(r["host"] or "-")}</td></tr>' for r in recent)}
        </table>
      </div>
    </div>
    """
    return render_page(body)


@app.route("/monthly")
def monthly_page():
    monthly = rows(
        """
        SELECT year_month, COUNT(*) AS jobs, COALESCE(SUM(pages),0) AS pages,
               COALESCE(SUM(impressions),0) AS impressions,
               COALESCE(SUM(sheets),0) AS sheets,
               COUNT(DISTINCT user_name) AS users,
               COUNT(DISTINCT printer) AS printers
        FROM jobs
        GROUP BY year_month
        ORDER BY year_month DESC
        """
    )
    body = f"""
    <div class="card">
      <h2>Monthly Totals</h2>
      <a class="action-link" href="{url_for('export_monthly_csv')}">Export CSV</a>
      <div class="table-wrap">
        <table>
          <tr><th>Month</th><th>Jobs</th><th>Impressions</th><th>Sheets</th><th>Pages</th><th>Users</th><th>Printers</th></tr>
          {''.join(f'<tr><td><a href="{url_for("dashboard", month=r["year_month"])}">{h(r["year_month"])}</a></td><td>{r["jobs"]}</td><td>{r["impressions"]}</td><td>{r["sheets"]}</td><td>{r["pages"]}</td><td>{r["users"]}</td><td>{r["printers"]}</td></tr>' for r in monthly)}
        </table>
      </div>
    </div>
    """
    return render_page(body)


@app.route("/rebuild", methods=["GET", "POST"])
def rebuild_db():
    if request.method == "GET":
        return render_page(
            f"""
            <div class="card">
              <h2>Rebuild Database</h2>
              <p class="muted">This clears current cached rows and re-imports from <span class="mono">{h(PAGE_LOG_PATH)}</span>.</p>
              <form method="post">
                <button type="submit">Confirm Rebuild</button>
                <a class="action-link" href="{url_for('dashboard')}">Cancel</a>
              </form>
            </div>
            """
        )

    inserted, skipped = reset_and_reimport()
    return render_page(
        f"""
        <div class="card">
          <h2>Database Rebuilt</h2>
          <p class="muted">Inserted: <strong>{inserted}</strong></p>
          <p class="muted">Skipped: <strong>{skipped}</strong></p>
          <p><a href="{url_for('dashboard')}">Return to dashboard</a></p>
        </div>
        """
    )


def csv_response(filename: str, header: list[str], data_rows: Iterable[Iterable]):
    def generate():
        yield ",".join(header) + "\n"
        for row in data_rows:
            escaped = []
            for item in row:
                text = "" if item is None else str(item)
                if any(ch in text for ch in [',', '"', '\n']):
                    text = '"' + text.replace('"', '""') + '"'
                escaped.append(text)
            yield ",".join(escaped) + "\n"

    return Response(
        generate(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.route("/export/users.csv")
def export_users_csv():
    month = request.args.get("month", current_month_fallback())
    result = rows(
        """
        SELECT user_name, COUNT(*) AS jobs, COALESCE(SUM(pages),0) AS pages,
               COALESCE(SUM(impressions),0) AS impressions,
               COALESCE(SUM(sheets),0) AS sheets
        FROM jobs WHERE year_month = ?
        GROUP BY user_name
        ORDER BY impressions DESC, jobs DESC, user_name ASC
        """,
        (month,),
    )
    return csv_response(
        f"cups_users_{month}.csv",
        ["user", "jobs", "impressions", "sheets", "pages"],
        ((r["user_name"], r["jobs"], r["impressions"], r["sheets"], r["pages"]) for r in result),
    )


@app.route("/export/printers.csv")
def export_printers_csv():
    month = request.args.get("month", current_month_fallback())
    result = rows(
        """
        SELECT printer, COUNT(*) AS jobs, COALESCE(SUM(pages),0) AS pages,
               COALESCE(SUM(impressions),0) AS impressions,
               COALESCE(SUM(sheets),0) AS sheets
        FROM jobs WHERE year_month = ?
        GROUP BY printer
        ORDER BY impressions DESC, jobs DESC, printer ASC
        """,
        (month,),
    )
    return csv_response(
        f"cups_printers_{month}.csv",
        ["printer", "jobs", "impressions", "sheets", "pages"],
        ((r["printer"], r["jobs"], r["impressions"], r["sheets"], r["pages"]) for r in result),
    )


@app.route("/export/monthly.csv")
def export_monthly_csv():
    result = rows(
        """
        SELECT year_month, COUNT(*) AS jobs, COALESCE(SUM(pages),0) AS pages,
               COALESCE(SUM(impressions),0) AS impressions,
               COALESCE(SUM(sheets),0) AS sheets,
               COUNT(DISTINCT user_name) AS users,
               COUNT(DISTINCT printer) AS printers
        FROM jobs
        GROUP BY year_month
        ORDER BY year_month DESC
        """
    )
    return csv_response(
        "cups_monthly.csv",
        ["month", "jobs", "impressions", "sheets", "pages", "users", "printers"],
        (
            (r["year_month"], r["jobs"], r["impressions"], r["sheets"], r["pages"], r["users"], r["printers"])
            for r in result
        ),
    )


if __name__ == "__main__":
    STARTUP_INIT_DONE = False
    init_db()
    if Path(PAGE_LOG_PATH).exists():
        import_page_log()
    STARTUP_INIT_DONE = True
    app.run(host=HOST, port=PORT, debug=DEBUG)
