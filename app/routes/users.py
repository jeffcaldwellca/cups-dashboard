from flask import Blueprint, request, url_for

from ..ad import get_cached_ad_user
from ..db import get_ad_config
from ..importer import clean_token
from ..renderer import render_page
from ..utils import ad_display, color_mode_badge, csv_response, current_month_fallback, h, month_filter_form, rows

bp = Blueprint("users", __name__)


@bp.route("/users")
def users_page():
    month = request.args.get("month", current_month_fallback())
    user = clean_token(request.args.get("user", ""))
    ad_cfg = get_ad_config()
    ad_enabled = bool(ad_cfg.get("enabled"))

    summary_query = """
        SELECT user_name, COUNT(*) AS jobs, COALESCE(SUM(pages),0) AS pages,
               COALESCE(SUM(impressions),0) AS impressions,
               COALESCE(SUM(sheets),0) AS sheets,
               COALESCE(SUM(CASE WHEN color_mode = 'color' THEN impressions ELSE 0 END),0) AS color_impressions,
               COALESCE(SUM(CASE WHEN color_mode IN ('monochrome','process-monochrome','auto-monochrome','bi-level','process-bi-level') THEN impressions ELSE 0 END),0) AS bw_impressions
        FROM jobs
        WHERE year_month = ?
    """
    summary_params: tuple = (month,)
    if user:
        summary_query += " AND user_name = ?"
        summary_params = (month, user)
    summary_query += """
        GROUP BY user_name
        ORDER BY impressions DESC, jobs DESC, user_name ASC
    """
    summary = rows(summary_query, summary_params)

    detail = []
    if user:
        detail = rows(
            """
            SELECT job_ts, printer, job_name, pages, impressions, sheets, media, sides, color_mode
            FROM jobs
            WHERE year_month = ? AND user_name = ?
            ORDER BY job_ts DESC
            LIMIT 100
            """,
            (month, user),
        )

    ad_profile_html = ""
    if user and ad_enabled:
        ttl = int(ad_cfg.get("cache_ttl_hours", 24))
        info = get_cached_ad_user(user, ttl)
        if info:
            ad_profile_html = f"""
        <div class="card ad-profile">
          <div class="ad-profile-item"><strong>Display Name</strong> {h(info.get('display_name') or '-')}</div>
          <div class="ad-profile-item"><strong>Email</strong> {h(info.get('email') or '-')}</div>
          <div class="ad-profile-item"><strong>Department</strong> {h(info.get('department') or '-')}</div>
          <div class="ad-profile-item"><strong>Title</strong> {h(info.get('title') or '-')}</div>
        </div>"""

    dept_header = "<th>Department</th>" if ad_enabled else ""

    def _user_row(r):
        dept_cell = ""
        if ad_enabled:
            ttl = int(ad_cfg.get("cache_ttl_hours", 24))
            info = get_cached_ad_user(r["user_name"], ttl)
            dept_cell = f'<td>{h((info or {}).get("department") or "-")}</td>'
        return (f'<tr><td><a href="{url_for("users.users_page", month=month, user=r["user_name"])}">'
                f'{ad_display(r["user_name"], ad_cfg)}</a></td>'
                f'<td>{r["jobs"]}</td><td>{r["impressions"]}</td>'
                f'<td>{r["color_impressions"]}</td><td>{r["bw_impressions"]}</td>'
                f'<td>{r["sheets"]}</td><td>{r["pages"]}</td>{dept_cell}</tr>')

    body = month_filter_form(month) + ad_profile_html + f"""
    <div class="card">
      <h2>Usage by User <span class="pill">{h(month)}</span></h2>
      <a class="action-link" href="{url_for('users.export_users_csv', month=month)}">Export CSV</a>
      {'<div class="muted">Filtered by user: <span class="mono-chip">' + h(user) + '</span> &nbsp; <a href="' + url_for("users.users_page", month=month) + '">Clear</a></div>' if user else ''}
      <div class="table-wrap">
        <table>
          <tr><th>User</th><th>Jobs</th><th>Impressions</th><th>&#9632; Color</th><th>&#9633; B&amp;W</th><th>Sheets</th><th>Pages</th>{dept_header}</tr>
          {''.join(_user_row(r) for r in summary)}
        </table>
      </div>
    </div>
    """

    if user:
        body += f"""
        <div class="card">
          <h2>Recent Jobs for {ad_display(user, ad_cfg)}</h2>
          <div class="table-wrap">
            <table>
              <tr><th>Time</th><th>Printer</th><th>Job Name</th><th>Color</th><th>Impressions</th><th>Sheets</th><th>Pages</th><th>Media</th><th>Sides</th></tr>
              {''.join(f'<tr><td>{h(r["job_ts"])}</td><td>{h(r["printer"])}</td><td>{h(r["job_name"] or "-")}</td><td>{color_mode_badge(r["color_mode"])}</td><td>{r["impressions"]}</td><td>{r["sheets"]}</td><td>{r["pages"]}</td><td>{h(r["media"] or "-")}</td><td>{h(r["sides"] or "-")}</td></tr>' for r in detail)}
            </table>
          </div>
        </div>
        """

    return render_page(body)


@bp.route("/export/users.csv")
def export_users_csv():
    month = request.args.get("month", current_month_fallback())
    ad_cfg = get_ad_config()
    ad_enabled = bool(ad_cfg.get("enabled"))
    result = rows(
        """
        SELECT user_name, COUNT(*) AS jobs, COALESCE(SUM(pages),0) AS pages,
               COALESCE(SUM(impressions),0) AS impressions,
               COALESCE(SUM(sheets),0) AS sheets,
               COALESCE(SUM(CASE WHEN color_mode = 'color' THEN impressions ELSE 0 END),0) AS color_impressions,
               COALESCE(SUM(CASE WHEN color_mode IN ('monochrome','process-monochrome','auto-monochrome','bi-level','process-bi-level') THEN impressions ELSE 0 END),0) AS bw_impressions
        FROM jobs WHERE year_month = ?
        GROUP BY user_name
        ORDER BY impressions DESC, jobs DESC, user_name ASC
        """,
        (month,),
    )

    if ad_enabled:
        ttl = int(ad_cfg.get("cache_ttl_hours", 24))

        def _ad_row(r):
            info = get_cached_ad_user(r["user_name"], ttl) or {}
            return (
                r["user_name"], r["jobs"], r["impressions"], r["color_impressions"], r["bw_impressions"],
                r["sheets"], r["pages"],
                info.get("display_name") or "",
                info.get("email") or "",
                info.get("department") or "",
                info.get("title") or "",
            )

        return csv_response(
            f"cups_users_{month}.csv",
            ["user", "jobs", "impressions", "color_impressions", "bw_impressions", "sheets", "pages",
             "display_name", "email", "department", "title"],
            (_ad_row(r) for r in result),
        )

    return csv_response(
        f"cups_users_{month}.csv",
        ["user", "jobs", "impressions", "color_impressions", "bw_impressions", "sheets", "pages"],
        ((r["user_name"], r["jobs"], r["impressions"], r["color_impressions"], r["bw_impressions"], r["sheets"], r["pages"]) for r in result),
    )
