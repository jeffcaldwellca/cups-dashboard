import json
import os
import secrets
import ssl as _ssl
import subprocess
import tempfile

from contextlib import closing
from pathlib import Path
from flask import Blueprint, jsonify, render_template, request, session

from ..ad import enrich_users_from_ad, test_ad_connection
from ..config import SSL_CERT_PATH, SSL_KEY_PATH
from ..db import get_ad_config, get_db, set_config
from ..renderer import render_page
from ..utils import csrf_token, verify_csrf

bp = Blueprint("settings", __name__)

_MAX_CERT_BYTES = 65_536  # 64 KB — more than enough for any real PEM cert/key


# ── AD settings ───────────────────────────────────────────────────────────────

@bp.route("/settings", methods=["GET", "POST"])
def settings_page():
    save_ok = None
    save_msg = ""
    cfg = get_ad_config()

    if request.method == "POST":
        if not verify_csrf():
            return render_page(
                "<p class='alert alert-danger'>Invalid CSRF token.</p>",
                "Settings",
                status=400,
            )

        new_cfg = {
            "enabled":           "ad_enabled"       in request.form,
            "server":            request.form.get("ad_server",          "").strip(),
            "port":              int(request.form.get("ad_port",        389) or 389),
            "use_ssl":           "use_ssl"           in request.form,
            "verify_ssl":        "verify_ssl"        in request.form,
            "auth_method":       "simple",
            "bind_dn":           request.form.get("bind_dn",            "").strip(),
            "base_dn":           request.form.get("base_dn",            "").strip(),
            "user_search_base":  request.form.get("user_search_base",   "").strip(),
            "username_attr":     request.form.get("username_attr",      "sAMAccountName").strip(),
            "display_name_attr": request.form.get("display_name_attr",  "displayName").strip(),
            "email_attr":        request.form.get("email_attr",         "mail").strip(),
            "department_attr":   request.form.get("department_attr",    "department").strip(),
            "title_attr":        request.form.get("title_attr",         "title").strip(),
            "cache_ttl_hours":   int(request.form.get("cache_ttl_hours", 24) or 24),
        }

        pw = request.form.get("bind_password", "").strip()
        env_pw = os.environ.get("CUPS_AD_BIND_PASSWORD", "")
        if env_pw:
            new_cfg["bind_password"] = env_pw
        elif pw:
            new_cfg["bind_password"] = pw
        else:
            new_cfg["bind_password"] = cfg.get("bind_password", "")

        try:
            set_config("ad_config", json.dumps(new_cfg))
            save_ok = True
            save_msg = "Settings saved successfully."
            cfg = new_cfg
        except Exception as exc:
            save_ok = False
            save_msg = f"Error saving settings: {exc}"

    body = render_template(
        "settings_form.html",
        cfg=cfg,
        csrf_token=csrf_token(),
        ad_bind_pw_env=bool(os.environ.get("CUPS_AD_BIND_PASSWORD")),
        save_ok=save_ok,
        save_msg=save_msg,
    )
    return render_page(body, "Settings")


@bp.route("/settings/test-ad", methods=["POST"])
def test_ad_route():
    data = request.get_json(silent=True) or {}
    if not secrets.compare_digest(
        str(data.get("csrf_token", "")),
        str(session.get("csrf_token", "")),
    ):
        return jsonify({"success": False, "message": "Invalid CSRF token."}), 403
    cfg = get_ad_config()
    ok, msg = test_ad_connection(cfg)
    return jsonify({"success": ok, "message": msg})


@bp.route("/settings/sync-ad", methods=["POST"])
def sync_ad_route():
    data = request.get_json(silent=True) or {}
    if not secrets.compare_digest(
        str(data.get("csrf_token", "")),
        str(session.get("csrf_token", "")),
    ):
        return jsonify({"success": False, "message": "Invalid CSRF token."}), 403
    try:
        with closing(get_db()) as conn:
            users = [
                r["user_name"]
                for r in conn.execute(
                    "SELECT DISTINCT user_name FROM jobs WHERE user_name IS NOT NULL"
                ).fetchall()
            ]
        enrich_users_from_ad(users)
        return jsonify({"success": True, "message": f"Sync triggered for {len(users)} users."})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)})

# ── SSL certificate management ────────────────────────────────────────────────

@bp.route("/settings/ssl-status")
def ssl_status_route():
    cert_path = Path(SSL_CERT_PATH)
    key_path  = Path(SSL_KEY_PATH)
    if not cert_path.exists() or not key_path.exists():
        return jsonify({"present": False})

    expiry = None
    try:
        result = subprocess.run(
            ["openssl", "x509", "-noout", "-enddate", "-in", str(cert_path)],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            # stdout: "notAfter=Mar  9 12:00:00 2027 GMT"
            expiry = result.stdout.strip().removeprefix("notAfter=")
    except Exception:
        pass

    return jsonify({"present": True, "expiry": expiry})


@bp.route("/settings/upload-ssl", methods=["POST"])
def upload_ssl():
    token = request.form.get("csrf_token", "")
    if not secrets.compare_digest(str(token), str(session.get("csrf_token", ""))):
        return jsonify({"success": False, "message": "Invalid CSRF token."}), 403

    cert_file = request.files.get("ssl_cert")
    key_file  = request.files.get("ssl_key")
    if not cert_file or not key_file:
        return jsonify({"success": False, "message": "Both certificate and key files are required."})

    cert_data = cert_file.read(_MAX_CERT_BYTES + 1)
    key_data  = key_file.read(_MAX_CERT_BYTES + 1)

    if len(cert_data) > _MAX_CERT_BYTES or len(key_data) > _MAX_CERT_BYTES:
        return jsonify({"success": False, "message": "File exceeds 64 KB limit."})

    if b"-----BEGIN CERTIFICATE-----" not in cert_data:
        return jsonify({"success": False,
                        "message": "Certificate does not appear to be a valid PEM certificate."})
    if b"PRIVATE KEY-----" not in key_data:
        return jsonify({"success": False,
                        "message": "Key does not appear to be a valid PEM private key."})

    # Validate that cert + key are a matching pair using a temp context
    tmp_cert = tmp_key = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".crt", delete=False) as tf:
            tf.write(cert_data)
            tmp_cert = tf.name
        with tempfile.NamedTemporaryFile(suffix=".key", delete=False) as tf:
            tf.write(key_data)
            tmp_key = tf.name

        ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(tmp_cert, tmp_key)  # raises ssl.SSLError if mismatch
    except _ssl.SSLError as exc:
        return jsonify({"success": False,
                        "message": f"Certificate/key validation failed: {exc}"})
    except Exception as exc:
        return jsonify({"success": False, "message": f"Unexpected error: {exc}"})
    finally:
        for p in (tmp_cert, tmp_key):
            if p and os.path.exists(p):
                os.unlink(p)

    # Save the validated files
    ssl_dir = Path(SSL_CERT_PATH).parent
    ssl_dir.mkdir(parents=True, exist_ok=True)

    Path(SSL_CERT_PATH).write_bytes(cert_data)
    Path(SSL_KEY_PATH).write_bytes(key_data)
    try:
        Path(SSL_CERT_PATH).chmod(0o644)
        Path(SSL_KEY_PATH).chmod(0o600)
    except OSError:
        pass

    return jsonify({"success": True,
                    "message": "Certificate and key saved. Restart the server to apply HTTPS."})


@bp.route("/settings/remove-ssl", methods=["POST"])
def remove_ssl():
    data = request.get_json(silent=True) or {}
    if not secrets.compare_digest(str(data.get("csrf_token", "")),
                                   str(session.get("csrf_token", ""))):
        return jsonify({"success": False, "message": "Invalid CSRF token."}), 403

    removed = []
    for path_str in (SSL_CERT_PATH, SSL_KEY_PATH):
        p = Path(path_str)
        if p.exists():
            p.unlink()
            removed.append(p.name)

    if removed:
        return jsonify({"success": True,
                        "message": f"Removed: {', '.join(removed)}. Restart to revert to HTTP."})
    return jsonify({"success": False, "message": "No certificate files found to remove."})
