#!/usr/bin/env python3
"""VDE-50 — dbt build exits non-zero on a model error; a *test* failure is a different exit path
and this is the guard for it.

Usage:
    python3 scripts/check_dbt_results.py [path]

Default path: dbt/target/run_results.json

Exit codes:
    0 — all results are passing or warn
    1 — one or more failing results, or the file is missing / unparseable
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_PASSING = {"success", "pass"}
_WARNING = {"warn"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail if any dbt result node has a non-passing status."
    )
    parser.add_argument(
        "path",
        nargs="?",
        default="dbt/target/run_results.json",
        help="Path to dbt run_results.json (default: dbt/target/run_results.json)",
    )
    args = parser.parse_args(argv)

    results_path = Path(args.path)

    if not results_path.exists():
        print(f"error: run_results.json not found: {results_path}", file=sys.stderr)
        return 1

    try:
        data = json.loads(results_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        print(f"error: could not parse {results_path}: {exc}", file=sys.stderr)
        return 1

    results = data.get("results", [])
    total = len(results)
    passing = 0
    warning = 0
    failing = 0

    for node in results:
        status = (node.get("status") or "").lower()
        unique_id = node.get("unique_id", "<unknown>")
        failures = node.get("failures") or 0
        message = node.get("message") or ""
        first_line = message.splitlines()[0] if message else ""

        if status in _PASSING:
            passing += 1
        elif status in _WARNING:
            warning += 1
            print(f"warn  {unique_id}  status={status}  failures={failures}  {first_line}")
        else:
            failing += 1
            print(f"FAIL  {unique_id}  status={status}  failures={failures}  {first_line}")

    print(f"dbt results: {total} total, {passing} passing, {warning} warn, {failing} failing")

    return 1 if failing > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
