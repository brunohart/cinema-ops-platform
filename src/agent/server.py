"""HTTP surface for agent tools — port 8787, bearer auth, hard row limits.

Proof (VDE-44)::

    curl -s -H "Authorization: Bearer $TOKEN" \\
      "localhost:8787/tools/get_site_performance?limit=100000" \\
      | jq '(.rows|length), .truncated'
"""

from __future__ import annotations

import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from pydantic import ValidationError

from agent.db import connect, dsn_from_env
from agent.limits import MAX_ROWS, effective_limit
from agent.tools import get_site_performance

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787

_BEARER = re.compile(r"^\s*Bearer\s+(\S+)\s*$", re.IGNORECASE)


def _expected_token() -> str:
    token = os.environ.get("AGENT_TOOL_TOKEN", "")
    if not token:
        raise RuntimeError(
            "AGENT_TOOL_TOKEN is not set — refuse to serve an unauthenticated tools surface"
        )
    return token


class ToolsHandler(BaseHTTPRequestHandler):
    """Minimal JSON tools API. No framework — the surface stays auditable."""

    server_version = "cinema-ops-agent-tools/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        # Keep proof output clean; structured logs can come later (VDE-34).
        if os.environ.get("AGENT_TOOLS_VERBOSE"):
            super().log_message(fmt, *args)

    def do_GET(self) -> None:  # noqa: N802 — http.server API
        parsed = urlparse(self.path)
        if parsed.path == "/healthz":
            self._json(200, {"ok": True})
            return
        if not self._authorised():
            self._json(401, {"error": "unauthorized"})
            return
        if parsed.path == "/tools/get_site_performance":
            self._get_site_performance(parse_qs(parsed.query))
            return
        self._json(404, {"error": "not_found", "path": parsed.path})

    def _authorised(self) -> bool:
        header = self.headers.get("Authorization", "")
        match = _BEARER.match(header)
        if not match:
            return False
        try:
            expected = _expected_token()
        except RuntimeError:
            return False
        return match.group(1) == expected

    def _get_site_performance(self, query: dict[str, list[str]]) -> None:
        raw_limit = query.get("limit", [None])[0]
        try:
            limit = effective_limit(raw_limit)
        except (ValueError, ValidationError) as exc:
            self._json(400, {"error": "invalid_limit", "detail": str(exc), "max": MAX_ROWS})
            return

        dsn = getattr(self.server, "dsn", dsn_from_env())  # type: ignore[attr-defined]
        try:
            with connect(dsn) as conn:
                payload = get_site_performance(conn, limit=limit)
        except Exception as exc:  # noqa: BLE001 — surface as tool error, don't crash the server
            self._json(500, {"error": "query_failed", "detail": str(exc)})
            return
        self._json(200, payload)

    def _json(self, status: int, body: dict[str, Any]) -> None:
        data = json.dumps(body, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class ToolsServer(ThreadingHTTPServer):
    def __init__(self, host: str, port: int, dsn: str) -> None:
        super().__init__((host, port), ToolsHandler)
        self.dsn = dsn


def serve(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    dsn: str | None = None,
) -> ToolsServer:
    """Bind and serve forever. Token must be present before listen."""
    _expected_token()  # fail fast
    server = ToolsServer(host, port, dsn or dsn_from_env())
    return server


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Agent tools HTTP server (VDE-44)")
    parser.add_argument("--host", default=os.environ.get("AGENT_TOOLS_HOST", DEFAULT_HOST))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("AGENT_TOOLS_PORT", str(DEFAULT_PORT))),
    )
    parser.add_argument("--dsn", default=None, help="Override AGENT_DATABASE_URL / DB")
    args = parser.parse_args(argv)

    server = serve(host=args.host, port=args.port, dsn=args.dsn)
    print(
        f"agent tools listening on http://{args.host}:{args.port} "
        f"(max_rows={MAX_ROWS})",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
