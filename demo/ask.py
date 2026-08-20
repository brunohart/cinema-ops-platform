"""VDE-57 — Loom demo beat 5: ask an operational question via the agent tool surface.

Calls get_site_revenue for a site-day and prints json.dumps of the outcome.

Exits 0 only when the tool returned an answer it actually resolved. `outcome ==
"ok"` alone is not that test: an unmatched key comes back ok with a zero, and a
zero is indistinguishable from a site that genuinely took no money — which is
the failure `agent.refuse` exists to prevent, reproduced inside the demo.

`site_key` is `gold.dim_site.site_key`, an md5 surrogate that differs per build,
so it is read from the environment rather than baked in as a literal:

    DEMO_SITE_KEY=$(psql "$DB" -Atc \\
      "select site_key from gold.fct_booking group by 1 order by count(*) desc limit 1")
    DEMO_DATE_KEY=$(psql "$DB" -Atc "select max(date_key) from gold.fct_booking")

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

site_key = os.environ.get("DEMO_SITE_KEY", "").strip()
date_key = os.environ.get("DEMO_DATE_KEY", "").strip()
if not site_key or not date_key:
    print(
        "DEMO_SITE_KEY and DEMO_DATE_KEY are required — see the module docstring for "
        "the two queries that read them out of gold. Refusing to ask about a site-day "
        "chosen at random, because the empty answer would look like a real one.",
        file=sys.stderr,
    )
    sys.exit(1)

from agent.tools import invoke_tool  # noqa: E402 — import after env-check

result = invoke_tool("get_site_revenue", {"site_key": site_key, "date_key": date_key})
print(json.dumps(result, indent=2))

if result.get("outcome") != "ok":
    sys.exit(1)

# The point of the beat: a resolved answer, not merely a successful call.
if not (result.get("result") or {}).get("found"):
    print(
        f"tool returned ok but resolved no rows for site_key={site_key} "
        f"date_key={date_key} — that is an absence, not an answer",
        file=sys.stderr,
    )
    sys.exit(1)
