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
  not been shown the four claims. The four-minute budget survives: the new section adds 166 words to
  a 1014-word above-fold total, landing at 1187 — under the 1300-word check-8 ceiling and under the
  1250 target the plan set aside for later issues.
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

```
(pending — captured in the final commit of this issue)
```
