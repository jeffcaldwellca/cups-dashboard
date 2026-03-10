#!/usr/bin/env python3
"""
PaperTrail for CUPS — entrypoint.

All application logic lives in the app/ package.
Run directly:  python3 dashboard.py
Or via Flask:  flask --app dashboard:app run
"""
import os

from app import app  # noqa: F401  (also exposes `app` for `flask run`)
from app.config import DEBUG, HOST, PORT, SSL_CERT_PATH, SSL_KEY_PATH

if __name__ == "__main__":
    ssl_ctx = (
        (SSL_CERT_PATH, SSL_KEY_PATH)
        if os.path.exists(SSL_CERT_PATH) and os.path.exists(SSL_KEY_PATH)
        else None
    )
    if ssl_ctx:
        print(f"[PaperTrail] HTTPS enabled — using certificate at {SSL_CERT_PATH}")
    app.run(host=HOST, port=PORT, debug=DEBUG, ssl_context=ssl_ctx)
