from flask import Blueprint, request, url_for

from ..db import get_ad_config
from ..importer import clean_token  # noqa: F401 (not used here but keep import consistent)
from ..renderer import render_page
from ..utils import ad_display, color_mode_badge, current_month_fallback, h, month_filter_form, rows, scalar

bp = Blueprint("main", __name__)


@bp.route("/")
def dashboard():
    month = request.args.get("month", current_month_fallback())
    ad_cfg = get_ad_config()

    total_pages = scalar("SELECT COALESCE(SUM(pages),0) FROM jobs WHERE year_month = ?", (month,))
    total_impressions = scalar("SELECT COALESCE(SUM(impressions),0) FROM jobs WHERE year_month = ?", (month,))
    total_sheets = scalar("SELECT COALESCE(SUM(sheets),0) FROM jobs WHERE year_month = ?", (month,))
    total_jobs = scalar("SELECT COUNT(*) FROM jobs WHERE year_month = ?", (month,))
    unique_users = scalar("SELECT COUNT(DISTINCT user_name) FROM jobs WHERE year_month = ?", (month,))
    unique_printers = scalar("SELECT COUNT(DISTINCT printer) FROM jobs WHERE year_month = ?", (month,))
    color_impressions = scalar(
        "SELECT COALESCE(SUM(CASE WHEN color_mode = 'color' THEN impressions ELSE 0 END),0) FROM jobs WHERE year_month = ?",
        (month,),
    )
    bw_impressions = scalar(
        """SELECT COALESCE(SUM(CASE WHEN color_mode IN
            ('monochrome','process-monochrome','auto-monochrome','bi-level','process-bi-level')
            THEN impressions ELSE 0 END),0) FROM jobs WHERE year_month = ?""",
        (month,),
    )

    top_users = rows(
        """
        SELECT user_name, COUNT(*) AS jobs, COALESCE(SUM(pages),0) AS pages,
               COALESCE(SUM(impressions),0) AS impressions,
               COALESCE(SUM(sheets),0) AS sheets,
               COALESCE(SUM(CASE WHEN color_mode = 'color' THEN impressions ELSE 0 END),0) AS color_impressions,
               COALESCE(SUM(CASE WHEN color_mode IN ('monochrome','process-monochrome','auto-monochrome','bi-level','process-bi-level') THEN impressions ELSE 0 END),0) AS bw_impressions
        FROM jobs WHERE year_month = ?
        GROUP BY user_name
        ORDER BY impressions DESC, jobs DESC, user_name ASC
        LIMIT 10
        """,
        (month,),
    )
    top_printers = rows(
        """
        SELECT printer, COUNT(*) AS jobs, COALESCE(SUM(pages),0) AS pages,
               COALESCE(SUM(impressions),0) AS impressions,
               COALESCE(SUM(sheets),0) AS sheets,
               COALESCE(SUM(CASE WHEN color_mode = 'color' THEN impressions ELSE 0 END),0) AS color_impressions,
               COALESCE(SUM(CASE WHEN color_mode IN ('monochrome','process-monochrome','auto-monochrome','bi-level','process-bi-level') THEN impressions ELSE 0 END),0) AS bw_impressions
        FROM jobs WHERE year_month = ?
        GROUP BY printer
        ORDER BY impressions DESC, jobs DESC, printer ASC
        LIMIT 10
        """,
        (month,),
    )
    recent = rows(
        """
        SELECT printer, user_name, job_name, pages, impressions, sheets, job_ts, color_mode
        FROM jobs
        ORDER BY job_ts DESC
        LIMIT 10
        """
    )

    body = month_filter_form(month) + f"""
    <div class="grid">
      <div class="card metric-card"><div class="muted">Month</div><div class="metric">{h(month)}</div></div>
      <div class="card metric-card"><div class="muted">Impressions</div><div class="metric">{total_impressions}</div></div>
      <div class="card metric-card"><div class="muted">&#9632; Color</div><div class="metric" style="color:#0a7">{color_impressions}</div></div>
      <div class="card metric-card"><div class="muted">&#9633; B&amp;W</div><div class="metric" style="color:#555">{bw_impressions}</div></div>
      <div class="card metric-card"><div class="muted">Sheets (Est.)</div><div class="metric">{total_sheets}</div></div>
      <div class="card metric-card"><div class="muted">Pages</div><div class="metric">{total_pages}</div></div>
      <div class="card metric-card"><div class="muted">Jobs</div><div class="metric">{total_jobs}</div></div>
      <div class="card metric-card"><div class="muted">Users</div><div class="metric">{unique_users}</div></div>
      <div class="card metric-card"><div class="muted">Printers</div><div class="metric">{unique_printers}</div></div>
    </div>

    <div class="two-col">
      <div class="card">
        <h2>Top Users <span class="pill">{h(month)}</span></h2>
        <div class="table-wrap">
          <table>
            <tr><th>User</th><th>Jobs</th><th>Impressions</th><th>&#9632; Color</th><th>&#9633; B&amp;W</th><th>Sheets</th><th>Pages</th></tr>
            {''.join(f'<tr><td><a href="{url_for("users.users_page", month=month, user=r["user_name"])}">{ad_display(r["user_name"], ad_cfg)}</a></td><td>{r["jobs"]}</td><td>{r["impressions"]}</td><td>{r["color_impressions"]}</td><td>{r["bw_impressions"]}</td><td>{r["sheets"]}</td><td>{r["pages"]}</td></tr>' for r in top_users)}
          </table>
        </div>
      </div>
      <div class="card">
        <h2>Top Printers <span class="pill">{h(month)}</span></h2>
        <div class="table-wrap">
          <table>
            <tr><th>Printer</th><th>Jobs</th><th>Impressions</th><th>&#9632; Color</th><th>&#9633; B&amp;W</th><th>Sheets</th><th>Pages</th></tr>
            {''.join(f'<tr><td><a href="{url_for("printers.printers_page", month=month, printer=r["printer"])}">{h(r["printer"])}</a></td><td>{r["jobs"]}</td><td>{r["impressions"]}</td><td>{r["color_impressions"]}</td><td>{r["bw_impressions"]}</td><td>{r["sheets"]}</td><td>{r["pages"]}</td></tr>' for r in top_printers)}
          </table>
        </div>
      </div>
    </div>

    <div class="card">
      <h2>Recent Jobs</h2>
      <div class="table-wrap">
        <table>
          <tr><th>Time</th><th>User</th><th>Printer</th><th>Job Name</th><th>Color</th><th>Impressions</th><th>Sheets</th><th>Pages</th></tr>
          {''.join(f'<tr><td>{h(r["job_ts"])}</td><td>{h(r["user_name"])}</td><td>{h(r["printer"])}</td><td>{h(r["job_name"] or "-")}</td><td>{color_mode_badge(r["color_mode"])}</td><td>{r["impressions"]}</td><td>{r["sheets"]}</td><td>{r["pages"]}</td></tr>' for r in recent)}
        </table>
      </div>
    </div>
    """
    return render_page(body)


@bp.route("/monthly")
def monthly_page():
    monthly = rows(
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
    body = f"""
    <div class="card">
      <h2>Monthly Totals</h2>
      <a class="action-link" href="{url_for('jobs.export_monthly_csv')}">Export CSV</a>
      <div class="table-wrap">
        <table>
          <tr><th>Month</th><th>Jobs</th><th>Impressions</th><th>Sheets</th><th>Pages</th><th>Users</th><th>Printers</th></tr>
          {''.join(f'<tr><td><a href="{url_for("main.dashboard", month=r["year_month"])}">{h(r["year_month"])}</a></td><td>{r["jobs"]}</td><td>{r["impressions"]}</td><td>{r["sheets"]}</td><td>{r["pages"]}</td><td>{r["users"]}</td><td>{r["printers"]}</td></tr>' for r in monthly)}
        </table>
      </div>
    </div>
    """
    return render_page(body)
