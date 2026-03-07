#!/usr/bin/env bash
set -e

# CUPS Dashboard Setup Script
# This script checks for Python 3 and pip, sets up a virtual environment,
# installs dependencies, and starts the dashboard.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"
DASHBOARD_SCRIPT="${SCRIPT_DIR}/dashboard.py"
REQUIREMENTS_FILE="${SCRIPT_DIR}/requirements.txt"

echo "========================================="
echo "CUPS Internal Dashboard - Setup & Start"
echo "========================================="
echo ""

# Check for Python 3
echo "Checking for Python 3..."
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: Python 3 is not installed."
    echo "Please install Python 3 and try again."
    exit 1
fi

PYTHON_VERSION=$(python3 --version)
echo "✓ Found: ${PYTHON_VERSION}"
echo ""

# Check for pip
echo "Checking for pip..."
if ! python3 -m pip --version &> /dev/null; then
    echo "❌ Error: pip is not installed."
    echo "Please install pip for Python 3 and try again."
    exit 1
fi

PIP_VERSION=$(python3 -m pip --version)
echo "✓ Found: ${PIP_VERSION}"
echo ""

# Check if dashboard.py exists
if [ ! -f "${DASHBOARD_SCRIPT}" ]; then
    echo "❌ Error: dashboard.py not found in ${SCRIPT_DIR}"
    exit 1
fi

# Set up virtual environment
if [ -d "${VENV_DIR}" ]; then
    echo "✓ Virtual environment already exists at ${VENV_DIR}"
else
    echo "Creating virtual environment..."
    python3 -m venv "${VENV_DIR}"
    echo "✓ Virtual environment created"
fi
echo ""

# Activate virtual environment
echo "Activating virtual environment..."
source "${VENV_DIR}/bin/activate"
echo "✓ Virtual environment activated"
echo ""

# Upgrade pip
echo "Upgrading pip..."
python -m pip install --upgrade pip --quiet
echo "✓ pip upgraded"
echo ""

# Install dependencies
echo "Installing Flask and dependencies..."
if [ -f "${REQUIREMENTS_FILE}" ]; then
    pip install -r "${REQUIREMENTS_FILE}" --quiet
    echo "✓ Dependencies installed from requirements.txt"
else
    pip install flask --quiet
    echo "✓ Flask installed"
fi
echo ""

# Display environment configuration
echo "========================================="
echo "Configuration"
echo "========================================="
echo "Page Log: ${CUPS_PAGE_LOG:-/var/log/cups/page_log (default)}"
echo "Database: ${CUPS_DASH_DB:-./cups_dashboard.db (default)}"
echo "Host: ${CUPS_DASH_HOST:-0.0.0.0 (default)}"
echo "Port: ${CUPS_DASH_PORT:-5000 (default)}"
echo "Debug: ${CUPS_DASH_DEBUG:-0 (default)}"
echo ""
echo "To customize, set environment variables before running:"
echo "  export CUPS_PAGE_LOG=/path/to/page_log"
echo "  export CUPS_DASH_DB=/path/to/database.db"
echo "  export CUPS_DASH_HOST=127.0.0.1"
echo "  export CUPS_DASH_PORT=8080"
echo "  export CUPS_DASH_DEBUG=1"
echo ""

# Start the dashboard
echo "========================================="
echo "Starting CUPS Dashboard..."
echo "========================================="
echo ""
echo "⚠️  IMPORTANT: Ensure your CUPS page_log uses the standard format:"
echo "   [DD/Mon/YYYY:HH:MM:SS -TZ]"
echo "   Example: [06/Mar/2026:09:15:01 -0500]"
echo ""
echo "   If no data appears, verify your log format with:"
echo "   head -n 5 ${CUPS_PAGE_LOG:-/var/log/cups/page_log}"
echo ""
echo "Access the dashboard at:"
echo "  http://${CUPS_DASH_HOST:-0.0.0.0}:${CUPS_DASH_PORT:-5000}"
echo ""
echo "Press Ctrl+C to stop the server"
echo ""

python "${DASHBOARD_SCRIPT}"
