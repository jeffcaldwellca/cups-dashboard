"""
render_page() — wraps a content body string in the base template.
"""
from __future__ import annotations

import os

from flask import render_template, request

from .config import (
    APP_TITLE, DB_PATH, DEBUG, DEFAULT_DB_PATH, DEFAULT_DEBUG,
    DEFAULT_HOST, DEFAULT_PAGE_LOG_PATH, DEFAULT_PORT,
    HOST, LOG_REFRESH_SECS, PAGE_LOG_PATH, PORT,
)
from .db import get_ad_config
from .utils import last_import_time


def render_page(body: str, title: str = APP_TITLE, status: int = 200):
    ad_cfg = get_ad_config()
    return render_template(
        "base.html",
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
        ad_enabled=bool(ad_cfg.get("enabled")),
        ad_bind_pw_env=bool(os.environ.get("CUPS_AD_BIND_PASSWORD")),
        last_import=last_import_time(),
        log_refresh_secs=LOG_REFRESH_SECS,
    ), status
