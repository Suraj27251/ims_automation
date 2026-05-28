"""WSGI entry point for cPanel deployment.

Serves the Renewal Campaign Dashboard (Flask app).
Handles cPanel/Passenger sub-path mounting automatically.
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))

from renewal_system.app import create_app

# Create the Flask application
app = create_app()

# WSGI application callable (required by cPanel/Passenger)
application = app
