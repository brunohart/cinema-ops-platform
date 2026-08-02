#!/usr/bin/env bash
# prove_readme_structure.sh — machine checks for the VDE-53 README restructure.
#
# Nine checks, each printing "  ok   — …" on success or "  FAIL — …" on first failure.
# Ends with PASS=9 and exits 0 only when all nine pass.
#
#   ./scripts/prove_readme_structure.sh
#
# Needs bash and python3 only. No pytest, no network, no docker.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

README="README.md"
ARCH="ARCHITECTURE.md"

pass() { echo "  ok   — $1"; }
fail() { echo "  FAIL — $1" >&2; exit 1; }

# ── check 1: seven anchors exist exactly once each and in file order ──────────
echo "== 1. seven section anchors exist once each, in order =="
python3 - <<'PY' || exit 1
import sys, re

anchors = [
    "# cinema-ops-platform",
    "## What it looks like",
    "## What happens when a source breaks",
    "## 60-second quickstart",
    "## The agent interface, and why it is safe",
    "## What I deliberately did not build",
    "## Below the fold — the long form",
]

text = open("README.md").read()
lines = text.splitlines()

positions = {}
for anchor in anchors:
    # match the heading exactly (allow for trailing whitespace)
    matches = [i for i, ln in enumerate(lines) if ln.rstrip() == anchor]
    if len(matches) == 0:
        print(f"  FAIL — anchor not found: {anchor!r}", file=sys.stderr)
        sys.exit(1)
    if len(matches) > 1:
        print(f"  FAIL — anchor appears {len(matches)} times: {anchor!r}", file=sys.stderr)
        sys.exit(1)
    positions[anchor] = matches[0]

for i in range(len(anchors) - 1):
    if positions[anchors[i]] >= positions[anchors[i+1]]:
        print(f"  FAIL — out of order: {anchors[i]!r} (line {positions[anchors[i]]+1}) "
              f"must precede {anchors[i+1]!r} (line {positions[anchors[i+1]]+1})", file=sys.stderr)
        sys.exit(1)

print("  ok   — all seven anchors present once each, in order")
PY

# ── check 2: one paragraph, one sentence-ending period, ≤ 45 words ───────────
echo "== 2. opening paragraph: one sentence-ending period, ≤ 45 words =="
python3 - <<'PY' || exit 1
import sys, re

lines = open("README.md").read().splitlines()

# Find H1 line
h1 = next((i for i, ln in enumerate(lines) if ln.rstrip() == "# cinema-ops-platform"), None)
if h1 is None:
    print("  FAIL — H1 not found", file=sys.stderr)
    sys.exit(1)

# Find first ## after H1
h2 = next((i for i in range(h1+1, len(lines)) if re.match(r'^## ', lines[i])), None)
if h2 is None:
    print("  FAIL — no ## found after H1", file=sys.stderr)
    sys.exit(1)

# Collect non-empty paragraphs between H1 and first ##
between = lines[h1+1:h2]
paragraphs = []
current = []
for ln in between:
    stripped = ln.strip()
    if stripped == "---" or stripped == "":
        if current:
            paragraphs.append(" ".join(current))
            current = []
    else:
        current.append(stripped)
if current:
    paragraphs.append(" ".join(current))

non_empty = [p for p in paragraphs if p.strip()]
if len(non_empty) != 1:
    print(f"  FAIL — expected 1 non-empty paragraph between H1 and first ##, found {len(non_empty)}", file=sys.stderr)
    sys.exit(1)

para = non_empty[0]
# Count sentence-ending periods (not decimals or abbreviations — simple: count '.' not preceded by digit)
period_count = len(re.findall(r'(?<!\d)\.(?!\d)', para))
if period_count != 1:
    print(f"  FAIL — paragraph has {period_count} sentence-ending period(s), want exactly 1", file=sys.stderr)
    sys.exit(1)

words = para.split()
if len(words) > 45:
    print(f"  FAIL — paragraph is {len(words)} words, limit is 45", file=sys.stderr)
    sys.exit(1)

print(f"  ok   — one paragraph, one period, {len(words)} words (≤ 45)")
PY

# ── check 3: no img.shields.io before slot-2 <img, no <img before H1 ─────────
echo "== 3. badge ordering — shields.io after slot-2 image, no <img before H1 =="
python3 - <<'PY' || exit 1
import sys, re

lines = open("README.md").read().splitlines()

h1_line = next((i for i, ln in enumerate(lines) if ln.rstrip() == "# cinema-ops-platform"), None)
if h1_line is None:
    print("  FAIL — H1 not found", file=sys.stderr)
    sys.exit(1)

# No <img before H1
for i in range(h1_line):
    if re.search(r'<img', lines[i], re.IGNORECASE):
        print(f"  FAIL — <img found before H1 at line {i+1}", file=sys.stderr)
        sys.exit(1)

# Find the slot-2 <img (lineage PNG)
slot2_line = None
for i in range(h1_line, len(lines)):
    if re.search(r'<img[^>]+2026-07-31-vde-23-lineage-graph', lines[i]):
        slot2_line = i
        break

if slot2_line is None:
    print("  FAIL — slot-2 lineage PNG <img not found", file=sys.stderr)
    sys.exit(1)

# No img.shields.io before slot-2
for i in range(h1_line, slot2_line):
    if "img.shields.io" in lines[i]:
        print(f"  FAIL — img.shields.io appears before slot-2 image at line {i+1}", file=sys.stderr)
        sys.exit(1)

print("  ok   — no shields.io before slot-2 image, no <img before H1")
PY

# ── check 4: every local link and image target resolves on disk ───────────────
echo "== 4. every local link and image target resolves on disk =="
python3 - <<'PY' || exit 1
import sys, re, os, urllib.parse

text = open("README.md").read()
root = os.getcwd()

# Find all markdown links [text](target) and <img src="...">
targets = re.findall(r'\[(?:[^\]]*)\]\(([^)]+)\)', text)
targets += re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', text, re.IGNORECASE)

errors = []
for raw in targets:
    # Skip http(s) URLs
    if re.match(r'https?://', raw):
        continue
    # Strip fragment
    path = raw.split('#')[0]
    if not path:
        continue
    # URL-decode
    path = urllib.parse.unquote(path)
    full = os.path.join(root, path)
    if not os.path.exists(full):
        errors.append(path)

if errors:
    for e in errors:
        print(f"  FAIL — local target does not exist on disk: {e}", file=sys.stderr)
    sys.exit(1)

print(f"  ok   — all {len([t for t in targets if not re.match(r'https?://', t) and t.split('#')[0]])} local targets resolve")
PY

# ── check 5: section-3 table rows match ARCHITECTURE.md §2 source column ──────
echo "== 5. section-3 failure-mode table matches ARCHITECTURE.md §2 sources =="
python3 - <<'PY' || exit 1
import sys, re

def extract_table_rows(filepath, section_marker):
    """Return list of (source, how_it_fails) pairs from the first markdown table after section_marker."""
    lines = open(filepath).read().splitlines()
    start = None
    for i, ln in enumerate(lines):
        if section_marker in ln:
            start = i
            break
    if start is None:
        print(f"  FAIL — section marker not found in {filepath}: {section_marker!r}", file=sys.stderr)
        sys.exit(1)

    rows = []
    in_table = False
    for ln in lines[start:]:
        if re.match(r'^\|', ln):
            in_table = True
            cells = [c.strip() for c in ln.split('|')]
            # Remove empty first/last from split
            cells = [c for c in cells if c]
            # Skip header and separator rows
            if re.match(r'^[-:]+$', cells[0]) or re.match(r'^[-:]+$', cells[1] if len(cells) > 1 else ''):
                continue
            if re.match(r'^#', cells[0]) or cells[0] == '#':
                continue  # header row with '#' column
            # First cell is row number, second is source, third is how_it_fails
            if len(cells) >= 3 and re.match(r'^\d+[ab]?$', cells[0]):
                src = cells[1].strip('`').strip()
                how = cells[2].strip('`').strip()
                if src and src not in ('source',):
                    rows.append((src, how))
        elif in_table:
            break
    return rows

# ARCHITECTURE.md §2 table (has '# | source | how it fails | ...' columns)
arch_rows = extract_table_rows("ARCHITECTURE.md", "## 2. Failure modes")

# README section 3 table (has '# | source | how it fails | ...' columns)
readme_rows = extract_table_rows("README.md", "## What happens when a source breaks")

arch_pairs = set(arch_rows)
readme_pairs = set(readme_rows)

if arch_pairs != readme_pairs:
    missing = arch_pairs - readme_pairs
    extra = readme_pairs - arch_pairs
    if missing:
        print(f"  FAIL — (source, failure) pairs in ARCHITECTURE.md §2 but missing from README section 3: {missing}", file=sys.stderr)
    if extra:
        print(f"  FAIL — (source, failure) pairs in README section 3 but not in ARCHITECTURE.md §2: {extra}", file=sys.stderr)
    sys.exit(1)

if len(arch_rows) != len(readme_rows):
    print(f"  FAIL — row count mismatch: ARCHITECTURE.md §2 has {len(arch_rows)}, README section 3 has {len(readme_rows)}", file=sys.stderr)
    sys.exit(1)

print(f"  ok   — section-3 (source, failure) pairs match ARCHITECTURE.md §2 ({len(arch_rows)} rows)")
PY
echo "== 6. quickstart block — git clone, script line, exists and executable =="
python3 - <<'PY' || exit 1
import sys, re, os, stat

lines = open("README.md").read().splitlines()

# Find section 4
sec4_start = next((i for i, ln in enumerate(lines) if ln.rstrip() == "## 60-second quickstart"), None)
if sec4_start is None:
    print("  FAIL — '## 60-second quickstart' not found", file=sys.stderr)
    sys.exit(1)

# Find next ##
sec5_start = next((i for i in range(sec4_start+1, len(lines)) if re.match(r'^## ', lines[i])), len(lines))

# Find fenced bash block in section 4
block_lines = []
in_block = False
for ln in lines[sec4_start:sec5_start]:
    if ln.strip().startswith("```bash") or ln.strip().startswith("``` bash"):
        in_block = True
        continue
    if in_block and ln.strip() == "```":
        break
    if in_block:
        block_lines.append(ln.strip())

if not block_lines:
    print("  FAIL — no fenced bash block found in section 4", file=sys.stderr)
    sys.exit(1)

clone_lines = [ln for ln in block_lines if ln.startswith("git clone")]
script_lines = [ln for ln in block_lines if not ln.startswith("git clone") and ln.strip()]

if len(clone_lines) != 1:
    print(f"  FAIL — expected 1 git clone line, found {len(clone_lines)}", file=sys.stderr)
    sys.exit(1)

if len(script_lines) != 1:
    print(f"  FAIL — expected 1 non-clone command line, found {len(script_lines)}: {script_lines}", file=sys.stderr)
    sys.exit(1)

# Extract script path from the script line (e.g. "./scripts/quickstart.sh")
script_match = re.search(r'\./([^\s#]+)', script_lines[0])
if not script_match:
    print(f"  FAIL — cannot extract script path from: {script_lines[0]!r}", file=sys.stderr)
    sys.exit(1)

script_path = script_match.group(1)
if not os.path.exists(script_path):
    print(f"  FAIL — script does not exist: {script_path}", file=sys.stderr)
    sys.exit(1)

st = os.stat(script_path)
if not (st.st_mode & stat.S_IXUSR):
    print(f"  FAIL — script is not executable: {script_path}", file=sys.stderr)
    sys.exit(1)

# Check PRINTED_URL in quickstart.sh matches the URL mentioned in section 4
url_in_section4 = None
for ln in lines[sec4_start:sec5_start]:
    m = re.search(r'http://127\.0\.0\.1:\d+', ln)
    if m:
        url_in_section4 = m.group(0)
        break

if url_in_section4 is None:
    print("  FAIL — no http://127.0.0.1:PORT URL found in section 4", file=sys.stderr)
    sys.exit(1)

printed_url = None
for ln in open(script_path):
    m = re.match(r'^PRINTED_URL="([^"]+)"', ln.strip())
    if m:
        printed_url = m.group(1)
        break

if printed_url is None:
    print(f"  FAIL — PRINTED_URL not found in {script_path}", file=sys.stderr)
    sys.exit(1)

if url_in_section4 != printed_url:
    print(f"  FAIL — URL in section 4 ({url_in_section4!r}) != PRINTED_URL in {script_path} ({printed_url!r})", file=sys.stderr)
    sys.exit(1)

print(f"  ok   — git clone + script line; {script_path} exists, is executable, URL matches PRINTED_URL")
PY

# ── check 7: section 5 — agent_access_log, link to artefact, 'absent', no PII words ──
echo "== 7. section 5 — agent_access_log, absent, no PII column names =="
python3 - <<'PY' || exit 1
import sys, re

lines = open("README.md").read().splitlines()

sec5_start = next((i for i, ln in enumerate(lines)
                   if ln.rstrip() == "## The agent interface, and why it is safe"), None)
if sec5_start is None:
    print("  FAIL — section 5 heading not found", file=sys.stderr)
    sys.exit(1)

sec6_start = next((i for i in range(sec5_start+1, len(lines)) if re.match(r'^## ', lines[i])), len(lines))

sec5_text = "\n".join(lines[sec5_start:sec6_start])

checks = [
    ("agent_access_log", r'agent_access_log'),
    ("link to VDE-43 artefact", r'docs/2026-07-31-vde-43-agent-access-log\.md'),
    ("word 'absent'", r'\babsent\b'),
]
for label, pattern in checks:
    if not re.search(pattern, sec5_text):
        print(f"  FAIL — section 5 missing: {label}", file=sys.stderr)
        sys.exit(1)

pii_words = ["email", "phone", "full_name", "card"]
for word in pii_words:
    if re.search(r'\b' + re.escape(word) + r'\b', sec5_text, re.IGNORECASE):
        print(f"  FAIL — section 5 contains PII column name: {word!r}", file=sys.stderr)
        sys.exit(1)

print("  ok   — section 5 has agent_access_log, artefact link, 'absent', no PII column names")
PY

# ── check 8: section 6 ≥ 4 bullets; sections 1–6 ≤ 1300 words; no stale claims ─
echo "== 8. section 6 ≥ 4 bullets; sections 1–6 ≤ 1300 words; no stale unbuilt-claims =="
python3 - <<'PY' || exit 1
import sys, re
from pathlib import Path

lines = open("README.md").read().splitlines()

def find_section(heading, lines):
    return next((i for i, ln in enumerate(lines) if ln.rstrip() == heading), None)

sec1 = find_section("# cinema-ops-platform", lines)
sec6 = find_section("## What I deliberately did not build", lines)
fold = find_section("## Below the fold — the long form", lines)

if sec1 is None or sec6 is None or fold is None:
    print("  FAIL — could not locate all required headings", file=sys.stderr)
    sys.exit(1)

# Section 6 bullet count
sec6_end = next((i for i in range(sec6+1, len(lines)) if re.match(r'^## ', lines[i])), len(lines))
sec6_text = lines[sec6:sec6_end]
bullet_count = sum(1 for ln in sec6_text if re.match(r'^- ', ln))
if bullet_count < 4:
    print(f"  FAIL — section 6 has {bullet_count} bullet(s), need ≥ 4", file=sys.stderr)
    sys.exit(1)

# Staleness guard — same VDE-53/VDE-55 lesson made mechanical for README's own
# "deliberately did not build" section: a path that has shipped on disk paired
# with the stale phrase that would be a lie if it still appeared here.
sec6_joined = "\n".join(sec6_text)
shipped = [
    ("mcp/src/mcp.ts", r'MCP server\b.*not\b|MCP.*not (yet )?built'),
    ("dbt/models/gold/fct_booking.sql", r'gold dbt transforms.*not yet written|dbt transforms.*not yet'),
    ("dbt/models/silver/stg_bookings.sql", r'silver.*dbt transforms.*not yet written'),
    ("src/orchestration/checks.py", r'Dagster asset checks.*not (yet )?built'),
    ("evals/mcp.yaml", r'evaluation layer.*(does not|doesn.t) exist'),
    ("agent-api/", r'agent-api.*not (yet )?built'),
]

root = Path(".")
leaked = []
for path, stale_pattern in shipped:
    if (root / path).exists() and re.search(stale_pattern, sec6_joined, re.I):
        leaked.append((path, stale_pattern))

if leaked:
    for path, pattern in leaked:
        print(f"  FAIL — {path} exists on disk but README section 6 claims it "
              f"unbuilt (matched {pattern!r})", file=sys.stderr)
    sys.exit(1)

denylist_terms = ["MCP", "dbt", "asset check", "eval suite", "agent-api"]
for term in denylist_terms:
    pattern = re.escape(term) + r'[^.]{0,60}\bnot (yet )?built\b'
    if re.search(pattern, sec6_joined, re.I):
        print(f"  FAIL — README section 6 claims '{term}' is unbuilt, but it "
              f"has shipped", file=sys.stderr)
        sys.exit(1)

# The VDE-55 bug this check exists to catch didn't say "not built" at all — it
# named the VDE-48 fixture as the whole evaluation layer without acknowledging
# the MCP boundary eval that had since shipped alongside it. Catch that shape
# directly: a bullet naming "evaluation layer" + "VDE-48" that never mentions
# the MCP eval fixture is describing a narrower build than actually exists.
if (root / "evals/mcp.yaml").exists() or (root / "scripts/prove_mcp_eval.sh").exists():
    eval_bullet = re.search(r'evaluation layer[^\n]{0,300}VDE-48[^\n]{0,300}', sec6_joined, re.I)
    if eval_bullet and not re.search(
        r'evals/mcp\.yaml|prove_mcp_eval|MCP boundary eval|redteam\.yaml',
        eval_bullet.group(0), re.I,
    ):
        print("  FAIL — README section 6 names the VDE-48 fixture as the "
              "evaluation layer without acknowledging the shipped MCP eval "
              "(evals/mcp.yaml, scripts/prove_mcp_eval.sh)", file=sys.stderr)
        sys.exit(1)

# Word count of sections 1–6 (H1 through the line before ## Below the fold)
above_fold = lines[sec1:fold]
above_fold_text = "\n".join(above_fold)
word_count = len(above_fold_text.split())
if word_count > 1300:
    print(f"  FAIL — sections 1–6 are {word_count} words, limit is 1300", file=sys.stderr)
    sys.exit(1)

print(f"  ok   — section 6 has {bullet_count} bullets, no stale unbuilt-claims; "
      f"sections 1–6 are {word_count} words (≤ 1300)")
PY

echo ""
echo "== bash -n scripts/quickstart.sh =="
bash -n scripts/quickstart.sh && echo "  ok   — bash -n scripts/quickstart.sh"

echo ""
echo "== ./scripts/quickstart.sh --check =="
./scripts/quickstart.sh --check

# ── check 9: below-fold sentinel phrases still present ────────────────────────
echo ""
echo "== 9. below-fold sentinel phrases still appear =="
python3 - <<'PY' || exit 1
import sys, re

text = open("README.md").read()

# Find the below-fold marker
fold_marker = "## Below the fold — the long form"
fold_idx = text.find(fold_marker)
if fold_idx == -1:
    print(f"  FAIL — fold marker not found: {fold_marker!r}", file=sys.stderr)
    sys.exit(1)

below_fold = text[fold_idx:]

sentinels = [
    ("illegible", "illegible"),
    ("essay is downstream", "essay is downstream"),
    ("all-predicted", "all-predicted"),
    ("Trustworthy data layer", "Trustworthy data layer"),
]

failed = False
for label, phrase in sentinels:
    if phrase not in below_fold:
        print(f"  FAIL — sentinel phrase missing from below-fold: {label!r}", file=sys.stderr)
        failed = True

if failed:
    sys.exit(1)

print(f"  ok   — all {len(sentinels)} sentinel phrases present below the fold")
PY

echo ""
echo "PASS=9"
