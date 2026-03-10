from flask import Blueprint, request, url_for

from ..renderer import render_page
from ..utils import csv_response, current_month_fallback, h, month_filter_form, rows, scalar

bp = Blueprint("jobs", __name__)


@bp.route("/jobs")
def jobs_page():
    month = request.args.get("month", "").strip()
    page = max(1, int(request.args.get("page", 1) or 1))
    per_page = 50
    offset = (page - 1) * per_page

    count_sql = "SELECT COUNT(*) FROM jobs" + (" WHERE year_month = ?" if month else "")
    total_jobs = scalar(count_sql, (month,) if month else ())
    total_pages_count = max(1, (total_jobs + per_page - 1) // per_page)
    page = min(page, total_pages_count)
    offset = (page - 1) * per_page

    if month:
        recent = rows(
            """
            SELECT job_ts, user_name, printer, job_name, pages, impressions, sheets, media, sides, host
            FROM jobs
            WHERE year_month = ?
            ORDER BY job_ts DESC
            LIMIT ? OFFSET ?
            """,
            (month, per_page, offset),
        )
    else:
        recent = rows(
            """
            SELECT job_ts, user_name, printer, job_name, pages, impressions, sheets, media, sides, host
            FROM jobs
            ORDER BY job_ts DESC
            LIMIT ? OFFSET ?
            """,
            (per_page, offset),
        )

    def _page_link(p: int, label: str) -> str:
        args = {"page": p}
        if month:
            args["month"] = month
        return f'<a class="action-link" href="{url_for("jobs.jobs_page", **args)}">{label}</a>'

    pagination = ""
    if total_pages_count > 1:
        parts = []
        if page > 1:
            parts.append(_page_link(page - 1, "&laquo; Prev"))
        parts.append(f'<span class="muted">Page {page} / {total_pages_count}</span>')
        if page < total_pages_count:
            parts.append(_page_link(page + 1, "Next &raquo;"))
        pagination = '<div style="margin:.75rem 0;display:flex;gap:1rem;align-items:center">' + " ".join(parts) + "</div>"

    body = month_filter_form(month or current_month_fallback()) + f"""
    <div class="card">
      <h2>Jobs {'<span class="pill">' + h(month) + '</span>' if month else ''}</h2>
      {pagination}
      <div class="table-wrap">
        <table>
          <tr><th>Time</th><th>User</th><th>Printer</th><th>Job Name</th><th>Impressions</th><th>Sheets</th><th>Pages</th><th>Media</th><th>Sides</th><th>Host</th></tr>
          {''.join(f'<tr><td>{h(r["job_ts"])}</td><td>{h(r["user_name"])}</td><td>{h(r["printer"])}</td><td>{h(r["job_name"] or "-")}</td><td>{r["impressions"]}</td><td>{r["sheets"]}</td><td>{r["pages"]}</td><td>{h(r["media"] or "-")}</td><td>{h(r["sides"] or "-")}</td><td>{h(r["host"] or "-")}</td></tr>' for r in recent)}
        </table>
      </div>
      {pagination}
    </div>
    """
    return render_page(body)


@bp.route("/export/monthly.csv")
def export_monthly_csv():
    result = rows(
        """
        SELECT year_month, COUNT(*) AS jobs, COALESCE(SUM(pages),0) AS pages,
               COALESCE(SUM(impressions),0) AS impressions,
               COALESCE(SUM(sheets),0) AS sheets,
               COUNT(DISTINCT user_name) AS users,
               COUNT(DISTINCT printer) AS printers
        FROM jobs
        GROUP BY year_month
        ORDER BY year_month DESC
        """
    )
    return csv_response(
        "cups_monthly.csv",
        ["month", "jobs", "impressions", "sheets", "pages", "users", "printers"],
        (
            (r["year_month"], r["jobs"], r["impressions"], r["sheets"], r["pages"], r["users"], r["printers"])
            for r in result
        ),
    )
