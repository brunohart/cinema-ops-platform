"""HTTP tools server on :8787 — Bearer token, refusal gate, fixed tool set.

Proof shape (VDE-45):

    curl -s -H "Authorization: Bearer $TOKEN" \\
      "localhost:8787/tools/get_site_performance?siteIds=9" | jq

Out of scope → ``{refused: true, reason, suggestion}``, never empty rows
presented as a complete answer.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

import psycopg

from agent.refuse import AuthorizedCall, Refusal, authorize
from agent.tokens import resolve_token
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


def _params_from_qs(qs: dict[str, list[str]]) -> dict[str, Any]:
    """Flatten query string into the raw param map the refusal gate validates."""
    out: dict[str, Any] = {}
    if "siteIds" in qs or "site_ids" in qs:
        raw_values = qs.get("siteIds") or qs.get("site_ids") or []
        parts: list[str] = []
        for chunk in raw_values:
            parts.extend(p.strip() for p in chunk.split(",") if p.strip())
        out["siteIds"] = parts
    if "from" in qs and qs["from"]:
        out["from"] = qs["from"][0]
    if "to" in qs and qs["to"]:
        out["to"] = qs["to"][0]
    return out


def _bearer(handler: BaseHTTPRequestHandler) -> str | None:
    header = handler.headers.get("Authorization") or handler.headers.get("authorization")
    if not header:
        return None
    scheme, _, rest = header.partition(" ")
    if scheme.lower() != "bearer" or not rest.strip():
        return None
    return rest.strip()


def _http_status_for(refusal: Refusal) -> int:
    if refusal.code == "schema_validation":
        return 400
    if refusal.code == "retention_exceeded":
        return 400
    # tool_not_allowed / site_scope — authorised subject, forbidden action
    return 403


def dispatch_tool(
    conn: psycopg.Connection,
    *,
    tool_name: str,
    bearer: str | None,
    raw_params: dict[str, Any] | None,
) -> tuple[int, dict[str, Any]]:
    """Resolve token → refuse-or-authorise → run tool. Returns (status, body)."""
    if bearer is None:
        return 401, {"error": "missing_bearer_token"}

    token = resolve_token(conn, bearer)
    if token is None:
        return 401, {"error": "invalid_or_expired_token"}

    decision = authorize(token, tool_name, raw_params)
    if isinstance(decision, Refusal):
        body = decision.as_dict()
        body["token_label"] = token.label
        return _http_status_for(decision), body

    assert isinstance(decision, AuthorizedCall)
    if decision.tool_name == GET_SITE_PERFORMANCE:
        body = get_site_performance(
            conn,
            decision.site_ids,
            date_from=decision.date_from,
            date_to=decision.date_to,
        )
        body["token_label"] = token.label
        body["refused"] = False
        return 200, body

    # Unreachable while authorize only admits implemented tools; keep closed.
    refusal = Refusal(
        code="tool_not_allowed",
        reason=f"Tool {tool_name!r} is not implemented on this server.",
        suggestion=f"Retry with {GET_SITE_PERFORMANCE!r}.",
    )
    return 403, {**refusal.as_dict(), "token_label": token.label}


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

        raw_params = _params_from_qs(parse_qs(parsed.query))
        bearer = _bearer(self)
        try:
            with psycopg.connect(_dsn()) as conn:
                status, body = dispatch_tool(
                    conn,
                    tool_name=tool_name,
                    bearer=bearer,
                    raw_params=raw_params,
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

    parser = argparse.ArgumentParser(description="cinema-ops agent tools server (VDE-45)")
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
