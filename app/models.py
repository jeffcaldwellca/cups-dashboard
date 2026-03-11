"""
Domain models and log-parsing constants.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

MONTHS: dict[str, int] = {
    "Jan": 1, "Feb": 2, "Mar": 3,  "Apr": 4,
    "May": 5, "Jun": 6, "Jul": 7,  "Aug": 8,
    "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

DATE_RE = re.compile(
    r"^\[(?P<day>\d{1,2})/(?P<mon>[A-Za-z]{3})/(?P<year>\d{4}):"
    r"(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})"
    r"(?:\s+(?P<offset>[+-]\d{4}|[A-Za-z_/\-+]+))?\]$"
)


@dataclass
class JobRecord:
    printer:    str
    user:       str
    job_id:     str
    timestamp:  datetime
    pages:      int
    impressions: int
    sheets:     int
    billing:    str
    host:       str
    job_name:   str
    media:      str
    sides:      str
    color_mode: str
    raw_line:   str
