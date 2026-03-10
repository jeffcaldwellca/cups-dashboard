"""
Application-wide configuration — all constants and environment variable reads.
"""
from __future__ import annotations

import os
from pathlib import Path

APP_TITLE = "PaperTrail"

DEFAULT_PAGE_LOG_PATH = "/var/log/cups/page_log"
DEFAULT_DB_PATH       = "./cups_dashboard.db"
DEFAULT_HOST          = "0.0.0.0"
DEFAULT_PORT          = 962
DEFAULT_DEBUG         = False
DEFAULT_LOG_REFRESH   = 300

PAGE_LOG_PATH    = os.environ.get("CUPS_PAGE_LOG",   DEFAULT_PAGE_LOG_PATH)
DB_PATH          = os.environ.get("CUPS_DASH_DB",    DEFAULT_DB_PATH)
HOST             = os.environ.get("CUPS_DASH_HOST",  DEFAULT_HOST)
PORT             = int(os.environ.get("CUPS_DASH_PORT",    str(DEFAULT_PORT)))
DEBUG            = os.environ.get("CUPS_DASH_DEBUG", "1" if DEFAULT_DEBUG else "0") == "1"
LOG_REFRESH_SECS = int(os.environ.get("CUPS_LOG_REFRESH", str(DEFAULT_LOG_REFRESH)))

# SSL certificate storage (next to the DB file)
_SSL_DIR      = Path(DB_PATH).parent / "ssl"
SSL_CERT_PATH = str(_SSL_DIR / "server.crt")
SSL_KEY_PATH  = str(_SSL_DIR / "server.key")
