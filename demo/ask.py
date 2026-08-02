"""VDE-57 — Loom demo beat 5: ask an operational question via the agent tool surface.

Calls get_site_revenue for site_key=10, date_key=20240701.
Prints json.dumps of the outcome. Exits 0 only if outcome == 'ok'.
AGENT_DATABASE_URL must be set; there is no default DSN.
Imports only from agent.tools — no hardcoded DSN; no literal JSON results.
"""

from __future__ import annotations

import json
import os
import sys

if not os.environ.get("AGENT_DATABASE_URL"):
    print("AGENT_DATABASE_URL is required; set it before running demo/ask.py", file=sys.stderr)
    sys.exit(1)

from agent.tools import invoke_tool  # noqa: E402 — import after env-check

result = invoke_tool("get_site_revenue", {"site_key": 10, "date_key": 20240701})
print(json.dumps(result, indent=2))

if result.get("outcome") != "ok":
    sys.exit(1)
