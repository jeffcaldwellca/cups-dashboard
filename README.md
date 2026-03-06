# CUPS Dashboard

Small Flask app for reporting CUPS print usage from `page_log`, with:
- Dashboard KPIs
- Per-user usage
- Per-printer usage
- Recent jobs
- Monthly rollups
- CSV exports
- SQLite cache with rebuild endpoint
- `pages`, `impressions`, and estimated `sheets` metrics

## Requirements

- Python 3.9+
- `flask` package
- Access to the CUPS `page_log` file

Install:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install flask
```

Run:

```bash
python3 dashboard.py
```

Default URL: `http://127.0.0.1:5000`

## Environment Variables

The app reads these on startup:

- `CUPS_PAGE_LOG` (default: `/var/log/cups/page_log`)
- `CUPS_DASH_DB` (default: `./cups_dashboard.db`)
- `CUPS_DASH_HOST` (default: `0.0.0.0`)
- `CUPS_DASH_PORT` (default: `5000`)
- `CUPS_DASH_DEBUG` (default: `0`, set to `1` to enable Flask debug mode)

Example:

```bash
export CUPS_PAGE_LOG=/var/log/cups/page_log
export CUPS_DASH_DB=/opt/cups-dashboard/cups_dashboard.db
export CUPS_DASH_HOST=0.0.0.0
export CUPS_DASH_PORT=5050
export CUPS_DASH_DEBUG=0
python3 dashboard.py
```

## Accepted `page_log` Format

The parser expects lines beginning with:

`printer user job-id [DD/Mon/YYYY:HH:MM:SS -TZ]`

It accepts two page-count variants:

1. With literal `total` token:
   - `printer user job-id [date] total PAGES [billing] [host] [job-name] [media] [sides]`
2. Without `total` token:
   - `printer user job-id [date] PAGES [billing] [host] [job-name] [media] [sides]`

Optional explicit impressions token is also accepted in trailing fields:
- `impressions=123`
- `impression=123`

Example valid lines:

```text
HP-Laser jeff 184 [06/Mar/2026:09:15:01 -0500] total 12 acct01 host01 Q1_Report A4 two-sided-long-edge
HP-Laser jeff 185 [06/Mar/2026:09:20:12 -0500] 3 acct01 host01 Notes A4 one-sided
```

## Deployment Notes

- Ensure the process user can read the configured `CUPS_PAGE_LOG`.
- Ensure the process user can write to the directory containing `CUPS_DASH_DB`.
- On first run (or empty DB), the app auto-imports existing log lines.
- Use `/rebuild` to clear and fully re-import from the current log file.
- UI includes an in-app collapsible setup panel with format/env/default guidance.

## CSV Endpoints

- `/export/users.csv?month=YYYY-MM`
- `/export/printers.csv?month=YYYY-MM`
- `/export/monthly.csv`

## Operational Considerations

- Tailwind is loaded via CDN in the HTML template; internet access is needed for that client-side asset unless you later vendor/bundle Tailwind locally.
- SQLite is adequate for internal reporting; if usage grows, move parsing/storage behind a service DB.
- `impressions` defaults to parsed page count unless explicitly provided in the log line.
- `sheets` is estimated from impressions and `sides` (two-sided/duplex uses `ceil(impressions/2)`).
