"""HTTP tools server on :8787 — Bearer token, site bind, fixed tool set.

Proof shape (VDE-41):

    curl -s -H "Authorization: Bearer $TOKEN" \\
      "localhost:8787/tools/get_site_performance?siteIds=9" | jq
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

import psycopg

from agent.tokens import bind_site_ids, resolve_token, tool_allowed
from agent.tools import GET_SITE_PERFORMANCE, get_site_performance

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787


def _dsn() -> str:
    from stores.postgres import dsn_from_env

    # Prefer the SELECT-only agent role when AGENT_DATABASE_URL is set;
    # fall back to DB / DATABASE_URL for local proof convenience.
    agent_dsn = os.environ.get("AGENT_DATABASE_URL")
    if agent_dsn:
        if agent_dsn.startswith("postgres://"):
            return "postgresql://" + agent_dsn[len("postgres://") :]
        return agent_dsn
    return dsn_from_env()


def _parse_site_ids(qs: dict[str, list[str]]) -> list[int] | None:
    """Parse siteIds query param. Absent → None (bind to all token sites)."""
    raw_values = qs.get("siteIds") or qs.get("site_ids")
    if not raw_values:
        return None
    out: list[int] = []
    for chunk in raw_values:
        for part in chunk.split(","):
            part = part.strip()
            if not part:
                continue
            out.append(int(part))
    return out


def _bearer(handler: BaseHTTPRequestHandler) -> str | None:
    header = handler.headers.get("Authorization") or handler.headers.get("authorization")
    if not header:
        return None
    scheme, _, rest = header.partition(" ")
    if scheme.lower() != "bearer" or not rest.strip():
        return None
    return rest.strip()


def dispatch_tool(
    conn: psycopg.Connection,
    *,
    tool_name: str,
    bearer: str | None,
    requested_site_ids: list[int] | None,
) -> tuple[int, dict[str, Any]]:
    """Resolve token → check tool → bind sites → run tool. Returns (status, body)."""
    if bearer is None:
        return 401, {"error": "missing_bearer_token"}

    token = resolve_token(conn, bearer)
    if token is None:
        return 401, {"error": "invalid_or_expired_token"}

    if not tool_allowed(token, tool_name):
        return 403, {
            "error": "tool_not_allowed",
            "tool": tool_name,
            "allowed_tools": list(token.allowed_tools),
        }

    bound = bind_site_ids(token.site_ids, requested_site_ids)

    if tool_name == GET_SITE_PERFORMANCE:
        body = get_site_performance(conn, bound)
        body["token_label"] = token.label
        return 200, body

    return 404, {"error": "unknown_tool", "tool": tool_name}


class ToolsHandler(BaseHTTPRequestHandler):
    server_version = "cinema-ops-tools/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        # Quiet by default; proof scripts care about the response body.
        if os.environ.get("AGENT_TOOLS_VERBOSE"):
            super().log_message(fmt, *args)

    def _send(self, status: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        prefix = "/tools/"
        if not path.startswith(prefix):
            self._send(404, {"error": "not_found", "path": path})
            return

        tool_name = path[len(prefix) :]
        if not tool_name or "/" in tool_name:
            self._send(404, {"error": "not_found", "path": path})
            return

        try:
            requested = _parse_site_ids(parse_qs(parsed.query))
        except ValueError:
            self._send(400, {"error": "invalid_site_ids"})
            return

        bearer = _bearer(self)
        try:
            with psycopg.connect(_dsn()) as conn:
                status, body = dispatch_tool(
                    conn,
                    tool_name=tool_name,
                    bearer=bearer,
                    requested_site_ids=requested,
                )
        except Exception as exc:  # noqa: BLE001 — surface as 500 for the proof
            self._send(500, {"error": "server_error", "detail": str(exc)})
            return

        self._send(status, body)


def serve(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), ToolsHandler)
    return httpd


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="cinema-ops agent tools server (VDE-41)")
    parser.add_argument("--host", default=os.environ.get("AGENT_TOOLS_HOST", DEFAULT_HOST))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("AGENT_TOOLS_PORT", str(DEFAULT_PORT))),
    )
    args = parser.parse_args(argv)
    httpd = serve(args.host, args.port)
    print(f"agent tools listening on http://{args.host}:{args.port}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down", flush=True)
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
