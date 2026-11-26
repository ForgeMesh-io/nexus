"""Loopback-only Nexus participant API; not a public web server."""

import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import inspect
import json
import re
import sqlite3

from .pilot import Pilot, PilotError
from .pilot_cli import _object


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Never log arbitrary paths, credentials, or submitted content.
        pass

    def do_POST(self):
        code, result = self._dispatch()
        encoded = json.dumps(result).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        if code == 401:
            self.send_header("WWW-Authenticate", "Bearer")
        self.end_headers()
        self.wfile.write(encoded)

    def _dispatch(self):
        if self.headers.get_all("Host") != [f"127.0.0.1:{self.server.server_port}"] or "Origin" in self.headers:
            return 403, {"error": "invalid_origin"}
        handler = self.server.operations.get(self.path)
        if handler is None:
            return 404, {"error": "unknown_action"}
        auth = self.headers.get_all("Authorization", [])
        if len(auth) != 1 or not re.fullmatch(r"Bearer [A-Za-z0-9_-]{43}", auth[0]):
            return 401, {"error": "unauthorized"}
        length = self.headers.get_all("Content-Length", [])
        if (len(length) != 1 or not re.fullmatch(r"[0-9]{1,5}", length[0])
                or "Transfer-Encoding" in self.headers or self.headers.get_content_type() != "application/json"):
            return 400, {"error": "invalid_input"}
        size = int(length[0])
        if size > 65_536:
            return 413, {"error": "invalid_input"}
        try:
            raw = self.rfile.read(size)
            if len(raw) != size:
                raise ValueError("incomplete request")
            data = json.loads(raw, object_pairs_hook=_object)
            if not isinstance(data, dict) or "token" in data:
                raise TypeError("expected object, token must be in the header")
            token = auth[0][7:]
            inspect.signature(handler).bind(token, **data)
        except (ValueError, TypeError, RecursionError, TimeoutError):
            return 400, {"error": "invalid_input"}
        try:
            return 200, handler(token, **data)
        except PilotError as exc:
            code = {"unauthorized": 401, "invalid_input": 400, "unknown_task": 404,
                    "capacity": 429, "independence": 403}.get(exc.code, 409)
            return code, {"error": exc.code}
        except (OSError, sqlite3.Error):
            return 503, {"error": "storage_unavailable"}


class Server(HTTPServer):
    request_queue_size = 8

    def get_request(self):
        sock, addr = super().get_request()
        sock.settimeout(3)
        return sock, addr

    def handle_error(self, request, client_address):
        # Broken connections must not emit request data to the console.
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    ledger = Pilot(args.database)
    with Server(("127.0.0.1", args.port), Handler) as server:
        server.operations = {
            "/v1/discover": ledger.discover, "/v1/claim": ledger.claim,
            "/v1/submit": ledger.submit, "/v1/review": ledger.review,
        }
        print(f"http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
