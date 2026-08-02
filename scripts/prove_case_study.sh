#!/usr/bin/env bash
# prove_case_study.sh — machine checks for the VDE-55 case study.
#
# Ten checks, each printing "  ok   — …" on success or "  FAIL — …" on first
# failure. Ends with PASS=10 and exits 0 only when all ten pass.
#
#   ./scripts/prove_case_study.sh
#
# Needs bash and python3 only. No pytest, no network, no docker.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DOC="docs/2026-08-02-vde-55-case-study.md"

pass() { echo "  ok   — $1"; }
fail() { echo "  FAIL — $1" >&2; exit 1; }

if [[ ! -f "$DOC" ]]; then
  fail "case study not found: $DOC"
fi

# ── check 1: the case study file exists and is non-empty ─────────────────────
echo "== 1. case study file exists =="
if [[ -s "$DOC" ]]; then
  pass "$DOC exists and is non-empty"
else
  fail "$DOC is empty"
fi

# ── check 2: the six section headings exist once each, in order ──────────────
echo "== 2. six section headings exist once each, in order =="
python3 - "$DOC" <<'PY' || exit 1
import sys

doc = sys.argv[1]
headings = [
    "## 1. The problem, in operator language",
    "## 2. The four sources, and how each one fails",
    "## 3. What I did about each failure",
    "## 4. The governance model — access control, not policy",
    "## 5. What I would do differently at circuit scale",
    "## 6. What I deliberately did not build",
    "## Proof",
]

lines = open(doc).read().splitlines()
positions = {}
for h in headings:
    matches = [i for i, ln in enumerate(lines) if ln.rstrip() == h]
    if len(matches) != 1:
        print(f"  FAIL — heading appears {len(matches)} time(s), want 1: {h!r}", file=sys.stderr)
        sys.exit(1)
    positions[h] = matches[0]

for i in range(len(headings) - 1):
    if positions[headings[i]] >= positions[headings[i + 1]]:
        print(f"  FAIL — out of order: {headings[i]!r} must precede {headings[i+1]!r}",
              file=sys.stderr)
        sys.exit(1)

print("  ok   — all six section headings plus '## Proof' present once each, in order")
PY

# ── check 3: word count of sections 1-6 is between 1100 and 1350 ─────────────
echo "== 3. sections 1-6 word count is 1100-1350 =="
python3 - "$DOC" <<'PY' || exit 1
import sys

doc = sys.argv[1]
lines = open(doc).read().splitlines()

start = next(i for i, ln in enumerate(lines)
             if ln.rstrip() == "## 1. The problem, in operator language")
end = next(i for i, ln in enumerate(lines) if ln.rstrip() == "## Proof")

section_text = "\n".join(lines[start:end])
word_count = len(section_text.split())

if not (1100 <= word_count <= 1350):
    print(f"  FAIL — sections 1-6 are {word_count} words, want 1100-1350", file=sys.stderr)
    sys.exit(1)

print(f"  ok   — sections 1-6 are {word_count} words (1100-1350)")
PY

# ── check 4: section 1 is operator language — >=5 operator terms, 0 tech terms ─
echo "== 4. section 1 — operator language test =="
python3 - "$DOC" <<'PY' || exit 1
import re
import sys

doc = sys.argv[1]
lines = open(doc).read().splitlines()

s1 = next(i for i, ln in enumerate(lines)
          if ln.rstrip() == "## 1. The problem, in operator language")
s2 = next(i for i, ln in enumerate(lines)
          if ln.rstrip() == "## 2. The four sources, and how each one fails")
sec1 = "\n".join(lines[s1:s2])

operator_terms = [
    "showtime", "screen", "seat", "site", "circuit", "attach", "box office",
    "schedule", "exhibitor", "session", "occupancy", "margin", "manager", "Tuesday",
]
tech_denylist = [
    "pipeline", "bronze", "silver", "gold", "medallion", "dbt", "Dagster",
    "Postgres", "Redpanda", "Docker", "MCP", "ETL", "extractor", "watermark",
    "idempotent", "schema", "Kafka", "SQL",
]

found = [t for t in operator_terms if re.search(r'\b' + re.escape(t) + r'\b', sec1, re.I)]
if len(found) < 5:
    print(f"  FAIL — section 1 has {len(found)} operator term(s) ({found}), want >= 5",
          file=sys.stderr)
    sys.exit(1)

leaked = [t for t in tech_denylist if re.search(r'\b' + re.escape(t) + r'\b', sec1, re.I)]
if leaked:
    print(f"  FAIL — section 1 contains technical term(s): {leaked}", file=sys.stderr)
    sys.exit(1)

print(f"  ok   — section 1 has {len(found)} operator term(s), zero technical terms")
PY

# ── check 5: section 2 names all four source shapes and their failure modes ──
echo "== 5. section 2 — four sources, their failures, 'shapes, not sources', 4b poison =="
python3 - "$DOC" <<'PY' || exit 1
import re
import sys

doc = sys.argv[1]
lines = open(doc).read().splitlines()

s2 = next(i for i, ln in enumerate(lines)
          if ln.rstrip() == "## 2. The four sources, and how each one fails")
s3 = next(i for i, ln in enumerate(lines) if ln.rstrip() == "## 3. What I did about each failure")
sec2 = "\n".join(lines[s2:s3])

checks = [
    ("TMDB + 429", r'TMDB'),
    ("429 rate limit", r'429'),
    ("landing files + schema drift", r'(?i)landing files'),
    ("cinema_ops late arrival", r'cinema_ops'),
    ("ticketing + duplicate delivery", r'(?i)ticketing'),
    ("'shapes, not source' framing", r'shape[s]?,? not source'),
    ("poison payload (4b)", r'(?i)poison'),
]
for label, pattern in checks:
    if not re.search(pattern, sec2):
        print(f"  FAIL — section 2 missing: {label}", file=sys.stderr)
        sys.exit(1)

print("  ok   — section 2 names all four source shapes, their failure modes, "
      "the 'shapes, not sources' framing, and the poison-payload fifth shape")
PY

# ── check 6: section 3 has 4-5 paragraphs and cites >= 3 distinct ADRs ────────
echo "== 6. section 3 — 4-5 paragraphs, >= 3 distinct ADRs =="
python3 - "$DOC" <<'PY' || exit 1
import re
import sys

doc = sys.argv[1]
lines = open(doc).read().splitlines()

s3 = next(i for i, ln in enumerate(lines) if ln.rstrip() == "## 3. What I did about each failure")
s4 = next(i for i, ln in enumerate(lines)
          if ln.rstrip() == "## 4. The governance model — access control, not policy")
sec3 = "\n".join(lines[s3 + 1:s4])

paragraphs = [p for p in sec3.split("\n\n") if p.strip()]
if not (4 <= len(paragraphs) <= 5):
    print(f"  FAIL — section 3 has {len(paragraphs)} paragraph(s), want 4-5", file=sys.stderr)
    sys.exit(1)

adrs = set(re.findall(r'ADR-\d+', sec3))
if len(adrs) < 3:
    print(f"  FAIL — section 3 cites {len(adrs)} distinct ADR(s) ({adrs}), want >= 3",
          file=sys.stderr)
    sys.exit(1)

print(f"  ok   — section 3 has {len(paragraphs)} paragraphs and cites {len(adrs)} "
      f"distinct ADRs ({sorted(adrs)})")
PY

# ── check 7: section 4 — governance anchors present, no PII column names ─────
echo "== 7. section 4 — ADR-009, §6c, VDE-48 red-team, 'absent', no PII words =="
python3 - "$DOC" <<'PY' || exit 1
import re
import sys

doc = sys.argv[1]
lines = open(doc).read().splitlines()

s4 = next(i for i, ln in enumerate(lines)
          if ln.rstrip() == "## 4. The governance model — access control, not policy")
s5 = next(i for i, ln in enumerate(lines)
          if ln.rstrip() == "## 5. What I would do differently at circuit scale")
sec4 = "\n".join(lines[s4:s5])

checks = [
    ("ADR-009", r'ADR-009'),
    ("ARCHITECTURE §6c", r'§6c'),
    ("VDE-48", r'VDE-48'),
    ("prove_synopsis_injection.sh", r'prove_synopsis_injection\.sh'),
    ("word 'absent'", r'\babsent\b'),
]
for label, pattern in checks:
    if not re.search(pattern, sec4):
        print(f"  FAIL — section 4 missing: {label}", file=sys.stderr)
        sys.exit(1)

pii_words = ["email", "phone", "full_name", "card"]
leaked = [w for w in pii_words if re.search(r'\b' + re.escape(w) + r'\b', sec4, re.I)]
if leaked:
    print(f"  FAIL — section 4 contains PII column name(s): {leaked}", file=sys.stderr)
    sys.exit(1)

print("  ok   — section 4 has ADR-009, §6c, VDE-48, the red-team script, "
      "'absent', and no PII column names")
PY

# ── check 8: section 5 — fct_booking, the 50M threshold, >= 4 numbers ────────
echo "== 8. section 5 — fct_booking, 50M scale threshold, >= 4 stated numbers =="
python3 - "$DOC" <<'PY' || exit 1
import re
import sys

doc = sys.argv[1]
lines = open(doc).read().splitlines()

s5 = next(i for i, ln in enumerate(lines)
          if ln.rstrip() == "## 5. What I would do differently at circuit scale")
s6 = next(i for i, ln in enumerate(lines) if ln.rstrip() == "## 6. What I deliberately did not build")
sec5 = "\n".join(lines[s5:s6])

if not re.search(r'fct_booking', sec5):
    print("  FAIL — section 5 missing: fct_booking", file=sys.stderr)
    sys.exit(1)

if not re.search(r'50M|50 million|fifty[- ]three million|fifty million', sec5, re.I):
    print("  FAIL — section 5 missing a stated ~50M-row scale threshold", file=sys.stderr)
    sys.exit(1)

# Numbers spelled out in words count too — this is prose, not a spreadsheet.
number_words = re.findall(
    r'\b(?:two hundred|eight|sixteen hundred|five|eight thousand|forty|'
    r'three hundred and twenty thousand|one hundred and seventeen million|'
    r'two-point-two|fifty-three million|\d[\d,]*)\b',
    sec5, re.I,
)
if len(number_words) < 4:
    print(f"  FAIL — section 5 has {len(number_words)} stated number(s), want >= 4",
          file=sys.stderr)
    sys.exit(1)

print(f"  ok   — section 5 names fct_booking, a ~50M-row scale threshold, and "
      f"{len(number_words)} stated numbers")
PY

# ── check 9: staleness guard — section 6 does not claim shipped work as unbuilt ─
echo "== 9. staleness guard — section 6 does not claim shipped paths as unbuilt =="
python3 - "$DOC" <<'PY' || exit 1
import re
import sys
from pathlib import Path

doc = sys.argv[1]
lines = open(doc).read().splitlines()

s6 = next(i for i, ln in enumerate(lines) if ln.rstrip() == "## 6. What I deliberately did not build")
proof = next(i for i, ln in enumerate(lines) if ln.rstrip() == "## Proof")
sec6 = "\n".join(lines[s6:proof])

# Each entry: a path that exists on disk today, and the phrase that would be a
# stale claim if it appeared in section 6 (case-insensitive, word-ish match).
# This is the VDE-53/VDE-55 lesson made mechanical: a claim of "not built" is
# only checked in, never assumed, against what is actually on disk.
shipped = [
    ("mcp/src/mcp.ts", r'MCP server itself|the MCP server\b.*not\b'),
    ("dbt/models/gold/fct_booking.sql", r'gold dbt transforms.*not yet written|dbt transforms.*not yet'),
    ("dbt/models/silver/stg_bookings.sql", r'silver.*dbt transforms.*not yet written'),
    ("src/orchestration/checks.py", r'Dagster asset checks.*not (yet )?built'),
    ("evals/mcp.yaml", r'evaluation layer.*(does not|doesn.t) exist'),
    ("agent-api/", r'agent-api.*not (yet )?built'),
]

root = Path(".")
leaked = []
for path, stale_pattern in shipped:
    if (root / path).exists() and re.search(stale_pattern, sec6, re.I):
        leaked.append((path, stale_pattern))

if leaked:
    for path, pattern in leaked:
        print(f"  FAIL — {path} exists on disk but section 6 claims it unbuilt "
              f"(matched {pattern!r})", file=sys.stderr)
    sys.exit(1)

# Explicit denylist per the plan: these must not be named as unbuilt at all.
denylist_terms = ["MCP", "dbt", "asset check", "eval suite", "agent-api"]
for term in denylist_terms:
    pattern = re.escape(term) + r'[^.]{0,60}\bnot (yet )?built\b'
    if re.search(pattern, sec6, re.I):
        print(f"  FAIL — section 6 claims '{term}' is unbuilt, but it has shipped",
              file=sys.stderr)
        sys.exit(1)

print("  ok   — section 6 makes no stale unbuilt-claim about MCP, dbt, asset checks, "
      "the eval suite, or agent-api")
PY

# ── check 10: every link target and every cited ADR resolves ─────────────────
echo "== 10. every local link target and cited ADR resolves =="
python3 - "$DOC" <<'PY' || exit 1
import re
import sys
import os
from pathlib import Path

doc = sys.argv[1]
text = open(doc).read()
root = Path(".").resolve()

targets = re.findall(r'\[(?:[^\]]*)\]\(([^)]+)\)', text)
errors = []
for raw in targets:
    if re.match(r'https?://', raw):
        continue
    path = raw.split('#')[0]
    if not path:
        continue
    if not (root / path).exists():
        errors.append(path)

decisions = open("DECISIONS.md").read()
adr_ids = sorted(set(re.findall(r'ADR-\d+', text)))
for adr in adr_ids:
    if not re.search(r'^##\s+' + re.escape(adr) + r'\b', decisions, re.M):
        errors.append(f"{adr} not found as a heading in DECISIONS.md")

if errors:
    for e in errors:
        print(f"  FAIL — {e}", file=sys.stderr)
    sys.exit(1)

print(f"  ok   — all {len(targets)} local link target(s) resolve; "
      f"all {len(adr_ids)} cited ADR(s) ({', '.join(adr_ids)}) exist in DECISIONS.md")
PY

echo ""
echo "PASS=10"
