"""HTTP tools server on :8787 — scoped tokens, hard limits, fixed tool set.

Auth (two compatible paths on one surface):

* **VDE-41** — ``Authorization: Bearer`` resolves via ``meta.agent_tokens``
  (sha256). Requested ``siteIds`` are intersected with the token's sites and
  the *result* is bound — not validated and rejected.
* **VDE-44** — if the bearer equals ``AGENT_TOOL_TOKEN``, accept it as a
  static proof credential (no site scope). Hard ``limit`` + ``truncated``
  still apply.

Proofs::

    # VDE-41 — token scoped to 1–3, asking for site 9
    curl -s -H "Authorization: Bearer $TOKEN" \\
      "localhost:8787/tools/get_site_performance?siteIds=9" | jq

    # VDE-44 — ceiling is not overridable
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
from agent.site_performance import get_site_performance as get_site_performance_limited
from agent.tokens import AgentToken, bind_site_ids, resolve_token, tool_allowed
from agent.tools import GET_SITE_PERFORMANCE, get_site_performance as get_site_performance_scoped

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787

_BEARER = re.compile(r"^\s*Bearer\s+(\S+)\s*$", re.IGNORECASE)


def _static_token() -> str | None:
    """Optional VDE-44 proof credential. Absent → DB-scoped tokens only."""
    token = os.environ.get("AGENT_TOOL_TOKEN", "").strip()
    return token or None


def _parse_bearer(header: str) -> str | None:
    match = _BEARER.match(header or "")
    if not match:
        return None
    return match.group(1)


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


def _resolve_auth(conn: Any, bearer: str | None) -> AgentToken | str | None:
    """Return AgentToken (VDE-41), ``\"static\"`` (VDE-44), or None."""
    if bearer is None:
        return None
    token = resolve_token(conn, bearer)
    if token is not None:
        return token
    expected = _static_token()
    if expected is not None and bearer == expected:
        return "static"
    return None


class ToolsHandler(BaseHTTPRequestHandler):
    """Minimal JSON tools API. No framework — the surface stays auditable."""

    server_version = "cinema-ops-agent-tools/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        if os.environ.get("AGENT_TOOLS_VERBOSE"):
            super().log_message(fmt, *args)

    def do_GET(self) -> None:  # noqa: N802 — http.server API
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path == "/healthz":
            self._json(200, {"ok": True})
            return

        prefix = "/tools/"
        if not path.startswith(prefix):
            self._json(404, {"error": "not_found", "path": path})
            return
        tool_name = path[len(prefix) :]
        if not tool_name or "/" in tool_name:
            self._json(404, {"error": "not_found", "path": path})
            return

        qs = parse_qs(parsed.query)
        try:
            requested_sites = _parse_site_ids(qs)
        except ValueError:
            self._json(400, {"error": "invalid_site_ids"})
            return

        raw_limit = qs.get("limit", [None])[0]
        try:
            limit = effective_limit(raw_limit)
        except (ValueError, ValidationError) as exc:
            self._json(400, {"error": "invalid_limit", "detail": str(exc), "max": MAX_ROWS})
            return

        bearer = _parse_bearer(self.headers.get("Authorization", ""))
        dsn = getattr(self.server, "dsn", dsn_from_env())  # type: ignore[attr-defined]

        try:
            with connect(dsn) as conn:
                auth = _resolve_auth(conn, bearer)
                if auth is None:
                    self._json(401, {"error": "unauthorized"})
                    return

                if tool_name != GET_SITE_PERFORMANCE:
                    # Static token: only the one HTTP tool is exposed here.
                    # Scoped tokens may also refuse via allowed_tools below.
                    if auth == "static":
                        self._json(404, {"error": "not_found", "path": path})
                        return
                    assert isinstance(auth, AgentToken)
                    if not tool_allowed(auth, tool_name):
                        self._json(
                            403,
                            {
                                "error": "tool_not_allowed",
                                "tool": tool_name,
                                "allowed_tools": list(auth.allowed_tools),
                            },
                        )
                        return
                    self._json(404, {"error": "unknown_tool", "tool": tool_name})
                    return

                if isinstance(auth, AgentToken):
                    if not tool_allowed(auth, GET_SITE_PERFORMANCE):
                        self._json(
                            403,
                            {
                                "error": "tool_not_allowed",
                                "tool": GET_SITE_PERFORMANCE,
                                "allowed_tools": list(auth.allowed_tools),
                            },
                        )
                        return
                    bound = bind_site_ids(auth.site_ids, requested_sites)
                    body = get_site_performance_scoped(conn, bound, limit=limit)
                    body["token_label"] = auth.label
                    self._json(200, body)
                    return

                # VDE-44 static token — unscoped showtime grain + hard LIMIT.
                payload = get_site_performance_limited(conn, limit=limit)
                self._json(200, payload)
        except Exception as exc:  # noqa: BLE001 — surface as tool error
            self._json(500, {"error": "query_failed", "detail": str(exc)})

    def _json(self, status: int, body: dict[str, Any]) -> None:
        data = json.dumps(body, default=str, separators=(",", ":")).encode("utf-8")
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
    """Bind the tools server. Auth is checked per request (scoped and/or static)."""
    return ToolsServer(host, port, dsn or dsn_from_env())


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="cinema-ops agent tools server (VDE-41 scoped tokens · VDE-44 hard limits)"
    )
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
