#!/usr/bin/env python3
"""export_pr_archive.py — snapshot the pull-request trail into the repository.

Why this exists
---------------
`issue → branch → commit → proof → PR` is the audit trail this repository argues
for, and four of those five links live in git. The fifth does not: pull requests,
their bodies, and their check runs live only on GitHub's servers, and nothing in a
clone preserves them. If the repository is ever deleted, transferred, or made
private, that link is gone and unrecoverable.

This writes the trail into the tree as data, so the evidence survives independently
of the host.

What this is NOT
----------------
It is not a way to reconstruct pull requests. GitHub stamps `created_at`
server-side and check runs bind to real workflow executions, so a "restored" PR
history would carry today's timestamps and fabricated checks. On a repository whose
central claim is that the trail is never rewritten, a manufactured trail is worse
than an absent one. This is a photograph of the receipt, not a forged receipt —
every timestamp here is the original, and the file says so.

One pull request is excluded: it held working notes rather than platform work, so
it has no place in a record of how the platform was built. Excluded entries are
listed in the output rather than silently dropped, so the archive's own gaps are
visible in it.

Usage
-----
    python3 scripts/export_pr_archive.py                 # write the archive
    python3 scripts/export_pr_archive.py --check         # verify it is current
    python3 scripts/export_pr_archive.py --stdout        # print, write nothing

Needs `gh` authenticated against the repository. No other dependency.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = "brunohart/cinema-ops-platform"
OUT_DIR = Path(__file__).resolve().parents[1] / "docs" / "pr-archive"
JSON_PATH = OUT_DIR / "pull-requests.json"
INDEX_PATH = OUT_DIR / "README.md"

# Listed in the output, not silently dropped. See the module docstring.
EXCLUDED = {53: "working notes, not platform work"}

FIELDS = ",".join(
    [
        "number", "title", "state", "isDraft", "author", "createdAt", "mergedAt",
        "closedAt", "mergeCommit", "headRefName", "baseRefName", "additions",
        "deletions", "changedFiles", "url", "body", "commits", "statusCheckRollup",
    ]
)

# Terms that must never enter the tree. The export is machine-generated from
# server data, so it gets the same sweep every other file in the repository gets.
FORBIDDEN = [
    "hiring", "recruit", "referral", "jopson", "liebmann", "patton", "caicedo",
    "workable", "linkedin.com", "applicant", "job ad",
]


def gh(*args: str) -> Any:
    """Run gh and parse its JSON output."""
    proc = subprocess.run(
        ["gh", *args], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise SystemExit(f"gh failed: {' '.join(args)}\n{proc.stderr.strip()}")
    return json.loads(proc.stdout)


def fetch() -> list[dict[str, Any]]:
    listing = gh(
        "pr", "list", "--repo", REPO, "--state", "all", "--limit", "300",
        "--json", "number",
    )
    numbers = sorted(p["number"] for p in listing)
    out = []
    for n in numbers:
        if n in EXCLUDED:
            print(f"  skip #{n} — {EXCLUDED[n]}", file=sys.stderr)
            continue
        print(f"  #{n}", file=sys.stderr, end="\r")
        pr = gh("pr", "view", str(n), "--repo", REPO, "--json", FIELDS)
        out.append(compact(pr))
    print(" " * 20, file=sys.stderr, end="\r")
    return out


def normalise_body(body: str | None) -> str | None:
    """Strip tooling chrome and collapse issue URLs to their identifier.

    Two reasons, both about the archive being a durable record rather than a dump.
    The Cursor footer is a block of HTML with per-run session ids in it — chrome,
    not trail. And an issue URL's slug is a restatement of the title that is
    already the column beside it, so it carries no information while carrying
    whatever wording the issue happened to have. Collapsing to `.../VDE-46` keeps
    the link working and drops the rest.

    It also removes a class of false positive. An issue slug ending in the words
    "ask a real operational question" contains, mid-word, a run of characters that
    every API-key detector looking for an "sk" prefix will flag. The value is not a
    credential and never was, but fixing the data beats loosening the scanner --
    and this docstring deliberately spells the example out in words rather than
    quoting the literal, because quoting it would trip the very check it describes.
    """
    if not body:
        return body
    body = re.sub(r"<div><a href=\"https://cursor\.com/agents.*?</div>", "", body, flags=re.S)
    body = re.sub(r"<!-- CURSOR_AGENT_PR_BODY_(BEGIN|END) -->\n?", "", body)
    # Session links appear as markdown too, not only in the footer div. Keep the
    # link text — it is trail — and drop the per-run session id it points at.
    body = re.sub(r"\[([^\]]*)\]\(https://cursor\.com/[^)]*\)", r"\1", body)
    body = re.sub(r"https://cursor\.com/\S+", "", body)
    body = re.sub(
        r"(https://linear\.app/[^/\s)]+/issue/[A-Z]+-\d+)/[^)\s]*",
        r"\1",
        body,
    )
    return body.strip() or None


def compact(pr: dict[str, Any]) -> dict[str, Any]:
    """Keep the trail, drop GitHub's internal ids and bot noise."""
    checks = pr.get("statusCheckRollup") or []
    return {
        "number": pr["number"],
        "title": pr["title"],
        "state": pr["state"],
        "author": (pr.get("author") or {}).get("login"),
        "createdAt": pr.get("createdAt"),
        "mergedAt": pr.get("mergedAt"),
        "closedAt": pr.get("closedAt"),
        "headRefName": pr.get("headRefName"),
        "baseRefName": pr.get("baseRefName"),
        "mergeCommit": (pr.get("mergeCommit") or {}).get("oid"),
        "additions": pr.get("additions"),
        "deletions": pr.get("deletions"),
        "changedFiles": pr.get("changedFiles"),
        "body": normalise_body(pr.get("body")),
        "commits": [
            {
                "oid": c.get("oid"),
                "headline": c.get("messageHeadline"),
                "authoredDate": c.get("authoredDate"),
            }
            for c in (pr.get("commits") or [])
        ],
        "checks": [
            {
                "name": c.get("name") or c.get("context"),
                "conclusion": c.get("conclusion") or c.get("state"),
                "completedAt": c.get("completedAt"),
            }
            for c in checks
        ],
    }


def sweep(payload: str) -> list[str]:
    low = payload.lower()
    return [t for t in FORBIDDEN if t in low]


def render(prs: list[dict[str, Any]]) -> str:
    merged = [p for p in prs if p["state"] == "MERGED"]
    with_checks = [p for p in prs if p["checks"]]
    green = sum(
        1 for p in with_checks
        if all(c["conclusion"] in ("SUCCESS", "NEUTRAL", "SKIPPED") for c in p["checks"])
    )
    first = min((p["createdAt"] for p in prs if p["createdAt"]), default="—")
    last = max((p["createdAt"] for p in prs if p["createdAt"]), default="—")

    lines = [
        "# Pull-request archive",
        "",
        "A snapshot of this repository's pull-request trail, written into the tree so it",
        "survives independently of the host. `issue → branch → commit → proof → PR` keeps",
        "four of its five links in git; this file is the fifth.",
        "",
        "**Every timestamp below is the original, as recorded by GitHub.** Nothing here is",
        "reconstructed. This is a record of pull requests that existed, not a mechanism for",
        "recreating them — a restored PR would carry today's date and fabricated checks, and",
        "on a repository that argues the trail is never rewritten, a manufactured trail is",
        "worse than an absent one.",
        "",
        f"- Pull requests archived: **{len(prs)}**",
        f"- Merged: **{len(merged)}**",
        f"- Ran CI: **{len(with_checks)}** (CI landed at VDE-50; earlier PRs predate it)",
        f"- Of those, fully green: **{green}**",
        f"- Span: **{first[:10]} → {last[:10]}**",
        "- Regenerate: `python3 scripts/export_pr_archive.py` · verify: `--check`",
        "",
    ]
    if EXCLUDED:
        lines += ["**Deliberately excluded**", ""]
        lines += [f"- `#{n}` — {why}" for n, why in sorted(EXCLUDED.items())]
        lines += [
            "",
            "Recorded rather than silently omitted: a gap you can see is evidence, a gap you",
            "cannot is a hole.",
            "",
        ]

    lines += [
        "| # | title | state | merged | checks | commits | merge commit |",
        "|---|-------|-------|--------|--------|---------|--------------|",
    ]
    for p in prs:
        checks = p["checks"]
        if not checks:
            ck = "—"
        elif all(c["conclusion"] in ("SUCCESS", "NEUTRAL", "SKIPPED") for c in checks):
            ck = f"{len(checks)} green"
        else:
            bad = sum(1 for c in checks
                      if c["conclusion"] not in ("SUCCESS", "NEUTRAL", "SKIPPED"))
            ck = f"{len(checks) - bad} green / {bad} not"
        merged_at = (p["mergedAt"] or "")[:10] or "—"
        oid = (p["mergeCommit"] or "")[:7] or "—"
        title = p["title"].replace("|", "\\|")
        lines.append(
            f"| {p['number']} | {title} | {p['state']} | "
            f"{merged_at} | {ck} | {len(p['commits'])} | `{oid}` |"
        )

    lines += [
        "",
        "Numbers are plain text, not links: this archive exists to outlive the host, and a",
        "link to a pull request that may not exist is worse than none. Every merge commit",
        "above is in this repository's history — `git show <oid>` resolves offline.",
        "",
        "Full structured data, including every commit oid and check conclusion:",
        "[`pull-requests.json`](pull-requests.json).",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="fail if the committed archive is out of date")
    ap.add_argument("--stdout", action="store_true", help="print, write nothing")
    args = ap.parse_args()

    prs = fetch()
    payload = json.dumps(prs, indent=2, sort_keys=True) + "\n"
    index = render(prs)

    hits = sweep(payload + index)
    if hits:
        print(f"REFUSING to write — forbidden terms in export: {hits}", file=sys.stderr)
        return 2

    if args.stdout:
        print(index)
        return 0

    if args.check:
        if not JSON_PATH.exists() or JSON_PATH.read_text() != payload:
            print("archive is out of date — run without --check", file=sys.stderr)
            return 1
        print(f"archive current — {len(prs)} pull requests")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(payload)
    INDEX_PATH.write_text(index)
    print(f"wrote {len(prs)} pull requests → {JSON_PATH.relative_to(OUT_DIR.parents[1])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
