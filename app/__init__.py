"""CUPS Dashboard — Flask application factory."""
from __future__ import annotations

import os
import secrets
import threading
from pathlib import Path

from flask import Flask

from .config import DB_PATH, DEBUG, HOST, LOG_REFRESH_SECS, PAGE_LOG_PATH, PORT

_STARTUP_DONE = False
_STARTUP_LOCK = threading.Lock()


def _load_or_create_secret_key() -> str:
    """Persist a stable HMAC secret key next to the DB file for stable sessions."""
    key_file = Path(DB_PATH).parent / ".cups_dash_secret"
    try:
        key_file.parent.mkdir(parents=True, exist_ok=True)
        if key_file.exists():
            key = key_file.read_text().strip()
            if len(key) >= 32:
                return key
        key = secrets.token_hex(32)
        key_file.write_text(key)
        try:
            key_file.chmod(0o600)
        except OSError:
            pass
        return key
    except OSError:
        return secrets.token_hex(32)  # ephemeral fallback


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = os.environ.get("CUPS_DASH_SECRET_KEY") or _load_or_create_secret_key()

    # Register blueprints
    from .routes.main import bp as main_bp
    from .routes.users import bp as users_bp
    from .routes.printers import bp as printers_bp
    from .routes.jobs import bp as jobs_bp
    from .routes.settings import bp as settings_bp
    from .routes.admin import bp as admin_bp

    for blueprint in (main_bp, users_bp, printers_bp, jobs_bp, settings_bp, admin_bp):
        app.register_blueprint(blueprint)

    @app.before_request
    def _startup_once():
        global _STARTUP_DONE
        if _STARTUP_DONE:
            return
        with _STARTUP_LOCK:
            if _STARTUP_DONE:
                return
            from .db import init_db
            from .importer import _IMPORT_LOCK, _start_bg_refresh, import_page_log_incremental

            init_db()
            if Path(PAGE_LOG_PATH).exists():
                with _IMPORT_LOCK:
                    import_page_log_incremental()
            _start_bg_refresh()
            _STARTUP_DONE = True

    return app


app = create_app()
