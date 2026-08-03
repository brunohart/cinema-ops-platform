# Pull-request archive

A snapshot of this repository's pull-request trail, written into the tree so it
survives independently of the host. `issue → branch → commit → proof → PR` keeps
four of its five links in git; this file is the fifth.

**Every timestamp below is the original, as recorded by GitHub.** Nothing here is
reconstructed. This is a record of pull requests that existed, not a mechanism for
recreating them — a restored PR would carry today's date and fabricated checks, and
on a repository that argues the trail is never rewritten, a manufactured trail is
worse than an absent one.

- Pull requests archived: **54**
- Merged: **52**
- Ran CI: **13** (CI landed at VDE-50; earlier PRs predate it)
- Of those, fully green: **1**
- Span: **2026-07-31 → 2026-08-02**
- Regenerate: `python3 scripts/export_pr_archive.py` · verify: `--check`

**Deliberately excluded**

- `#53` — working notes, not platform work

Recorded rather than silently omitted: a gap you can see is evidence, a gap you
cannot is a hole.

| # | title | state | merged | checks | commits | merge commit |
|---|-------|-------|--------|--------|---------|--------------|
| 1 | VDE-9: BaseExtractor with retry, quarantine, and watermark-last | MERGED | 2026-07-31 | — | 2 | `a0b19a6` |
| 2 | VDE-10: Every bronze row carries stamp audit columns | MERGED | 2026-07-31 | — | 5 | `28205fe` |
| 3 | VDE-11: Raw payloads are immutable — INSERT-only bronze | MERGED | 2026-07-31 | — | 1 | `540cedc` |
| 4 | VDE-12: TMDB extractor — pagination, 429 Retry-After, incremental date filter | MERGED | 2026-07-31 | — | 6 | `ad1a496` |
| 5 | VDE-15: Prove a re-run produces zero duplicates | MERGED | 2026-07-31 | — | 2 | `b4a1f2b` |
| 6 | VDE-14: Quarantine bad rows instead of failing the whole batch | MERGED | 2026-07-31 | — | 2 | `0798dbe` |
| 7 | VDE-13: File extractor with Pydantic schema-drift quarantine | MERGED | 2026-07-31 | — | 3 | `4601e6c` |
| 8 | VDE-17: Handle cinema_ops clock-skew with SAFETY_LAG overlap | MERGED | 2026-07-31 | — | 3 | `53283e8` |
| 9 | VDE-20: Consumer-group offset handling — commit after processing | MERGED | 2026-07-31 | — | 1 | `b023008` |
| 10 | VDE-16: Incremental cinema_ops pull with transactional meta.watermarks | MERGED | 2026-07-31 | — | 2 | `87c901a` |
| 11 | VDE-18: Redpanda consumer for synthetic ticketing events | MERGED | 2026-07-31 | — | 3 | `0b15f11` |
| 12 | VDE-21: Kill the consumer mid-stream — prove effectively-once | MERGED | 2026-07-31 | — | 3 | `cb53b07` |
| 13 | docs: README — the read path, the four shapes, and the proofs | MERGED | 2026-07-31 | — | 4 | `fdb5877` |
| 14 | VDE-19: Dead-letter queue for unparseable ticketing messages | MERGED | 2026-07-31 | — | 2 | `007a0e8` |
| 15 | VDE-24: silver dbt models — typed, renamed, deduped from bronze | MERGED | 2026-07-31 | — | 2 | `b9db27a` |
| 16 | VDE-27: SCD Type 2 film_snapshot via dbt | MERGED | 2026-07-31 | — | 2 | `29835be` |
| 17 | VDE-26: state the grain of every fact table before modelling | MERGED | 2026-07-31 | — | 2 | `9e2da79` |
| 18 | VDE-22: Wrap four extractors as Dagster assets with declared dependencies | MERGED | 2026-07-31 | — | 2 | `fcd79fe` |
| 19 | VDE-25: gold star schema — dim_film, dim_site, dim_date, fct_session, fct_booking | MERGED | 2026-07-31 | — | 1 | `5265f69` |
| 20 | VDE-23: Screenshot the lineage graph for the case study | MERGED | 2026-07-31 | — | 1 | `31e055d` |
| 21 | Cursor/vde 24 silver models 948d | MERGED | 2026-07-31 | — | 3 | `ed91018` |
| 22 | VDE-32: singular business-rule — no booking without a session | MERGED | 2026-07-31 | — | 3 | `fe29e4c` |
| 23 | VDE-30: dbt schema tests — unique, not_null, relationships, accepted_values | MERGED | 2026-07-31 | — | 1 | `5f20c0c` |
| 24 | VDE-37: RUNBOOK.md — three likely failures, symptom first | MERGED | 2026-07-31 | — | 1 | `763cb3c` |
| 25 | VDE-36: append-only meta.pipeline_runs — what ran, duration, outcome | MERGED | 2026-07-31 | — | 2 | `b6e8911` |
| 26 | VDE-33: Freshness policies on every source asset | MERGED | 2026-07-31 | — | 1 | `f0090b9` |
| 27 | VDE-34: structlog JSON logging with batch_id threaded through every stage | MERGED | 2026-07-31 | — | 4 | `f8a72f6` |
| 28 | VDE-28: pytest unit tests on transforms | MERGED | 2026-07-31 | — | 2 | `526173d` |
| 29 | VDE-35: One Slack webhook alert path on check failure / freshness breach | MERGED | 2026-07-31 | — | 2 | `ce12670` |
| 30 | VDE-31: Dagster asset checks on gold (row-count Δ, null-rate, RI) | MERGED | 2026-08-01 | — | 5 | `580a579` |
| 31 | VDE-29: Integration test — full DAG against throwaway Postgres | MERGED | 2026-08-01 | — | 3 | `3dce711` |
| 32 | VDE-39: Fixed set of parameterised, allowlisted queries | MERGED | 2026-07-31 | — | 1 | `e965882` |
| 33 | VDE-42: PII absent from agent interface, not redacted from storage | MERGED | 2026-08-01 | — | 2 | `6483821` |
| 34 | VDE-38: Hono agent-api over gold — no SQL passthrough | MERGED | 2026-08-01 | — | 4 | `6c5508f` |
| 35 | VDE-41: Scoped tokens — bound to sites and tools | MERGED | 2026-08-01 | — | 5 | `2c5fddc` |
| 36 | VDE-43: agent_access_log — who, what tool, what params, what row count, when | MERGED | 2026-08-01 | — | 2 | `de54f83` |
| 37 | VDE-44: Hard row limits and query timeouts on agent tools | MERGED | 2026-08-01 | — | 2 | `789a385` |
| 38 | VDE-48: Red-team the synopsis injection path — prove it fails closed | MERGED | 2026-08-01 | — | 2 | `16b5d78` |
| 39 | VDE-45: refusal path — decline rather than guess when scope is exceeded | MERGED | 2026-08-01 | — | 4 | `487ae9c` |
| 40 | VDE-40: MCP server — get_site_performance, get_film_attendance, list_sessions | MERGED | 2026-08-01 | — | 4 | `5f233aa` |
| 41 | VDE-47: Eval suite over the MCP server — contract, scope refusal, PII absence | MERGED | 2026-08-01 | 1 green | 3 | `d56179f` |
| 42 | pipeline: every issue plans on Opus, implements on Sonnet, verifies on Opus — and writes back what it learned | MERGED | 2026-08-01 | — | 21 | `4ce8d75` |
| 43 | VDE-53: README four-minute first read — screenshot, failure modes, quickstart | MERGED | 2026-08-01 | 3 green / 1 not | 14 | `3f24dc1` |
| 44 | VDE-50: GitHub Actions CI — lint, typecheck, unit + integration, dbt build | MERGED | 2026-08-01 | 1 green / 1 not | 15 | `f491321` |
| 45 | VDE-52: Three least-privilege DB roles (extractor / transformer / api) | MERGED | 2026-08-01 | 3 green / 1 not | 15 | `899824d` |
| 46 | VDE-51: Secrets out of the repo | MERGED | 2026-08-01 | 3 green / 1 not | 30 | `3ca8c01` |
| 47 | VDE-54: Public demo deploy surface with scoped demo token | MERGED | 2026-08-01 | 3 green / 1 not | 20 | `df9e4bd` |
| 48 | VDE-49: docker compose up brings up the entire platform, seeded | MERGED | 2026-08-01 | 3 green / 1 not | 20 | `83b90b3` |
| 49 | VDE-58: AI-first practice section — spec before code, proven from git history | MERGED | 2026-08-02 | 3 green / 1 not | 14 | `7d9c3c4` |
| 50 | VDE-56: name circuit-scale limits and first-week moves for every omission | MERGED | 2026-08-02 | 3 green / 1 not | 7 | `4f08518` |
| 51 | VDE-59: Where I rejected the AI's output, and why | OPEN | — | 3 green / 1 not | 6 | `—` |
| 52 | VDE-46: Claude Desktop MCP config + audited operator question | OPEN | — | 3 green / 1 not | 47 | `—` |
| 54 | VDE-57: 3-minute Loom demo shot list (rehearsable, machine-checked) | MERGED | 2026-08-02 | 3 green / 1 not | 8 | `a82b2f3` |
| 55 | VDE-55: Case study — problem, four failure modes, governance model | MERGED | 2026-08-02 | 3 green / 1 not | 11 | `fb4723c` |

Numbers are plain text, not links: this archive exists to outlive the host, and a
link to a pull request that may not exist is worse than none. Every merge commit
above is in this repository's history — `git show <oid>` resolves offline.

Full structured data, including every commit oid and check conclusion:
[`pull-requests.json`](pull-requests.json).
