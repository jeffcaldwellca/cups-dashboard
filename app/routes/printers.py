from flask import Blueprint, request, url_for

from ..db import get_ad_config
from ..importer import clean_token
from ..renderer import render_page
from ..utils import ad_display, color_mode_badge, csv_response, current_month_fallback, h, month_filter_form, rows

bp = Blueprint("printers", __name__)


@bp.route("/printers")
def printers_page():
    month = request.args.get("month", current_month_fallback())
    printer = clean_token(request.args.get("printer", ""))
    ad_cfg = get_ad_config()

    summary_query = """
        SELECT printer, COUNT(*) AS jobs, COALESCE(SUM(pages),0) AS pages,
               COALESCE(SUM(impressions),0) AS impressions,
               COALESCE(SUM(sheets),0) AS sheets,
               COALESCE(SUM(CASE WHEN color_mode = 'color' THEN impressions ELSE 0 END),0) AS color_impressions,
               COALESCE(SUM(CASE WHEN color_mode IN ('monochrome','process-monochrome','auto-monochrome','bi-level','process-bi-level') THEN impressions ELSE 0 END),0) AS bw_impressions
        FROM jobs
        WHERE year_month = ?
    """
    summary_params: tuple = (month,)
    if printer:
        summary_query += " AND printer = ?"
        summary_params = (month, printer)
    summary_query += """
        GROUP BY printer
        ORDER BY impressions DESC, jobs DESC, printer ASC
    """
    summary = rows(summary_query, summary_params)

    detail = []
    if printer:
        detail = rows(
            """
            SELECT job_ts, user_name, job_name, pages, impressions, sheets, media, sides, color_mode
            FROM jobs
            WHERE year_month = ? AND printer = ?
            ORDER BY job_ts DESC
            LIMIT 100
            """,
            (month, printer),
        )

    body = month_filter_form(month) + f"""
    <div class="card">
      <h2>Usage by Printer <span class="pill">{h(month)}</span></h2>
      <a class="action-link" href="{url_for('printers.export_printers_csv', month=month)}">Export CSV</a>
      {'<div class="muted">Filtered by printer: <span class="mono-chip">' + h(printer) + '</span> &nbsp; <a href="' + url_for("printers.printers_page", month=month) + '">Clear</a></div>' if printer else ''}
      <div class="table-wrap">
        <table>
          <tr><th>Printer</th><th>Jobs</th><th>Impressions</th><th>&#9632; Color</th><th>&#9633; B&amp;W</th><th>Sheets</th><th>Pages</th></tr>
          {''.join(f'<tr><td><a href="{url_for("printers.printers_page", month=month, printer=r["printer"])}">{h(r["printer"])}</a></td><td>{r["jobs"]}</td><td>{r["impressions"]}</td><td>{r["color_impressions"]}</td><td>{r["bw_impressions"]}</td><td>{r["sheets"]}</td><td>{r["pages"]}</td></tr>' for r in summary)}
        </table>
      </div>
    </div>
    """

    if printer:
        body += f"""
        <div class="card">
          <h2>Recent Jobs for {h(printer)}</h2>
          <div class="table-wrap">
            <table>
              <tr><th>Time</th><th>User</th><th>Job Name</th><th>Color</th><th>Impressions</th><th>Sheets</th><th>Pages</th><th>Media</th><th>Sides</th></tr>
              {''.join(f'<tr><td>{h(r["job_ts"])}</td><td>{ad_display(r["user_name"], ad_cfg)}</td><td>{h(r["job_name"] or "-")}</td><td>{color_mode_badge(r["color_mode"])}</td><td>{r["impressions"]}</td><td>{r["sheets"]}</td><td>{r["pages"]}</td><td>{h(r["media"] or "-")}</td><td>{h(r["sides"] or "-")}</td></tr>' for r in detail)}
            </table>
          </div>
        </div>
        """

    return render_page(body)


@bp.route("/export/printers.csv")
def export_printers_csv():
    month = request.args.get("month", current_month_fallback())
    result = rows(
        """
        SELECT printer, COUNT(*) AS jobs, COALESCE(SUM(pages),0) AS pages,
               COALESCE(SUM(impressions),0) AS impressions,
               COALESCE(SUM(sheets),0) AS sheets,
               COALESCE(SUM(CASE WHEN color_mode = 'color' THEN impressions ELSE 0 END),0) AS color_impressions,
               COALESCE(SUM(CASE WHEN color_mode IN ('monochrome','process-monochrome','auto-monochrome','bi-level','process-bi-level') THEN impressions ELSE 0 END),0) AS bw_impressions
        FROM jobs WHERE year_month = ?
        GROUP BY printer
        ORDER BY impressions DESC, jobs DESC, printer ASC
        """,
        (month,),
    )
    return csv_response(
        f"cups_printers_{month}.csv",
        ["printer", "jobs", "impressions", "color_impressions", "bw_impressions", "sheets", "pages"],
        ((r["printer"], r["jobs"], r["impressions"], r["color_impressions"], r["bw_impressions"], r["sheets"], r["pages"]) for r in result),
    )
