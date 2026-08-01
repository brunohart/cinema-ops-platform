"""Public demo server for cinema-ops-platform (VDE-54).

Stdlib only. MUST NOT import agent.tools, agent.limits, agent.server,
agent.site_performance, agent.db, or src.cli.

Run:
    PYTHONPATH=src python3 -m agent.demo_server [--host 0.0.0.0] [--port 8080]

Environment:
    DEMO_HOST   — bind address (default 0.0.0.0)
    DEMO_PORT   — bind port    (default 8080)
    AGENT_DEMO_TOKEN_SHA256 — override token digest for testing
"""

from __future__ import annotations

import argparse
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from agent.catalog import IMPLEMENTED_TOOLS, TOOL_DESCRIPTIONS, TOOL_COLUMNS
from agent.demo_data import AgentToken, resolve_demo_token, rows_for
from agent.refuse import (
    AuthorizedCall,
    Refusal,
    authorize,
    check_site_scope,
    check_tool_allowed,
    validate_params,
)

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8080

_BEARER = re.compile(r"^\s*Bearer\s+(\S+)\s*$", re.IGNORECASE)

_DATASET_HEADER = ("X-Cinema-Ops-Dataset", "fixture")


def _bearer(handler: BaseHTTPRequestHandler) -> str | None:
    header = handler.headers.get("Authorization") or handler.headers.get("authorization")
    if not header:
        return None
    match = _BEARER.match(header)
    if not match:
        return None
    return match.group(1)


def _params_from_qs(qs: dict[str, list[str]]) -> dict[str, Any]:
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


def _http_status_for(refusal: Refusal) -> int:
    if refusal.code in ("schema_validation", "retention_exceeded"):
        return 400
    return 403


def _authorize_demo(
    token: AgentToken,
    tool_name: str,
    raw_params: dict[str, Any] | None,
) -> AuthorizedCall | Refusal:
    """Run refusal checks against a demo AgentToken.

    Reuses the real policy layer (agent.refuse) — the only difference from the
    production path is that the token comes from demo_data, not Postgres.
    """
    # check_tool_allowed and check_site_scope work on duck-typed AgentToken;
    # the demo AgentToken has the same .allowed_tools and .site_ids attributes.
    refused = check_tool_allowed(token, tool_name)  # type: ignore[arg-type]
    if refused is not None:
        return refused

    if tool_name not in IMPLEMENTED_TOOLS:
        return Refusal(
            code="tool_not_allowed",
            reason=f"Tool {tool_name!r} is not implemented on the demo server.",
            suggestion=f"Retry with one of: {', '.join(repr(t) for t in IMPLEMENTED_TOOLS)}.",
        )

    params = validate_params(raw_params)
    if isinstance(params, Refusal):
        return params

    refused = check_site_scope(token, params.site_ids)  # type: ignore[arg-type]
    if refused is not None:
        return refused

    if params.site_ids is None:
        bound = sorted({int(s) for s in token.site_ids})
    else:
        bound = sorted({int(s) for s in params.site_ids})

    return AuthorizedCall(
        tool_name=tool_name,
        site_ids=bound,
        date_from=params.date_from,
        date_to=params.date_to,
    )


class DemoHandler(BaseHTTPRequestHandler):
    """Minimal JSON demo API. Stdlib only."""

    server_version = "cinema-ops-public-demo/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        if os.environ.get("DEMO_VERBOSE"):
            super().log_message(fmt, *args)

    def _json(self, status: int, body: dict[str, Any]) -> None:
        data = json.dumps(body, default=str, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header(*_DATASET_HEADER)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        # ── /healthz ─────────────────────────────────────────────────────────
        if path == "/healthz":
            self._json(
                200,
                {
                    "ok": True,
                    "service": "cinema-ops-public-demo",
                    "dataset": "fixture",
                    "tools": len(IMPLEMENTED_TOOLS),
                },
            )
            return

        # ── /tools — manifest ─────────────────────────────────────────────────
        if path == "/tools":
            bearer = _bearer(self)
            if bearer is None:
                # Unauthenticated: return schema-level manifest (no scoping)
                self._json(
                    200,
                    {
                        "tools": [
                            {
                                "name": t,
                                "description": TOOL_DESCRIPTIONS[t],
                                "columns": list(TOOL_COLUMNS[t]),
                            }
                            for t in IMPLEMENTED_TOOLS
                        ],
                        "dataset": "fixture",
                    },
                )
                return

            token = resolve_demo_token(bearer)
            if token is None:
                self._json(401, {"error": "invalid_or_expired_token"})
                return

            self._json(
                200,
                {
                    "tools": [
                        {
                            "name": t,
                            "description": TOOL_DESCRIPTIONS[t],
                            "columns": list(TOOL_COLUMNS[t]),
                        }
                        for t in token.allowed_tools
                        if t in IMPLEMENTED_TOOLS
                    ],
                    "token_label": token.label,
                    "site_ids": list(token.site_ids),
                    "dataset": "fixture",
                },
            )
            return

        # ── /tools/<name> ─────────────────────────────────────────────────────
        prefix = "/tools/"
        if path.startswith(prefix):
            tool_name = path[len(prefix):]
            if not tool_name or "/" in tool_name:
                self._json(404, {"error": "not_found", "path": path})
                return

            bearer = _bearer(self)
            if bearer is None:
                self._json(401, {"error": "missing_bearer_token"})
                return

            token = resolve_demo_token(bearer)
            if token is None:
                self._json(401, {"error": "invalid_or_expired_token"})
                return

            raw_params = _params_from_qs(parse_qs(parsed.query))
            decision = _authorize_demo(token, tool_name, raw_params)

            if isinstance(decision, Refusal):
                body = decision.as_dict()
                body["token_label"] = token.label
                self._json(_http_status_for(decision), body)
                return

            assert isinstance(decision, AuthorizedCall)
            data_rows = rows_for(decision.tool_name, decision.site_ids)
            self._json(
                200,
                {
                    "tool": decision.tool_name,
                    "site_ids": decision.site_ids,
                    "rows": data_rows,
                    "refused": False,
                    "token_label": token.label,
                    "dataset": "fixture",
                },
            )
            return

        self._json(404, {"error": "not_found", "path": path})


class DemoServer(ThreadingHTTPServer):
    pass


def serve(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> DemoServer:
    return DemoServer((host, port), DemoHandler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="cinema-ops public demo server (VDE-54, stdlib only)"
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("DEMO_HOST", DEFAULT_HOST),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("DEMO_PORT", str(DEFAULT_PORT))),
    )
    args = parser.parse_args(argv)

    server = serve(host=args.host, port=args.port)
    print(
        f"cinema-ops demo listening on http://{args.host}:{args.port} "
        f"(dataset=fixture, tools={len(IMPLEMENTED_TOOLS)}, stdlib-only)",
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
