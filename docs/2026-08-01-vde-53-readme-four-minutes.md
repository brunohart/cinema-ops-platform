# VDE-53 — README: four-minute first read

**Date:** 2026-08-01  
**Issue:** VDE-53  
**Branch:** `cursor/vde-53-readme-architecture-quickstart-8cf3`  
**Model:** claude-sonnet-4-5 (implement phase)  
**Tool:** Cursor Cloud · bash · python3

## What landed

Six sections above a single fold marker, in this order:

1. `# cinema-ops-platform` — one sentence (45 words, one period)
2. `## What it looks like` — caption + screenshot (`docs/assets/2026-07-31-vde-23-lineage-graph.png`) + artefact link
3. `## What happens when a source breaks` — five-row failure-mode table restating `ARCHITECTURE.md` §2 in full (rows 1, 2, 3, 4, 4b); source of truth link; row-2 caveat
4. `## 60-second quickstart` — two-command bash block; URL; proof-script alternative
5. `## The agent interface, and why it is safe` — triple-lock structural argument; verbatim `agent_access_log` aggregation; refusal-logging rationale
6. `## What I deliberately did not build` — six bullets, each naming the thing and the reason

Everything existing that was not one of the six survives below `## Below the fold — the long form`, wrapped in `<details>` blocks.

## Four decisions taken (and the reasoning behind each)

### 1. Screenshot in slot 2, not the mermaid diagram

`docs/assets/2026-07-31-vde-23-lineage-graph.png` exists and renders: ten Dagster assets (`raw_tmdb`, `raw_landing_files`, `raw_cinema_ops`, `raw_ticketing` → four `stg_*` → `dim_film`, `fct_ticket_sale`), all green *Materialized Jul 31, 7:29 PM*. The mermaid diagram is an illustration; the screenshot is evidence. The issue asked for the screenshot.

**Glob near-miss recorded:** `Glob('**/*.png')` returns zero results in this workspace because binary files are excluded from the glob index. The planner confirmed the PNG exists via `ls docs/assets/` and `Read`. Check 4 of `prove_readme_structure.sh` now enforces that every local image target resolves on disk, so a deleted or renamed asset fails the proof loudly.

### 2. Badges moved below the fold, not deleted

The six `img.shields.io` badges moved intact to the start of the below-fold section, immediately after the banner SVG. Check 3 enforces that no `img.shields.io` occurrence appears before the slot-2 lineage image. No badge markup was altered.

### 3. `scripts/quickstart.sh` created because no one-command entry point existed

The repository had no Makefile and no single entry point that brought up Postgres and launched Dagster in one step. Writing "one command" without one would be exactly the assurance this repo refuses. The script has:
- `--check` mode (bash + python3 only, no Docker) that asserts required files exist and `workspace.yaml` names `orchestration.definitions`
- default mode that runs `docker compose up -d db`, polls for readiness, creates `.venv` if absent, installs `.[dev,dbt]`, and `exec dagster dev`
- `PRINTED_URL="http://127.0.0.1:3000"` defined exactly once; check 6 reads this variable by name to verify the URL in section 4 matches

### 4. Essay and argument demoted below the fold

The "Two paths out of a platform" mermaid, "An agent is a consumer with no judgement" prose, "The shape of the thing" diagram, and all supporting tables moved into `<details>` blocks below the fold. **Note (post-verify correction):** four fragments from the base README were silently dropped during the restructure — the epigraph blockquote, the essay-dependency paragraph, the all-predicted `[!NOTE]`, and the "Trustworthy data layer" sentence — and were restored after a verifier fail finding. The original artefact line 43 incorrectly claimed "No prose was deleted; none was reworded." The decision log (`ARCHITECTURE.md` §10) records this as a structural choice: a reviewer who never reaches the proof table has not been persuaded of anything.

## Proof — verbatim captured output (updated after verify-fail fix)

```
$ ./scripts/prove_readme_structure.sh && ./scripts/quickstart.sh --check
== 1. seven section anchors exist once each, in order ==
  ok   — all seven anchors present once each, in order
== 2. opening paragraph: one sentence-ending period, ≤ 45 words ==
  ok   — one paragraph, one period, 45 words (≤ 45)
== 3. badge ordering — shields.io after slot-2 image, no <img before H1 ==
  ok   — no shields.io before slot-2 image, no <img before H1
== 4. every local link and image target resolves on disk ==
  ok   — all 38 local targets resolve
== 5. section-3 failure-mode table matches ARCHITECTURE.md §2 sources ==
  ok   — section-3 (source, failure) pairs match ARCHITECTURE.md §2 (5 rows)
== 6. quickstart block — git clone, script line, exists and executable ==
  ok   — git clone + script line; scripts/quickstart.sh exists, is executable, URL matches PRINTED_URL
== 7. section 5 — agent_access_log, absent, no PII column names ==
  ok   — section 5 has agent_access_log, artefact link, 'absent', no PII column names
== 8. section 6 ≥ 4 bullets; sections 1–6 ≤ 1300 words ==
  ok   — section 6 has 7 bullets; sections 1–6 are 1014 words (≤ 1300)

== bash -n scripts/quickstart.sh ==
  ok   — bash -n scripts/quickstart.sh

== ./scripts/quickstart.sh --check ==
quickstart: check ok — http://127.0.0.1:3000

== 9. below-fold sentinel phrases still appear ==
  ok   — all 4 sentinel phrases present below the fold

PASS=9
quickstart: check ok — http://127.0.0.1:3000
```

Exit code: 0.

## What has NOT been run (honest scope)

The full docker quickstart has **not** been run. No Docker daemon is available in this Cloud Agent environment. The three reviewer questions the issue posed, and which section answers each:

| question | answers in | status |
|---|---|---|
| *What does it do?* | section 2 (screenshot) + section 3 (failure modes) | PREDICTED — not witnessed by a human reviewer |
| *What happens when a source breaks?* | section 3 — five-row failure-mode table | PREDICTED — table restates §2 reasoning; no source has broken in front of a reviewer yet |
| *Why is the agent part safe?* | section 5 — triple-lock argument + verbatim access-log output | PREDICTED — structural argument is sound; adversarial testing (VDE-48 fixture) is the evidence referenced in section 6 |

`PREDICTED` is this repository's own vocabulary: reasoned but not yet witnessed. The docker path is labelled "needs Docker and Python 3.11+" in the README and is not part of the green-on-clean-clone claim.

## Trail

issue **VDE-53** → branch `cursor/vde-53-readme-architecture-quickstart-8cf3` → this artefact  
Commits: `VDE-53: add scripts/quickstart.sh with --check mode` · `VDE-53: restructure README — six sections above fold, essay below` · `VDE-53: add scripts/prove_readme_structure.sh; fix README paragraph to ≤ 45 words` · `VDE-53: append §10 decision-log row — README four-minute first read` · `VDE-53: artefact docs/2026-08-01-vde-53-readme-four-minutes.md`
