"""
Active Directory / LDAP integration.

All LDAP calls via ldap3 (optional soft dependency).  If ldap3 is not
installed, AD-enrichment functions degrade gracefully.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import closing
from datetime import datetime
from typing import Optional

try:
    from ldap3 import ALL, NTLM, SIMPLE, SUBTREE, Connection, Server, Tls  # type: ignore
    LDAP3_AVAILABLE = True
except ImportError:
    LDAP3_AVAILABLE = False

from .db import get_db, get_ad_config

# ─── LDAP helpers ──────────────────────────────────────────────────────────────

def _ldap_escape(value: str) -> str:
    """Escape LDAP filter special characters per RFC 4515."""
    for ch, esc in [
        ("\\", "\\5c"), ("*",  "\\2a"),
        ("(",  "\\28"), (")",  "\\29"), ("\x00", "\\00"),
    ]:
        value = value.replace(ch, esc)
    return value


def _build_ldap_server(cfg: dict):
    use_ssl = bool(cfg.get("use_ssl"))
    port    = int(cfg.get("port", 636 if use_ssl else 389))
    tls_obj = None
    if use_ssl or cfg.get("verify_ssl"):
        import ssl as _ssl
        tls_obj = Tls(
            validate=_ssl.CERT_REQUIRED if cfg.get("verify_ssl") else _ssl.CERT_NONE
        )
    return Server(cfg["server"], port=port, use_ssl=use_ssl,
                  tls=tls_obj, get_info=ALL, connect_timeout=5)


def _build_ldap_conn(server, cfg: dict):
    bind_pw = os.environ.get("CUPS_AD_BIND_PASSWORD") or cfg.get("bind_password", "")
    auth    = NTLM if cfg.get("auth_method") == "ntlm" else SIMPLE
    return Connection(
        server,
        user=cfg.get("bind_dn", ""),
        password=bind_pw,
        authentication=auth,
        auto_bind=True,
        receive_timeout=15,
    )


def _get_ldap_attr(entry, attr: str) -> str:
    try:
        v = entry[attr].value
        return str(v) if v is not None else ""
    except Exception:  # noqa: BLE001
        return ""

# ─── Public API ────────────────────────────────────────────────────────────────

def test_ad_connection(cfg: dict) -> tuple[bool, str]:
    """Try to bind and do a sample search. Returns (ok, message)."""
    if not LDAP3_AVAILABLE:
        return False, (
            "ldap3 is not installed. Add it to requirements.txt and rebuild "
            "(or run: pip install ldap3 in your virtual environment)."
        )
    if not cfg.get("server") or not cfg.get("base_dn"):
        return False, "Server URL and Base DN are required."
    try:
        server = _build_ldap_server(cfg)
        conn   = _build_ldap_conn(server, cfg)
        search_base = cfg.get("user_search_base") or cfg["base_dn"]
        ua = cfg.get("username_attr", "sAMAccountName")
        conn.search(search_base, "(objectClass=user)", SUBTREE,
                    attributes=[ua], size_limit=5)
        found = len(conn.entries)
        conn.unbind()
        return True, (
            f"Connection successful — bound as {cfg.get('bind_dn', '(anonymous)')}. "
            f"Search base accessible ({found} sample result(s) returned)."
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"Connection failed: {exc}"


def _ad_lookup_batch(usernames: list[str], cfg: dict) -> dict[str, dict]:
    """Look up multiple users in one LDAP session. Returns {lower(sam): info_dict}."""
    if not LDAP3_AVAILABLE or not usernames:
        return {}
    try:
        server = _build_ldap_server(cfg)
        conn   = _build_ldap_conn(server, cfg)
        search_base = cfg.get("user_search_base") or cfg["base_dn"]
        ua  = cfg.get("username_attr",     "sAMAccountName")
        dna = cfg.get("display_name_attr", "displayName")
        ea  = cfg.get("email_attr",        "mail")
        da  = cfg.get("department_attr",   "department")
        ta  = cfg.get("title_attr",        "title")
        parts         = "".join(f"({ua}={_ldap_escape(u)})" for u in usernames)
        search_filter = f"(&(objectClass=user)(|{parts}))"
        conn.search(search_base, search_filter, SUBTREE,
                    attributes=[ua, dna, ea, da, ta],
                    size_limit=len(usernames) * 2)
        results: dict[str, dict] = {}
        for entry in conn.entries:
            sam_val = _get_ldap_attr(entry, ua)
            if sam_val:
                results[sam_val.lower()] = {
                    "display_name": _get_ldap_attr(entry, dna),
                    "email":        _get_ldap_attr(entry, ea),
                    "department":   _get_ldap_attr(entry, da),
                    "title":        _get_ldap_attr(entry, ta),
                }
        conn.unbind()
        return results
    except Exception:  # noqa: BLE001
        return {}


def get_cached_ad_user(sam_account: str, ttl_hours: int = 24) -> Optional[dict]:
    try:
        with closing(get_db()) as conn:
            row = conn.execute(
                "SELECT * FROM ad_user_cache WHERE sam_account = ?",
                (sam_account.lower(),),
            ).fetchone()
            if not row:
                return None
            cached_at = datetime.fromisoformat(row["cached_at"])
            if (datetime.now() - cached_at).total_seconds() / 3600 > ttl_hours:
                return None
            return dict(row)
    except sqlite3.OperationalError:
        return None


def _write_ad_cache(sam_account: str, info: dict) -> None:
    with closing(get_db()) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO ad_user_cache
                (sam_account, display_name, email, department, title, cached_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                sam_account.lower(),
                info.get("display_name", ""),
                info.get("email",        ""),
                info.get("department",   ""),
                info.get("title",        ""),
                datetime.now().isoformat(sep=" "),
            ),
        )
        conn.commit()


def enrich_users_from_ad(usernames: list[str]) -> None:
    """Fire-and-forget background thread: fetch uncached / stale AD user info."""
    def _worker() -> None:
        try:
            cfg = get_ad_config()
            if not cfg.get("enabled") or not cfg.get("server") or not cfg.get("base_dn"):
                return
            ttl   = int(cfg.get("cache_ttl_hours", 24))
            stale = [u for u in usernames if get_cached_ad_user(u, ttl) is None]
            if not stale:
                return
            results = _ad_lookup_batch(stale, cfg)
            for sam, info in results.items():
                _write_ad_cache(sam, info)
            not_found = {u.lower() for u in stale} - set(results)
            for sam in not_found:
                _write_ad_cache(sam, {})
        except Exception:  # noqa: BLE001
            pass
    threading.Thread(target=_worker, daemon=True).start()
