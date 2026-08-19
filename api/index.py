"""Vercel Python-runtime entry point for the public demo surface (VDE-62).

VDE-54 committed `fly.toml` and `Dockerfile.demo` but never ran the deploy, so
`cinema-ops-platform-demo.fly.dev` was NXDOMAIN for the whole time the README
pointed at it. This module is a second *host*, not a second implementation: it
re-exports `agent.demo_server.DemoHandler` unchanged, so routing, token
resolution and the refusal policy keep exactly one definition. There is nothing
here for the two hosts to disagree about, which is the point — a demo that
refuses differently depending on where it runs proves nothing about the policy.

Vercel's Python runtime invokes a module-level `handler` that subclasses
BaseHTTPRequestHandler. `vercel.json` rewrites every path to this function.
"""

from __future__ import annotations

import sys
from pathlib import Path

# The function bundle preserves the repository layout (vercel.json
# `includeFiles`), so `src/` sits beside `api/` and is not importable until it
# is on the path. Derived from __file__, not the cwd — the runtime's working
# directory is not guaranteed to be the project root.
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agent.demo_server import DemoHandler  # noqa: E402

# Vercel looks up this exact name. Assigning the shared class — rather than
# subclassing it — is deliberate: a subclass is a place for the hosts to drift.
handler = DemoHandler
