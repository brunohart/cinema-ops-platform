# VDE-56 — README: what breaks at circuit scale, and what I deliberately did not build

**Date:** 2026-08-02
**Issue:** VDE-56
**Branch:** `cursor/vde-56-vista-scale-limits-6263`
**Model:** claude-sonnet-5 (implement phase)
**Tool:** Cursor Cloud · bash · python3

## What landed

README section 6 became two sub-sections instead of one flat bullet list:

1. `### At circuit scale, these break first` — four bullets, each carrying a specific number
   (`fct_booking` past ~50M rows, four sources to hundreds of sites, `ops.watermarks`'
   `(site_id, source)` key, one Slack webhook muted by week two), stated as mine and specific
   enough to be wrong.
2. `### Deliberately not built` — six omissions (real CDC, backfill orchestration UI,
   multi-tenancy, a red team on every change, no real operator data, the red bronze-immutability
   guard), each paired with a one-sentence `*First week:*` first move. An item with no first-week
   move answerable was cut rather than listed.

Three stale "not built" claims were removed because the thing now exists: "the MCP server itself"
(`mcp/src/tools.ts`), "models not yet written" (`dbt/models/gold/fct_booking.sql`), and "asset
checks / SLAs" (`src/orchestration/checks.py`). The mcp-eval gap was corrected from "no workflow"
to "runs only on `mcp/**`/`evals/**` changes" — `mcp-eval.yml` already exists and runs on PRs.

`scripts/prove_readme_structure.sh` gained check 10: it asserts the two sub-headings exist once
each and in order, that the scale sub-section has ≥ 4 bullets each carrying a digit, that the
"deliberately not built" sub-section has ≥ 4 bullets each with exactly one `*First week:*`
sentence, and — the freshness tripwire — that a "not built" claim about the MCP server, gold
models, asset checks, or the synopsis-injection workflow fails the proof the moment the
corresponding file or workflow condition exists. Checks 1 and 8's `find_section` anchor were
updated to the renamed heading. `PASS=9` became `PASS=10`.

## Decisions taken

### The freshness tripwires are structural, not a one-time cleanup

The plan's point in cutting the three stale claims was not just accuracy today — it was that the
check itself now fails automatically if a future PR reintroduces a "not built" claim about
something that has since been built. Check 10 greps `.github/workflows/*` in addition to `src/`,
because the mcp-eval gap in the previous text ("no workflow") was inaccurate even before this
change — the ledger's note on VDE-56's own plan flagged this before implementation began.

### Word budget held at 1228, no cuts needed

Sections 1–6 came in at 1228 words, under the plan's 1250-word trigger for the cut list, so none
of the three named trims (dropping `, a per-site run log`, `, and the VDE-11 guard caught what it
was written to catch`, or `, not a bigger instance`) were applied. All three phrases remain in the
delivered text verbatim, as specified.

### `docs/thesis-map.md` and ADR-006 anchor both resolve

The scale-section prose links to `docs/thesis-map.md` (exists) and
`DECISIONS.md#adr-006--watermark-plus-overlap-window-not-cdc` (ADR-006 is titled "Watermark plus
overlap window, not CDC" in `DECISIONS.md`) — both verified before commit so check 4 (every local
link resolves) would not silently fail.

## Proof — verbatim captured output

```
$ ./scripts/prove_readme_structure.sh
== 1. seven section anchors exist once each, in order ==
  ok   — all seven anchors present once each, in order
== 2. opening paragraph: one sentence-ending period, ≤ 45 words ==
  ok   — one paragraph, one period, 45 words (≤ 45)
== 3. badge ordering — shields.io after slot-2 image, no <img before H1 ==
  ok   — no shields.io before slot-2 image, no <img before H1
== 4. every local link and image target resolves on disk ==
  ok   — all 48 local targets resolve
== 5. section-3 failure-mode table matches ARCHITECTURE.md §2 sources ==
  ok   — section-3 (source, failure) pairs match ARCHITECTURE.md §2 (5 rows)
== 6. quickstart block — git clone, script line, exists and executable ==
  ok   — git clone + script line; scripts/quickstart.sh exists, is executable, URL matches PRINTED_URL
== 7. section 5 — agent_access_log, absent, no PII column names ==
  ok   — section 5 has agent_access_log, artefact link, 'absent', no PII column names
== 8. section 6 ≥ 4 bullets; sections 1–6 ≤ 1300 words ==
  ok   — section 6 has 10 bullets; sections 1–6 are 1228 words (≤ 1300)

== bash -n scripts/quickstart.sh ==
  ok   — bash -n scripts/quickstart.sh

== ./scripts/quickstart.sh --check ==
quickstart: check ok — http://127.0.0.1:3000

== 9. below-fold sentinel phrases still appear ==
  ok   — all 4 sentinel phrases present below the fold

== 10. section 6 — scale bullets carry numbers; every omission has a one-sentence first-week move ==
  ok   — 4 scale bullets with numbers; 6 omissions, each with a one-sentence first-week move

PASS=10
```

Exit code: 0.

## Trail

issue **VDE-56** → branch `cursor/vde-56-vista-scale-limits-6263` → this artefact
Commits: `VDE-56: README section 6 — circuit-scale limits and first-week moves; check 10` ·
`VDE-56: artefact docs/2026-08-02-vde-56-scale-limits.md; Prove-it row` ·
`VDE-56: ARCHITECTURE.md §10 decision-log row`
