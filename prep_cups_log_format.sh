#!/usr/bin/env bash
# prep_cups_log_format.sh
#
# Configures /etc/cups/cupsd.conf to use the PageLogFormat required by
# cups-dashboard. Removes any existing PageLogFormat directive and appends
# the correct one, then optionally restarts CUPS.
#
# Usage:
#   ./prep_cups_log_format.sh [/path/to/cupsd.conf] [--restart]
#
# Defaults:
#   cupsd.conf path: /etc/cups/cupsd.conf
#   --restart is opt-in (pass the flag to restart CUPS after changes)

set -euo pipefail

# ─── Defaults ────────────────────────────────────────────────────────────────
CUPS_CONF="${1:-/etc/cups/cupsd.conf}"
RESTART=0

for arg in "$@"; do
    case "${arg}" in
        --restart) RESTART=1 ;;
    esac
done

# The exact PageLogFormat required by cups-dashboard.
# Produces lines like:
#   HP-LaserJet john 42 [06/Mar/2026:09:15:01 -0500] 1 2 - myhost doc.pdf Letter two-sided-long-edge color
PAGE_LOG_FORMAT='PageLogFormat %p %u %j [%d/%b/%Y:%T %z] %P %C %{billing} %{hostname} %{job-name} %{media} %{sides} %{print-color-mode}'

# ─── Banner ──────────────────────────────────────────────────────────────────
echo "======================================="
echo " CUPS Log Format Prep"
echo "======================================="
echo ""
echo "  Config:  ${CUPS_CONF}"
echo "  Restart: $([ "${RESTART}" -eq 1 ] && echo yes || echo no)"
echo ""

# ─── Sanity checks ───────────────────────────────────────────────────────────
if [ ! -f "${CUPS_CONF}" ]; then
    echo "❌  ${CUPS_CONF} not found."
    echo "    Install CUPS or specify the correct path as the first argument."
    exit 1
fi

# On Linux, require root so we can write the config file.
if [[ "$(uname)" != "Darwin" ]] && [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    echo "❌  Must be run as root on Linux."
    echo "    Try: sudo $0 $*"
    exit 1
fi

# ─── Backup ──────────────────────────────────────────────────────────────────
BACKUP="${CUPS_CONF}.bak.$(date +%Y%m%d%H%M%S)"
cp "${CUPS_CONF}" "${BACKUP}"
echo "✓  Backup saved: ${BACKUP}"

# ─── Check if already correct ────────────────────────────────────────────────
if grep -qF "${PAGE_LOG_FORMAT}" "${CUPS_CONF}"; then
    echo "✓  PageLogFormat is already set correctly. No changes needed."
else
    # Count and remove any existing PageLogFormat lines (case-insensitive)
    EXISTING=$(grep -ic '^[[:space:]]*PageLogFormat' "${CUPS_CONF}" || true)
    if [ "${EXISTING}" -gt 0 ]; then
        echo "   Found ${EXISTING} existing PageLogFormat line(s) — removing..."
        TMP="$(mktemp)"
        grep -v -i '^[[:space:]]*PageLogFormat' "${CUPS_CONF}" > "${TMP}"
        mv "${TMP}" "${CUPS_CONF}"
        echo "✓  Existing PageLogFormat removed"
    else
        echo "   No existing PageLogFormat directive found"
    fi

    # Append the required format
    printf '\n# cups-dashboard: required log format\n%s\n' "${PAGE_LOG_FORMAT}" >> "${CUPS_CONF}"
    echo "✓  PageLogFormat added"
fi

# ─── Confirm what's live in the file ─────────────────────────────────────────
echo ""
echo "Active PageLogFormat in ${CUPS_CONF}:"
grep -i 'PageLogFormat' "${CUPS_CONF}" | sed 's/^/    /' || echo "    (none — unexpected)"
echo ""

# ─── Optional CUPS restart ───────────────────────────────────────────────────
if [ "${RESTART}" -eq 1 ]; then
    echo "Restarting CUPS..."
    if command -v systemctl &>/dev/null && systemctl is-enabled cups &>/dev/null 2>&1; then
        systemctl restart cups
        echo "✓  CUPS restarted via systemctl"
    elif command -v service &>/dev/null; then
        service cups restart
        echo "✓  CUPS restarted via service"
    elif [[ "$(uname)" == "Darwin" ]]; then
        if launchctl kickstart -k system/org.cups.cupsd 2>/dev/null; then
            echo "✓  CUPS restarted via launchctl (kickstart)"
        else
            launchctl stop org.cups.cupsd 2>/dev/null || true
            launchctl start org.cups.cupsd 2>/dev/null || true
            echo "✓  CUPS restarted via launchctl (stop/start)"
        fi
    else
        echo "⚠️   Could not auto-restart CUPS. Please restart it manually."
    fi
    echo ""
fi

# ─── Done ────────────────────────────────────────────────────────────────────
echo "======================================="
echo " Done"
echo "======================================="
echo ""
echo "Verify with:"
echo "  grep -i PageLogFormat ${CUPS_CONF}"
echo ""
echo "Tail the live log:"
echo "  tail -f ${CUPS_PAGE_LOG:-/var/log/cups/page_log}"
echo ""
