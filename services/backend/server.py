"""Health-only packaging scaffold; not the location service."""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    server_version = "FamilyStalker"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def respond(self, status, payload, head=False):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def do_GET(self):
        self.respond(
            200 if self.path == "/healthz" else 404,
            {"status": "ok", "stage": "scaffold"}
            if self.path == "/healthz" else {"error": "not_found"},
        )

    def do_HEAD(self):
        self.respond(
            200 if self.path == "/healthz" else 404,
            {"status": "ok", "stage": "scaffold"}
            if self.path == "/healthz" else {"error": "not_found"},
            head=True,
        )

    def reject_write(self):
        self.respond(405, {"error": "not_implemented"})

    do_POST = reject_write
    do_PUT = reject_write
    do_PATCH = reject_write
    do_DELETE = reject_write

    def log_message(self, format, *args):
        # Do not log request URLs, headers, or bodies.
        pass


if __name__ == "__main__":
    with HTTPServer(("0.0.0.0", 8080), Handler) as server:
        print("Family-Stalker health scaffold listening on port 8080", flush=True)
        server.serve_forever()
