"""Public demo server for cinema-ops-platform (VDE-54).

Stdlib only. MUST NOT import agent.tools, agent.limits, agent.server,
agent.site_performance, agent.db, or src.cli.

Run:
    PYTHONPATH=src python3 -m agent.demo_server [--host 0.0.0.0] [--port 8080]

Environment:
    PORT             — bind port (highest priority, matches Fly convention)
    AGENT_TOOLS_PORT — bind port (fallback)
    DEMO_HOST        — bind address (default 0.0.0.0)
    AGENT_DEMO_TOKEN_SHA256 — override token digest for testing
"""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import date
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from agent.catalog import IMPLEMENTED_TOOLS, TOOL_COLUMNS, TOOL_DESCRIPTIONS
from agent.demo_data import PUBLIC_DEMO_TOKEN, resolve_demo_token, rows_for
from agent.refuse import AuthorizedCall, Refusal, authorize

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8080

# Anchor date for deterministic retention checks against fixture rows (2026-07-10).
_ANCHOR_DATE = date(2026, 7, 10)

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


REPO_URL = "https://github.com/brunohart/cinema-ops-platform"


def _index_payload() -> dict[str, Any]:
    """What `/` says. One definition, rendered as JSON or as HTML."""
    return {
        "service": "cinema-ops-public-demo",
        "dataset": "fixture",
        "description": (
            "Bearer-scoped, read-only tool surface over fixture cinema data. "
            "The refusal policy is the same code the local Postgres-backed "
            "server runs; only the data source differs."
        ),
        "demo_token": PUBLIC_DEMO_TOKEN,
        "token_note": (
            "Public on purpose: scoped to sites 1-2 and three tools over "
            "fixture rows. Safety here is scope, not secrecy."
        ),
        "endpoints": [
            {"path": "/healthz", "auth": False, "description": "Liveness and tool count."},
            {"path": "/tools", "auth": True, "description": "Tool manifest for your token."},
            *(
                {
                    "path": f"/tools/{name}",
                    "auth": True,
                    "description": TOOL_DESCRIPTIONS[name].split(". ")[0] + ".",
                }
                for name in IMPLEMENTED_TOOLS
            ),
        ],
        "try_it": [
            f"curl -H 'Authorization: Bearer {PUBLIC_DEMO_TOKEN}' <base>/tools/list_sessions",
            "curl <base>/tools/list_sessions                      # 401 missing_bearer_token",
            f"curl -H 'Authorization: Bearer {PUBLIC_DEMO_TOKEN}' "
            "'<base>/tools/list_sessions?siteIds=3'   # 403 site_scope",
        ],
        "source": REPO_URL,
    }


def _index_html(payload: dict[str, Any]) -> str:
    """Minimal self-contained page. Stdlib only — no template engine, no CDN."""
    rows = "\n".join(
        "<tr><td><code>{}</code></td><td>{}</td><td>{}</td></tr>".format(
            escape(str(e["path"])),
            "bearer" if e["auth"] else "open",
            escape(str(e["description"])),
        )
        for e in payload["endpoints"]
    )
    curls = escape("\n".join(payload["try_it"]))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>cinema-ops public demo</title>
<style>
 :root {{ color-scheme: light dark; --fg:#1a1a1a; --bg:#fbfaf8; --mut:#6b7280;
          --line:#e5e2dd; --accent:#C08B4F; --code:#f3f1ed; }}
 @media (prefers-color-scheme: dark) {{
   :root {{ --fg:#e8e6e3; --bg:#16161a; --mut:#9aa0a6; --line:#2c2c33; --code:#1f1f25; }} }}
 * {{ box-sizing:border-box; }}
 body {{ margin:0; padding:2.5rem 1.25rem; background:var(--bg); color:var(--fg);
        font:16px/1.6 ui-sans-serif,-apple-system,Segoe UI,Roboto,sans-serif; }}
 main {{ max-width:52rem; margin:0 auto; }}
 h1 {{ font-size:1.5rem; margin:0 0 .25rem; letter-spacing:-.01em; }}
 .badge {{ display:inline-block; font-size:.75rem; font-weight:600; letter-spacing:.04em;
           text-transform:uppercase; color:var(--accent); border:1px solid var(--accent);
           border-radius:999px; padding:.1rem .55rem; vertical-align:middle; }}
 p.lede {{ color:var(--mut); margin:.5rem 0 2rem; }}
 h2 {{ font-size:.8rem; text-transform:uppercase; letter-spacing:.08em; color:var(--mut);
       margin:2rem 0 .6rem; }}
 table {{ width:100%; border-collapse:collapse; font-size:.9rem; }}
 td,th {{ text-align:left; padding:.5rem .6rem; border-bottom:1px solid var(--line);
          vertical-align:top; }}
 td:nth-child(2) {{ color:var(--mut); white-space:nowrap; width:1%; }}
 code {{ background:var(--code); padding:.1rem .35rem; border-radius:4px;
         font:.85em ui-monospace,SFMono-Regular,Menlo,monospace; }}
 pre {{ background:var(--code); padding:.9rem 1rem; border-radius:8px; overflow-x:auto;
        font:.82rem/1.7 ui-monospace,SFMono-Regular,Menlo,monospace; }}
 a {{ color:inherit; }}
 footer {{ margin-top:2.5rem; padding-top:1rem; border-top:1px solid var(--line);
           color:var(--mut); font-size:.85rem; }}
</style></head><body><main>
<h1>cinema-ops public demo <span class="badge">fixture data</span></h1>
<p class="lede">{escape(str(payload["description"]))}</p>

<h2>Endpoints</h2>
<table><tr><th>Path</th><th>Auth</th><th>What it does</th></tr>
{rows}
</table>

<h2>Demo token</h2>
<p><code>{escape(str(payload["demo_token"]))}</code><br>
<span style="color:var(--mut);font-size:.9rem">{escape(str(payload["token_note"]))}</span></p>

<h2>Try it</h2>
<pre>{curls}</pre>

<footer>Every response carries <code>X-Cinema-Ops-Dataset: fixture</code> — this
surface never touches live data. Source and the reasoning behind it:
<a href="{escape(REPO_URL)}">{escape(REPO_URL)}</a>. This page is also available
as JSON: <code>curl -H 'Accept: application/json' &lt;base&gt;/</code></footer>
</main></body></html>
"""


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

    def _html(self, status: int, markup: str) -> None:
        data = markup.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header(*_DATASET_HEADER)
        self.end_headers()
        self.wfile.write(data)

    def _wants_html(self) -> bool:
        """True for a browser, false for curl and every agent client."""
        return "text/html" in (self.headers.get("Accept") or "")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        # ── / — index ────────────────────────────────────────────────────────
        # VDE-62. This used to 404. The address resolved, the health check
        # passed, and a person who clicked the link read {"error":"not_found"}
        # and reasonably concluded the demo was down — a surface can be up and
        # still be dead to the only visitor who does not already know the
        # routes. Unknown paths below still 404; the root is not unknown.
        if path == "/":
            payload = _index_payload()
            if self._wants_html():
                self._html(200, _index_html(payload))
            else:
                self._json(200, payload)
            return

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
                self._json(401, {"error": "missing_bearer_token"})
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
                    "expires_at": token.expires_at.isoformat(),
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
            decision = authorize(token, tool_name, raw_params, today=_ANCHOR_DATE)  # type: ignore[arg-type]

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
        # `or`, not a get() default — a blank DEMO_HOST from a sourced .env is
        # present-and-empty, which get() passes straight through. Same fix as
        # agent/server.py; here it only mattered for the printed URL, because
        # DEFAULT_HOST is already 0.0.0.0 for the container.
        default=os.environ.get("DEMO_HOST") or DEFAULT_HOST,
    )
    _port_default = int(
        os.environ.get("PORT")
        or os.environ.get("AGENT_TOOLS_PORT")
        or DEFAULT_PORT
    )
    parser.add_argument(
        "--port",
        type=int,
        default=_port_default,
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
