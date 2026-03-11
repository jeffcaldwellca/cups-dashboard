FROM python:3.11-slim

LABEL org.opencontainers.image.title="PaperTrail for CUPS" \
      org.opencontainers.image.description="Dashboard for CUPS print usage statistics" \
      org.opencontainers.image.source="https://github.com/jeffcaldwellca/cups-dashboard"

WORKDIR /app

# Install dependencies first (layer-cached separately from app code)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY dashboard.py .
COPY app/ app/

# ── Runtime defaults (all overridable via docker-compose or -e flags) ─────────
ENV CUPS_PAGE_LOG=/var/log/cups/page_log \
    CUPS_DASH_DB=/data/cups_dashboard.db \
    CUPS_DASH_HOST=0.0.0.0 \
    CUPS_DASH_PORT=5000 \
    CUPS_DASH_DEBUG=0

# /data holds the persistent SQLite database
VOLUME ["/data"]

EXPOSE 5000

# Drop to a non-root user for the running process.
# Added to group lp (gid 7 on Debian/Ubuntu) so the process can read CUPS logs
# that are owned root:lp with mode 640.
RUN useradd -r -u 1001 -g root -G lp appuser 2>/dev/null || useradd -r -u 1001 -g root appuser
USER appuser

CMD ["python", "dashboard.py"]
