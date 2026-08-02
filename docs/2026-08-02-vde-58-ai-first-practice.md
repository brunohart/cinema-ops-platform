# VDE-58 — AI-first section: how the practice is proven, not asserted

**Date:** 2026-08-02  
**Issue:** VDE-58  
**Branch:** `cursor/vde-58-ai-first-section-fa90`  
**Model:** claude-sonnet-5 (implement phase)  
**Tool:** Cursor Cloud · bash · python3 · git

## What landed

- `scripts/prove_ai_practice.sh` — six checks, stdlib + git only, refuses a shallow clone (exit 2)
  before reading the root commit.
- A new above-fold README section, `## How this was built with AI`, between
  `## What I deliberately did not build` and `## Below the fold — the long form`.
- One Prove-it row inside the existing `<details><summary>Prove it</summary>` block, and one
  sentence inside the existing `<details><summary>How the work gets done — plan, implement,
  verify</summary>` block.
- A minimal extension to `scripts/prove_readme_structure.sh`: check 1's anchor list now has eight
  entries (the new heading inserted in the correct place) and check 8's wording moved from
  "sections 1–6" to "above-fold" — the 1300-word cap and its measurement (H1 through the fold
  marker) are unchanged, and no other check's semantics changed.
- `ARCHITECTURE.md` §10 — one dated row for this decision.
- This artefact.

## The four claims, each named against the check that gates it

1. **Spec before prompting.** Check 1 asserts commit one (`4f05bb5`, 2026-07-30 author date) touches
   only `ARCHITECTURE.md`, `DECISIONS.md`, `.mcp.json`, `.gitignore`, and contains both
   `ARCHITECTURE.md` and `DECISIONS.md`; check 2 asserts it is a strict, dated ancestor of the first
   commit under `src/`, `dbt/` or `sql/` (`8f2aa34`, 2026-07-31 — "VDE-9: add BaseExtractor with
   retry, quarantine, watermark-last").
2. **Tests read the implementation before they were written.** Check 3 pairs every
   `tests/**/test_<X>.py` against `src/**/<X>.py` where the basename match is unique (7 pairs:
   `base`, `tmdb`, `events`, `silver`, `gold`, `common`, `limits`), and asserts the test's adding
   commit is never a strict ancestor-predecessor of the implementation's adding commit. All 7 pass;
   2 (`base`, `tmdb`) landed in a strictly later commit than the code they test, the other 5 landed
   in the same commit.
3. **Plan precedes implement, every recorded session.** Check 4 parses
   `docs/agent-ledger/ledger.jsonl` and asserts the first `plan` line index is lower than the first
   `implement` line index for every session holding both — 7 sessions checked, 0 violations, 0
   orphan `implement`-with-no-`plan` sessions to name. It then requires
   `python3 scripts/agent_ledger.py validate` to exit 0, so the ordering claim rests on an
   unrewritten hash chain.
4. **Gates the model could not talk past.** Check 5 asserts `.github/workflows/ci.yml` contains
   `ruff check`, `mypy src`, `pytest`, `dbt build` and `scripts/check_dbt_results.py`, and that
   `.cursor/hooks.json` registers a `stop` hook running `pipeline_hook.py`.

Check 6 asserts the README section itself: exists exactly once, in the correct position, ≤ 220
words, mentions `ARCHITECTURE.md`, `DECISIONS.md`, `docs/agent-ledger/`, `ruff`, `mypy`, `pytest`,
`dbt`, and links this artefact, which exists on disk.

## Decisions taken

- **No new ADR.** ADR-013 already settles *how* work is delivered (three models, ledger between
  them). VDE-58 exhibits and proves that decision; it does not take a new one-way door. This also
  avoids the ADR-number race the ledger has already recorded twice this week (main is at ADR-016).
- **Above the fold, not a `<details>` block.** A reviewer who never opens a collapsed section has
  not been shown the four claims. The four-minute budget survives: the section is 170 words after
  two review-loop wording fixes (the word count moved 166 → 170; see "Trail" below for the fix
  commits), landing the above-fold total at 1191 — under the 1300-word check-8 ceiling and under
  the 1250 target the plan set aside for later issues.
- **`prove_readme_structure.sh` check 1 and check 8 updated, minimally.** Placing the new section
  above the fold changes the anchor set from seven to eight; check 1's anchor list and check 8's
  wording ("sections 1–6" → "above-fold") were updated to match. No other check's semantics changed,
  and check 8's 1300-word ceiling and H1-to-fold-marker measurement are unchanged — this is the
  necessary consequence of the above-fold placement, not a redesign of the VDE-53 checks.
- **Shallow-clone guard exits 2, not 1.** "Cannot prove" (no root-commit history available) is not
  the same claim as "disproved" (the history exists and violates the property). Exit 2 matches the
  convention already established in `scripts/deploy_fly.sh` for missing prerequisites.
- **README build-log row: none added.** The PR number is not known while this commit is being
  written; VDE-53 set the precedent of leaving no row rather than inventing one.

## Honest scope

These checks prove ordering and the existence of gates. They do **not** prove that a human read
every diff, or that the plan/implement/verify roles were followed in spirit rather than only in the
ledger's bookkeeping — that stays `PREDICTED` in this repository's vocabulary, the same as every
other claim here that is reasoned but not independently witnessed.

Check 4's orphan-session count was 0 in this run; if a future run of this script reports a non-zero
count, that session must be named here rather than silently absorbed into "7 sessions checked."

## Proof — verbatim captured output

Re-captured after the third fix loop (the check-1 banner wording, and the two prose corrections
below). The ledger's two counts inside the output — `entries` and `session(s) checked` — are as of
this capture only: every subsequent `agent_ledger.py append` (including this issue's own `note`
entries recording each fix loop) advances both, so a later re-run of `./scripts/prove_ai_practice.sh`
will not reproduce these exact two numbers, and that is expected — the check re-derives them from
the ledger as it stands at run time rather than asserting a fixed count.

```
$ ./scripts/prove_ai_practice.sh && ./scripts/prove_readme_structure.sh
== 1. commit one carries no code (spec + toolchain config) ==
  ok   — commit one (4f05bb5, 2026-07-30) is exactly ['.gitignore', '.mcp.json', 'ARCHITECTURE.md', 'DECISIONS.md']
== 2. the spec precedes the pipeline (commit one predates the first src/dbt/sql commit) ==
  ok   — commit one (4f05bb5, 2026-07-30 20:56:06 +1200) precedes first pipeline commit (8f2aa34, 2026-07-31 00:08:20 +0000) — 'VDE-9: add BaseExtractor with retry, quarantine, watermark-last'
== 3. no test predates the implementation it tests (unique basename pairing) ==
  note — unpaired, not gated: tests/agents/test_agent_ledger.py
  note — unpaired, not gated: tests/bronze/test_immutability.py
  note — unpaired, not gated: tests/extractors/test_cinema_ops_lag.py
  note — unpaired, not gated: tests/extractors/test_stamp.py
  note — unpaired, not gated: tests/integration/test_medallion_dag.py
  note — unpaired, not gated: tests/orchestration/test_slack_alerts.py
  note — unpaired, not gated: tests/test_idempotency.py
  ok   — pairs=7 gated=7; 2 landed in a strictly later commit than the implementation they test
== 4. the ledger shows plan before implement, in every recorded session ==
  ok   — 8 session(s) checked; plan precedes implement in every one
ledger ok: 81 entries, hash chains intact — /workspace/docs/agent-ledger/ledger.jsonl
  ok   — ledger chain validates (python3 scripts/agent_ledger.py validate)
== 5. CI workflow and pipeline hook contain the gates the model could not talk past ==
  ok   — ci.yml contains ['ruff check', 'mypy src', 'pytest', 'dbt build', 'scripts/check_dbt_results.py']; hooks.json registers a stop hook running pipeline_hook.py
== 6. README section '## How this was built with AI' exists and says the four things ==
  ok   — section present once, in order, 170 words (≤ 220), mentions all required names, links docs/2026-08-02-vde-58-ai-first-practice.md which exists on disk

== evidence: git log --oneline --reverse | head -20 ==
4f05bb5 Commit one: architecture, decisions, and MCP toolchain config
bb4aca1 Add CLAUDE.md — the rules every agent session inherits
1972b30 Add scripts/seed-linear.mjs — generate the Linear backlog from the spec
8f2aa34 VDE-9: add BaseExtractor with retry, quarantine, watermark-last
9f1e096 Ignore Python bytecode and remove accidentally committed caches
13bcfeb VDE-11: enforce bronze immutability via grants and grep
b4619e4 VDE-12: add TMDBExtractor.fetch with pagination and Retry-After
43abfd6 VDE-12: mock HTTP tests for pagination and 429 Retry-After
d54ca9a VDE-15: prove re-run idempotency against throwaway Postgres
6cc20f3 VDE-14: quarantine bad rows into bronze.quarantine
ef54b70 VDE-13: file extractor with Pydantic schema-drift quarantine
7157051 VDE-13: drop unused dumps_payload helper
a0b19a6 VDE-9: BaseExtractor with retry, quarantine, and watermark-last (#1)
bca1061 VDE-9: add BaseExtractor with retry, quarantine, watermark-last
7d58ff2 Ignore Python bytecode and remove accidentally committed caches
4a177f0 VDE-10: expose BaseExtractor.stamp() for bronze audit columns
28205fe VDE-10: add stamp proof tests (unstamped=0, hash stability)
540cedc Merge pull request #3 from brunohart/cursor/vde-11-bronze-immutable-a4e2
8a011eb Merge origin/main into VDE-12 TMDB extractor branch
f776c71 VDE-12: finish merge resolution for extractors __init__

PASS=6
== 1. eight section anchors exist once each, in order ==
  ok   — all eight anchors present once each, in order
== 2. opening paragraph: one sentence-ending period, ≤ 45 words ==
  ok   — one paragraph, one period, 45 words (≤ 45)
== 3. badge ordering — shields.io after slot-2 image, no <img before H1 ==
  ok   — no shields.io before slot-2 image, no <img before H1
== 4. every local link and image target resolves on disk ==
  ok   — all 51 local targets resolve
== 5. section-3 failure-mode table matches ARCHITECTURE.md §2 sources ==
  ok   — section-3 (source, failure) pairs match ARCHITECTURE.md §2 (5 rows)
== 6. quickstart block — git clone, script line, exists and executable ==
  ok   — git clone + script line; scripts/quickstart.sh exists, is executable, URL matches PRINTED_URL
== 7. section 5 — agent_access_log, absent, no PII column names ==
  ok   — section 5 has agent_access_log, artefact link, 'absent', no PII column names
== 8. section 6 ≥ 4 bullets; above-fold ≤ 1300 words ==
  ok   — section 6 has 7 bullets; above-fold is 1191 words (≤ 1300)

== bash -n scripts/quickstart.sh ==
  ok   — bash -n scripts/quickstart.sh

== ./scripts/quickstart.sh --check ==
quickstart: check ok — http://127.0.0.1:3000

== 9. below-fold sentinel phrases still appear ==
  ok   — all 4 sentinel phrases present below the fold

PASS=9
```

Exit code: 0.

## Trail

issue **VDE-58** → branch `cursor/vde-58-ai-first-section-fa90` → this artefact  
Commits: `VDE-58: add scripts/prove_ai_practice.sh — six checks against git history, ledger and CI` ·
`VDE-58: README above-fold AI-practice section + artefact link + prove_readme_structure.sh anchor
update` · `VDE-58: ARCHITECTURE.md §10 — decision-log row for the AI-first practice section` ·
`VDE-58: capture proof output in the artefact` · `VDE-58: verifier fixes — Prove-it row wording
matches check 1's actual allowlist; artefact notes ledger counts advance on re-run` ·
`VDE-58: README section body — fix remaining overclaim about commit one's contents` ·
`VDE-58: prove_ai_practice.sh check 1 banner wording + re-captured proof`
