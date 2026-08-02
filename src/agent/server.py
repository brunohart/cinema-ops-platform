"""HTTP tools server on :8787 — two complementary auth paths, one port.

VDE-45 (scoped tokens + refusal gate)::

    curl -s -H "Authorization: Bearer $SCOPED_TOKEN" \\
      "localhost:8787/tools/get_site_performance?siteIds=9" | jq
    # → {refused: true, reason, suggestion} — never partial-as-complete

VDE-44 (shared bearer + hard row limits)::

    curl -s -H "Authorization: Bearer $AGENT_TOOL_TOKEN" \\
      "localhost:8787/tools/get_site_performance?limit=100000" \\
      | jq '(.rows|length), .truncated'
    # → 500 / true

A bearer that resolves in ``meta.agent_tokens`` takes the refusal path.
Otherwise the shared ``AGENT_TOOL_TOKEN`` (when set) takes the hard-limits path.
"""

from __future__ import annotations

import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

import psycopg
from pydantic import ValidationError

from agent.db import connect, dsn_from_env
from agent.limits import MAX_ROWS, effective_limit
from agent.refuse import AuthorizedCall, Refusal, authorize
from agent.site_performance import get_site_performance as get_limited_site_performance
from agent.tokens import resolve_token
from agent.tools import GET_SITE_PERFORMANCE
from agent.tools import get_site_performance as get_scoped_site_performance

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787

_BEARER = re.compile(r"^\s*Bearer\s+(\S+)\s*$", re.IGNORECASE)


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
    if "limit" in qs and qs["limit"]:
        out["limit"] = qs["limit"][0]
    return out


def _bearer(handler: BaseHTTPRequestHandler) -> str | None:
    header = handler.headers.get("Authorization") or handler.headers.get("authorization")
    if not header:
        return None
    match = _BEARER.match(header)
    if not match:
        return None
    return match.group(1)


def _env_tool_token() -> str | None:
    token = os.environ.get("AGENT_TOOL_TOKEN", "")
    return token or None


def _http_status_for(refusal: Refusal) -> int:
    if refusal.code in ("schema_validation", "retention_exceeded"):
        return 400
    return 403


def dispatch_scoped_tool(
    conn: psycopg.Connection,
    *,
    tool_name: str,
    token_plaintext: str,
    raw_params: dict[str, Any] | None,
) -> tuple[int, dict[str, Any]] | None:
    """VDE-45 path. Returns None when the bearer is not a scoped token."""
    token = resolve_token(conn, token_plaintext)
    if token is None:
        return None

    decision = authorize(token, tool_name, raw_params)
    if isinstance(decision, Refusal):
        body = decision.as_dict()
        body["token_label"] = token.label
        return _http_status_for(decision), body

    assert isinstance(decision, AuthorizedCall)
    if decision.tool_name == GET_SITE_PERFORMANCE:
        body = get_scoped_site_performance(
            conn,
            decision.site_ids,
            date_from=decision.date_from,
            date_to=decision.date_to,
        )
        body["token_label"] = token.label
        body["refused"] = False
        return 200, body

    refusal = Refusal(
        code="tool_not_allowed",
        reason=f"Tool {tool_name!r} is not implemented on this server.",
        suggestion=f"Retry with {GET_SITE_PERFORMANCE!r}.",
    )
    return 403, {**refusal.as_dict(), "token_label": token.label}


def dispatch_limited_tool(
    conn: psycopg.Connection,
    *,
    tool_name: str,
    raw_params: dict[str, Any] | None,
) -> tuple[int, dict[str, Any]]:
    """VDE-44 path — shared bearer already verified; enforce hard row limits."""
    if tool_name != GET_SITE_PERFORMANCE:
        return 404, {"error": "not_found", "tool": tool_name}

    raw_limit = (raw_params or {}).get("limit")
    try:
        limit = effective_limit(None if raw_limit is None else str(raw_limit))
    except (ValueError, ValidationError) as exc:
        return 400, {"error": "invalid_limit", "detail": str(exc), "max": MAX_ROWS}

    payload = get_limited_site_performance(conn, limit=limit)
    return 200, payload


class ToolsHandler(BaseHTTPRequestHandler):
    """Minimal JSON tools API. No framework — the surface stays auditable."""

    server_version = "cinema-ops-agent-tools/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        if os.environ.get("AGENT_TOOLS_VERBOSE"):
            super().log_message(fmt, *args)

    def _json(self, status: int, body: dict[str, Any]) -> None:
        data = json.dumps(body, default=str, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

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

        bearer = _bearer(self)
        if bearer is None:
            self._json(401, {"error": "missing_bearer_token"})
            return

        raw_params = _params_from_qs(parse_qs(parsed.query))
        dsn = getattr(self.server, "dsn", None) or dsn_from_env()

        try:
            with connect(dsn) as conn:
                scoped = dispatch_scoped_tool(
                    conn,
                    tool_name=tool_name,
                    token_plaintext=bearer,
                    raw_params=raw_params,
                )
                if scoped is not None:
                    status, body = scoped
                    self._json(status, body)
                    return

                env_token = _env_tool_token()
                if env_token is not None and bearer == env_token:
                    status, body = dispatch_limited_tool(
                        conn,
                        tool_name=tool_name,
                        raw_params=raw_params,
                    )
                    self._json(status, body)
                    return
        except Exception as exc:  # noqa: BLE001 — surface as tool error
            self._json(500, {"error": "server_error", "detail": str(exc)})
            return

        self._json(401, {"error": "invalid_or_expired_token"})


class ToolsServer(ThreadingHTTPServer):
    def __init__(self, host: str, port: int, dsn: str) -> None:
        super().__init__((host, port), ToolsHandler)
        self.dsn = dsn


def serve(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    dsn: str | None = None,
    *,
    require_env_token: bool = False,
) -> ToolsServer:
    """Bind the tools server. Scoped-token auth always works when rows exist.

    ``require_env_token=True`` (``serve tools`` / VDE-44) fails fast when
    ``AGENT_TOOL_TOKEN`` is unset so an unauthenticated shared-bearer surface
    cannot start by accident.
    """
    if require_env_token and _env_tool_token() is None:
        raise RuntimeError(
            "AGENT_TOOL_TOKEN is not set — refuse to serve an unauthenticated tools surface"
        )
    return ToolsServer(host, port, dsn or dsn_from_env())


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="cinema-ops agent tools server (VDE-44 hard limits + VDE-45 refusal)"
    )
    parser.add_argument("--host", default=os.environ.get("AGENT_TOOLS_HOST", DEFAULT_HOST))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("AGENT_TOOLS_PORT", str(DEFAULT_PORT))),
    )
    parser.add_argument("--dsn", default=None, help="Override AGENT_DATABASE_URL / DB")
    parser.add_argument(
        "--require-env-token",
        action="store_true",
        help="Fail fast unless AGENT_TOOL_TOKEN is set (VDE-44 serve tools)",
    )
    args = parser.parse_args(argv)

    server = serve(
        host=args.host,
        port=args.port,
        dsn=args.dsn,
        require_env_token=args.require_env_token,
    )
    print(
        f"agent tools listening on http://{args.host}:{args.port} "
        f"(max_rows={MAX_ROWS}; scoped-token refusal + hard limits)",
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
