"""View routes for the Renewal Campaign Dashboard.

Serves the HTML dashboard UI.
"""

from flask import Blueprint, render_template

views_bp = Blueprint("views", __name__)


@views_bp.route("/renewals")
@views_bp.route("/renewals/")
def dashboard():
    """Render the main renewal campaign dashboard."""
    return render_template("dashboard.html")
