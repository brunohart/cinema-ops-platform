# VDE-51 — Secrets out of the repo

**Date:** 2026-08-01
**Issue:** VDE-51
**Branch:** `cursor/vde-51-secrets-out-c800`
**Model 08** — Backfill is the real test of an architecture

## Why

The repository was public and the history contained commented-out credential-shaped lines in
`.env.example` (a Slack webhook placeholder, ADR-010 local-dev DSNs). The existing `.env.example`
also had most keys commented out, so anyone who copied it to `.env` would miss them. These were not
secrets — no third-party credential was ever committed — but a grep-based proof was impossible to
read cleanly, and an incomplete `.env.example` is a silent footgun.

Done means: one command proves no third-party credential shape has ever existed in history or the
working tree; `.env.example` lists every key the code reads with every value blank; and the
enforcement runs in CI.

## What landed

| path | role |
|------|------|
| `scripts/scan_secrets.py` | stdlib-only classifier — Tier A (provider-shaped) and Tier B (secret-named) over full git history and working tree; exits 0/1/2; also checks `.env.example` completeness; `--self-check` runs synthetic kill-test |
| `scripts/prove_no_secrets.sh` | proof script — step 0: synthetic kill-test; steps 1–6: git sanity, issue-shaped grep (reported, not gated), classifier, `.env` never committed, `.gitignore` coverage, `.env.example` sign-off |
| `.env.example` | rewritten — every key present, every value blank; no credential-bearing URL anywhere in the file |
| `.github/workflows/secret-scan.yml` | first CI workflow; runs `prove_no_secrets.sh` on push and pull\_request with `fetch-depth: 0` |
| `docs/2026-08-01-vde-51-secrets-out.md` | this artefact |
| `DECISIONS.md` | ADR-014 appended |
| `ARCHITECTURE.md` | §10 row appended |
| `README.md` | two rows appended (Prove it table + build-log table) |
| `docs/agent-ledger/ledger.jsonl` | plan, implement, verify, verify-fail, implement (fix-pass), verify-fail-2, implement (prose-fix) entries |

## Proof

```
$ ./scripts/prove_no_secrets.sh
--- scanner self-check (synthetic kill-test)
self-check: all kill-check and account-check assertions passed

--- git sanity
  inside work tree: yes
  shallow clone: no

--- issue-shaped grep over full history (reported; gate is classifier below)
  issue-shaped grep over full history: 29 matching lines
  (classified below; a history count can only grow — see docs/2026-08-01-vde-51-secrets-out.md)

--- credential classifier (tier A + tier B + .env.example)
tier A hits: 0
tier B matches: 113  (blank=2  expression=44  interpolation=14  local-dev=2  low-entropy=19  placeholder=15  regex-pattern=7  source-literal=10)
unaccounted: 0
env-example: blank-valued and complete

--- .env was never committed
  .env never committed; only .env.example is tracked

--- .gitignore covers .env
  .env, .env.*, !.env.example rules present; git check-ignore confirms

--- .env.example blank-valued and complete
  verified by scan_secrets.py above

VDE-51 ok: no credential-shaped value in history or tree; .env.example blank and complete
```

Exit code: **0**

## The issue's command and the count explained

The issue-shaped command:

```
git log -p | grep -ncE "api[_-]?key=.+|password=.+|xoxb-|hooks.slack.com/services/"
```

returned **19** matching lines as of the commit this proof was captured against. That number is
**not the gate** — a history-based count can only grow: blanking `.env.example` added lines to
the diff, and later fix-pass commits add more. Anyone chasing zero would reach for `git
filter-repo`, which the audit-trail rule forbids. The gate is `unaccounted: 0`.

### Classification of every match

All 113 Tier B matches fall into accounted categories:

| category | count | examples |
|----------|-------|---------|
| `expression` | 44 | `api_key=api_key,` in cli.py; `token: AgentToken,` in TypeScript; `webhook = resolve_slack_webhook_url()` in alerts.py; `parsed.password or "cinema"` in dbt_assets.py |
| `placeholder` | 15 | `SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...` (placeholder URL, `.../` path can't match Tier A) |
| `low-entropy` | 19 | short values, repeated-pattern values, or first tokens of multi-word code below 3.0 bits/char |
| `interpolation` | 14 | `${TOKEN}`, `${DBT_PASSWORD:-cinema}` in prove scripts and configs |
| `regex-pattern` | 7 | prove script grep patterns containing `.+` quantifiers — structurally impossible in any real credential |
| `source-literal` | 10 | scanner reading its own historical source fixtures (Python string literals `"KEY=VALUE",  # comment`); first token ends with a Python closing delimiter — real credentials never do |
| `local-dev` | 2 | ADR-010 local-dev identities (`cinema`, `agent_reader`) in DSN values |
| `blank` | 2 | `TMDB_API_KEY=` blank assignments in `.env.example` history |

The classifier gates on **value shape only** — never on file path. A path exclusion is how a real
secret hides in an allowlisted file.

## Why no history rewrite

No third-party credential was ever committed. The two categories that a naive scan flags are:

- **`cinema:cinema` / `agent_reader:agent_reader`** — ADR-010 local-dev identities, deliberately
  embedded in `docker-compose.yml`, `dbt/profiles.yml`, `src/agent/tools.py`, and several prove
  scripts. Not secrets; present by design.
- **Commented-out lines in `.env.example`** — the old `SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...`
  placeholder used `...` as the token path, which cannot match the Tier A webhook pattern
  (which requires a real segment of at least 7 chars). The fix was to blank the value, not to
  rewrite the commit.

CLAUDE.md: "The audit trail starts at commit one and is never rewritten." Rewriting history for
a clean grep count, when there was never a real secret, destroys an audit trail to make a metric
look better. That is the one thing the classification system exists to prevent.

**Condition that would reverse this:** a genuinely leaked third-party credential (real Slack token,
GitHub PAT, AWS key, Anthropic key, etc.) found anywhere in history. Order of operations in that
case: rotate at the provider first; then `git filter-repo` / BFG to scrub the history; then record
the incident in `ARCHITECTURE.md` §7 field corrections. Rotation before scrubbing because a revoked
credential in history is evidence, not a live risk.

## GitHub secrets table

| key | where used | status |
|-----|-----------|--------|
| `TMDB_API_KEY` | bronze extractor (`src/orchestration/assets.py`) — only needed if CI runs a live extract; today's tests mock all HTTP | not required by any CI workflow today |
| `SLACK_WEBHOOK_URL` | alert sensor (`src/orchestration/alerts.py`) — only needed for a live Slack notification | not required by any CI workflow today |
| `LINEAR_API_KEY` | local tooling only (`scripts/seed-linear.mjs`) — never used in CI | not required by any CI workflow today |

`secret-scan.yml` needs no GitHub repo secret to run — it is satisfied by `python3`, `git`, and
`bash` on the runner. `gh secret list` returned **403** for this integration; secrets that are
needed in future would be set by a human at *Settings → Secrets and variables → Actions*. No
secret was set as part of this issue.

## Trail

```
VDE-51 → cursor/vde-51-secrets-out-c800
  → scripts/scan_secrets.py
  → scripts/prove_no_secrets.sh
  → .env.example (rewritten)
  → .github/workflows/secret-scan.yml
  → docs/2026-08-01-vde-51-secrets-out.md
  → DECISIONS.md (ADR-014)
  → ARCHITECTURE.md (§10 row)
  → README.md (two rows)
```
