#!/usr/bin/env bash
# deploy.sh
#
# Full deployment script for cups-dashboard:
#   1. Configures the host's CUPS PageLogFormat via prep_cups_log_format.sh
#   2. Builds the Docker image
#   3. Starts the container via Docker Compose
#
# Usage:
#   ./deploy.sh                        # Uses default /etc/cups/cupsd.conf
#   CUPS_CONF=/path/to/cupsd.conf ./deploy.sh
#
# Flags passed through to prep_cups_log_format.sh:
#   --no-restart   Skip restarting CUPS after config change (default: restarts)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CUPS_CONF="${CUPS_CONF:-/etc/cups/cupsd.conf}"
NO_RESTART=0

for arg in "$@"; do
    case "${arg}" in
        --no-restart) NO_RESTART=1 ;;
    esac
done

# ── Dependency checks ─────────────────────────────────────────────────────────
echo "========================================="
echo " CUPS Dashboard — Docker Deployment"
echo "========================================="
echo ""

if ! command -v docker &>/dev/null; then
    echo "❌  Docker is not installed or not in PATH."
    echo "    Install Docker Desktop: https://docs.docker.com/get-docker/"
    exit 1
fi

if ! docker compose version &>/dev/null 2>&1; then
    echo "❌  Docker Compose (v2) is not available."
    echo "    Update Docker Desktop or install the Compose plugin."
    exit 1
fi

echo "✓  Docker $(docker --version | awk '{print $3}' | tr -d ',')"
echo "✓  $(docker compose version)"
echo ""

# ── Step 1: Configure CUPS log format on the host ────────────────────────────
echo "─── Step 1/3: Configure CUPS PageLogFormat ──────────────────────────────"
echo ""

PREP_SCRIPT="${SCRIPT_DIR}/prep_cups_log_format.sh"
if [ ! -f "${PREP_SCRIPT}" ]; then
    echo "❌  prep_cups_log_format.sh not found at ${PREP_SCRIPT}"
    exit 1
fi
chmod +x "${PREP_SCRIPT}"

RESTART_FLAG="--restart"
[ "${NO_RESTART}" -eq 1 ] && RESTART_FLAG=""

# On Linux, escalate to root if needed
if [[ "$(uname)" != "Darwin" ]] && [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    echo "   Elevated privileges required — running with sudo..."
    sudo bash "${PREP_SCRIPT}" "${CUPS_CONF}" ${RESTART_FLAG}
else
    bash "${PREP_SCRIPT}" "${CUPS_CONF}" ${RESTART_FLAG}
fi

echo ""

# ── Step 2: Build the Docker image ───────────────────────────────────────────
echo "─── Step 2/3: Build Docker image ────────────────────────────────────────"
echo ""
docker compose -f "${SCRIPT_DIR}/docker-compose.yml" build
echo ""
echo "✓  Image built"
echo ""

# ── Step 3: Start the container ──────────────────────────────────────────────
echo "─── Step 3/3: Start container ───────────────────────────────────────────"
echo ""
docker compose -f "${SCRIPT_DIR}/docker-compose.yml" up -d
echo ""

DASH_PORT="${CUPS_DASH_PORT:-5000}"

echo "========================================="
echo " Deployment complete"
echo "========================================="
echo ""
echo "  Dashboard: http://localhost:${DASH_PORT}"
echo ""
echo "  Useful commands:"
echo "    Logs:    docker compose -f ${SCRIPT_DIR}/docker-compose.yml logs -f cups-dashboard"
echo "    Status:  docker compose -f ${SCRIPT_DIR}/docker-compose.yml ps"
echo "    Stop:    docker compose -f ${SCRIPT_DIR}/docker-compose.yml down"
echo ""
