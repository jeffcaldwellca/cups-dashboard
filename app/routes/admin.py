from flask import Blueprint, request, url_for

from ..config import PAGE_LOG_PATH
from ..importer import reset_and_reimport
from ..renderer import render_page
from ..utils import csrf_token, h, verify_csrf

bp = Blueprint("admin", __name__)


@bp.route("/rebuild", methods=["GET", "POST"])
def rebuild_db():
    if request.method == "GET":
        csrf = csrf_token()
        return render_page(
            f"""
            <div class="card">
              <h2>Rebuild Database</h2>
              <p class="muted">This clears current cached rows and re-imports from <span class="mono">{h(PAGE_LOG_PATH)}</span>.</p>
              <form method="post">
                <input type="hidden" name="csrf_token" value="{h(csrf)}">
                <button type="submit" class="btn-danger">Confirm Rebuild</button>
                &nbsp; <a class="action-link" href="{url_for('main.dashboard')}">Cancel</a>
              </form>
            </div>
            """
        )
    if not verify_csrf():
        return render_page(
            '<div class="card"><div class="alert alert-danger">Invalid security token. Please try again.</div>'
            f'<a href="{url_for("admin.rebuild_db")}">Go back</a></div>'
        ), 403

    inserted, skipped = reset_and_reimport()
    return render_page(
        f"""
        <div class="card">
          <h2>Database Rebuilt</h2>
          <p class="muted">Inserted: <strong>{inserted}</strong> &nbsp; Skipped: <strong>{skipped}</strong></p>
          <p><a href="{url_for('main.dashboard')}">Return to dashboard</a></p>
        </div>
        """
    )


@bp.app_errorhandler(404)
def page_not_found(e):
    body = "<div class='alert alert-warning'><strong>404</strong> — Page not found.</div>"
    return render_page(body, "Not Found", status=404)


@bp.app_errorhandler(500)
def internal_error(e):
    body = "<div class='alert alert-danger'><strong>500</strong> — Internal server error.</div>"
    return render_page(body, "Server Error", status=500)
