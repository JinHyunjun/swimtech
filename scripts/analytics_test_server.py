"""Loopback-only synthetic analytics sandbox. No production authentication or DB."""
import json
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'api'))
from fastapi import Response
from routers.analytics import analytics_test_config


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if path == '/api/analytics/test-config':
            body = json.dumps(analytics_test_config(Response())).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)
            return
        # Only expose the two sandbox assets, not application files or secrets.
        if path in ('/', '/analytics_test'):
            self.path = '/analytics_test.html'
        elif path != '/static/analytics-test.js':
            self.send_error(404)
            return
        super().do_GET()


if __name__ == '__main__':
    server = ThreadingHTTPServer(('127.0.0.1', 8766), partial(Handler, directory=str(ROOT / 'frontend')))
    print('Analytics sandbox: http://localhost:8766/analytics_test', flush=True)
    server.serve_forever()
