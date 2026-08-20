"""Vercel Python-runtime entry point for the public demo surface (VDE-62).

VDE-54 committed `fly.toml` and `Dockerfile.demo` but never ran the deploy, so
`cinema-ops-platform-demo.fly.dev` was NXDOMAIN for the whole time the README
pointed at it. This module is a second *host*, not a second implementation: it
inherits `agent.demo_server.DemoHandler` and overrides nothing, so routing,
token resolution and the refusal policy keep exactly one definition. That is
the point — a demo that refuses differently depending on where it runs proves
nothing about the policy it exists to demonstrate.

The empty subclass is load-bearing and cannot be shortened to
`handler = DemoHandler`. Vercel decides whether a file under `/api` is a
function by reading it for a top-level `app`, `application`, or `handler`
*definition*; an alias assignment is not one, so with the alias the whole
repository was served by `@vercel/static`, `api/index.py` was downloaded as
text, and every route 404'd. `class handler(DemoHandler)` is the smallest thing
the detector accepts. `prove_public_demo.sh` section 15 asserts the body stays
empty, which is the property that actually matters here.
"""

from __future__ import annotations

import sys
from pathlib import Path

# The function bundle preserves the repository layout, so `src/` sits beside
# `api/` and is not importable until it is on the path. Derived from __file__,
# not the cwd — the runtime's working directory is not guaranteed to be root.
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agent.demo_server import DemoHandler  # noqa: E402


class handler(DemoHandler):  # noqa: N801  (Vercel requires this exact name)
    """The demo server, hosted on Vercel. Overrides nothing, by design."""
