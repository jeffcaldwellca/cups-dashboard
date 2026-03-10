FROM python:3.11-slim

LABEL org.opencontainers.image.title="CUPS Dashboard" \
      org.opencontainers.image.description="Flask dashboard for CUPS print usage statistics" \
      org.opencontainers.image.source="https://github.com/jeffcaldwellca/cups-dashboard"

WORKDIR /app

# Install dependencies first (layer-cached separately from app code)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY dashboard.py .

# ── Runtime defaults (all overridable via docker-compose or -e flags) ─────────
ENV CUPS_PAGE_LOG=/var/log/cups/page_log \
    CUPS_DASH_DB=/data/cups_dashboard.db \
    CUPS_DASH_HOST=0.0.0.0 \
    CUPS_DASH_PORT=5000 \
    CUPS_DASH_DEBUG=0

# /data holds the persistent SQLite database
VOLUME ["/data"]

EXPOSE 5000

# Drop to a non-root user for the running process
RUN useradd -r -u 1001 -g root appuser
USER appuser

CMD ["python", "dashboard.py"]
