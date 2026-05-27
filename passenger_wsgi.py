# Placeholder for cPanel Python App requirement.
# IMS Data Fetcher is a CLI application that runs via cron jobs,
# not a web server. This file satisfies cPanel's startup file requirement.


def application(environ, start_response):
    """Minimal WSGI app — returns a simple status message."""
    start_response('200 OK', [('Content-Type', 'text/plain')])
    return [b'IMS Data Fetcher - CLI application. Runs via cron jobs.']
