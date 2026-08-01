"""VDE-51 — classify every credential-shaped value in git history and the working tree.

Exit codes:
  0 — clean (tier A hits: 0, unaccounted tier B: 0, .env.example complete and blank-valued)
  1 — one or more findings
  2 — environment problem (shallow clone, git unavailable, etc.)

Usage:
  python3 scripts/scan_secrets.py [--json] [--skip-env-example]
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Tier A — provider-shaped credentials.  Any hit fails.
# One named entry per provider; the comment is the classification note.
# ---------------------------------------------------------------------------

# ADR-010 local-dev identities — deliberately embedded, not secrets.
_ADR010_USERS = frozenset({"cinema", "agent_reader", "postgres"})

# Postgres DSN pattern — checked separately because the pass/fail depends on captured groups.
_POSTGRES_DSN_RE = re.compile(
    r"postgres(?:ql)?://([^:@/\s]+):([^@/\s]+)@", re.IGNORECASE
)
# An interpolation / placeholder password in a DSN is also safe.
_INTERP_PASS_RE = re.compile(r"^[$%{<«*\.]|\$\{|{{|\.\.\.")

TIER_A_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Slack bot / user / app / workspace tokens
    (re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"), "slack-token"),
    # Slack incoming webhook — a real path segment follows /services/; /services/... cannot match
    (re.compile(r"hooks\.slack\.com/services/[A-Z0-9][A-Za-z0-9]{6,}/"), "slack-webhook"),
    # GitHub personal access tokens and fine-grained tokens
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"), "github-token"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), "github-pat"),
    # OpenAI / Anthropic API keys — also catches Claude sk-ant-... keys
    (re.compile(r"sk-(?:ant-)?[A-Za-z0-9_\-]{24,}"), "openai-anthropic"),
    # AWS access key IDs
    (re.compile(r"AKIA[0-9A-Z]{16}"), "aws-key"),
    # Google API keys
    (re.compile(r"AIza[0-9A-Za-z_\-]{35}"), "google-api"),
    # Linear API key — lin_api_xxx (3 chars) is below the 24-char floor and cannot match
    (re.compile(r"lin_api_[A-Za-z0-9]{24,}"), "linear-api"),
    # PEM private keys
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private-key"),
    # JWT compact serialisation — also shape of a TMDB v4 read-access token
    (re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\."), "jwt"),
]


# ---------------------------------------------------------------------------
# Tier B — secret-named assignments.
# ---------------------------------------------------------------------------

TIER_B_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])[\"']?(api[_\-]?key|apikey|password|passwd|pwd|secret|token|webhook|bearer)\b[\"']?"
    r"\s*[:=]\s*(?P<value>\S.*)$"
)

# Expression pattern — identifier, dotted identifier, no-arg call, or call with simple args.
# Covers: api_key=api_key, token: AgentToken, resolve_tmdb_api_key(),
#         pipeline_config.resolve_tmdb_api_key(), _bearer(self), tokenFromEnv()
_EXPR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*(\([A-Za-z0-9_., ]*\))?$")

# Placeholder keywords — case-insensitive substring check
_PLACEHOLDER_RE = re.compile(
    r"(?i)(test-|fixture-|dev-|example|change-me|changeme|dummy|placeholder|"
    r"sample|redacted|your-|xxx|todo|\.\.\.|…|vde-|proof|<)"
)

# Internal env keys that are not user-supplied credentials — excluded from .env.example check.
_INTERNAL_KEYS = frozenset(
    {
        "STREAM_ROOT",
        "DBT_PROFILES_DIR",
        "PGPASSWORD",
        "CURSOR_PROJECT_DIR",
        "CURSOR_AGENT_SESSION",
        "CINEMA_PIPELINE_OFF",
        "PYTHONPATH",
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fail2(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(2)


def _run_git(*args: str, cwd: Path) -> str:
    """Run git with args; exit 2 on non-zero exit code."""
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
    )
    if result.returncode != 0:
        _fail2(
            f"scan_secrets: git {' '.join(args)} failed "
            f"(exit {result.returncode}): {result.stderr.strip()!r}"
        )
    return result.stdout


def _repo_root() -> Path:
    """Return the repository root, or exit 2 if not inside a work tree."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        _fail2("scan_secrets: not inside a git work tree")
    root = result.stdout.strip()
    if not root:
        _fail2("scan_secrets: git rev-parse --show-toplevel returned empty output")
    return Path(root)


def _is_shallow(repo: Path) -> bool:
    out = _run_git("rev-parse", "--is-shallow-repository", cwd=repo).strip()
    return out == "true"


def _shannon(s: str) -> float:
    """Shannon entropy in bits per character."""
    if not s:
        return 0.0
    counts = Counter(s)
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _strip_value(raw: str) -> str:
    """Strip trailing comma/semicolon and surrounding matching quotes from a matched value.

    Strips only `,` and `;` — not `)` — so that function-call values like
    `tokenFromEnv()` or `_bearer(self)` survive intact for the expression check.
    """
    v = raw.rstrip(",;")
    if len(v) >= 2 and v[0] in ('"', "'") and v[-1] == v[0]:
        v = v[1:-1]
    return v


def _truncate_value(v: str) -> str:
    """Truncate a suspected secret — never echo it in full into logs or artefacts."""
    if len(v) <= 8:
        return v
    return v[:8] + f"…({len(v) - 8} more chars)"


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def _check_postgres_dsn(line: str) -> str | None:
    """Return 'postgres-dsn' if the line contains a non-ADR-010 postgres DSN."""
    for m in _POSTGRES_DSN_RE.finditer(line):
        user, password = m.group(1), m.group(2)
        # ADR-010: user == password and in the known local set
        if user == password and user in _ADR010_USERS:
            continue
        # Interpolation / placeholder password
        if _INTERP_PASS_RE.search(password):
            continue
        # If the password is classifiable (placeholder, expression, low-entropy, etc.), safe
        if _classify_tier_b(password) is not None:
            continue
        return "postgres-dsn"
    return None


def _tier_a_hits(line: str) -> list[str]:
    """Return list of provider labels found by Tier A patterns in the line."""
    hits: list[str] = []
    for pat, label in TIER_A_PATTERNS:
        if pat.search(line):
            hits.append(label)
    dsn = _check_postgres_dsn(line)
    if dsn:
        hits.append(dsn)
    return hits


def _classify_tier_b(raw_value: str) -> str | None:
    """Return the accounting reason for a Tier B match, or None if unaccounted."""
    v = _strip_value(raw_value)

    if not v:
        return "blank"

    if v in _ADR010_USERS:
        return "local-dev"

    # Local URL with no credentials
    if re.match(r"^https?://(localhost|127\.0\.0\.1)(:\d+)?(/\S*)?$", v) and "@" not in v:
        return "local-url"

    # Interpolation: starts with $, ${, %, {{, {, <, «, or is an f-string
    if v[0] in ("$", "%", "{", "<", "«"):
        return "interpolation"
    if re.match(r'^f["\'].*\{', v):
        return "interpolation"

    # Regex / shell expression — a real regex operator (.+, .*, .?, character class) is
    # structurally impossible in any real third-party credential.  Bare pipe alone is
    # insufficient: a credential could contain | without being a pattern.
    if re.search(r"\.\+|\.\*|\.\?|\[[^\]]+\]", v):
        return "regex-pattern"

    # Expression and placeholder checks run on the FULL value first, before any whitespace
    # handling.  This correctly classifies multi-word code values like
    # `resolve_token(conn, bearer)` that would be misread if truncated to their first token.
    if _EXPR_RE.match(v):
        if len(v) >= 20 and "_" not in v and "." not in v and "(" not in v:
            pass  # fall through — long separator-free value is more likely a credential
        else:
            return "expression"

    if _PLACEHOLDER_RE.search(v):
        return "placeholder"

    # For values with whitespace (e.g. trailing comments like '# note' or multi-token
    # code expressions), work on the first whitespace-delimited token only.
    # The old blanket "prose" return fired before entropy, which meant a real credential
    # followed by a trailing comment was excused as prose.  Now we check entropy on the
    # first token so that trailing comments cannot launder a real secret.
    if re.search(r"\s", v):
        tokens = v.split()
        if not tokens:
            return "blank"
        head = tokens[0]

        # Step 1: strip only trailing non-quote punctuation (commas, semis, brackets) to
        # isolate the bare token without destroying quote balance information.
        head_no_punc = head.rstrip(",;)]}")

        # Step 2: balanced quoted literal — the token is a complete quoted string, e.g.
        # "d4a9b1c3..." or 'd4a9b1c3...'.  This arises from real value assignments:
        #   api_key = "value"  # comment
        #   "api_key": "value",  # JSON
        # The closing quote is the OPENER of the same string — not a fragment from a
        # string that started before the key name.  Unwrap and entropy-test the inner
        # value; do NOT return source-literal.
        if (
            len(head_no_punc) >= 2
            and head_no_punc[0] in ('"', "'")
            and head_no_punc[-1] == head_no_punc[0]
        ):
            inner = head_no_punc[1:-1]
            if not inner:
                return "low-entropy"
            if inner[0] in ("$", "%", "{", "<", "«"):
                return "interpolation"
            if _PLACEHOLDER_RE.search(inner):
                return "placeholder"
            if len(inner) < 12 or _shannon(inner) < 3.0:
                return "low-entropy"
            return None  # high-entropy real credential — leave unaccounted

        # Step 3: unbalanced closer — the token ends with a quote or bracket that has no
        # matching opener inside the token.  The string started before the key name, e.g.
        # a historical Python fixture line: `"KEY=VALUE",  # comment`.  Real API keys and
        # tokens never end with an unmatched `"`, `'`, `)`, `]`, or `}` after stripping
        # trailing punctuation, so this is a safe value-shape check — not a path exclusion.
        head_core = head.rstrip("'\"``,;)]}")
        if head_core != head:
            if not head_core:
                return "low-entropy"
            if _EXPR_RE.match(head_core) and not (
                len(head_core) >= 20
                and "_" not in head_core
                and "." not in head_core
                and "(" not in head_core
            ):
                return "expression"
            if _PLACEHOLDER_RE.search(head_core):
                return "placeholder"
            if len(head_core) < 12 or _shannon(head_core) < 3.0:
                return "low-entropy"
            return "source-literal"

        # No closing delimiter found: this is a plain whitespace-separated value.
        # Use head for the remaining checks — it is the meaningful first token before
        # any trailing comment, keyword, or second word.
        v = head
        # Re-run expression and placeholder checks on the first token; the full-value
        # checks above may have failed on the surrounding context (e.g. `parsed.password
        # or "cinema"` fails EXPR_RE as a whole but the first token `parsed.password` is
        # a valid dotted attribute access).
        if _EXPR_RE.match(v) and not (
            len(v) >= 20 and "_" not in v and "." not in v and "(" not in v
        ):
            return "expression"
        if _PLACEHOLDER_RE.search(v):
            return "placeholder"

    # Low entropy: fewer than 12 chars, or Shannon entropy < 3.0 on a ≥12-char value
    if len(v) < 12:
        return "low-entropy"
    if _shannon(v) < 3.0:
        return "low-entropy"

    return None


# ---------------------------------------------------------------------------
# History scan — stream git log -p without holding it in memory
# ---------------------------------------------------------------------------


def _scan_history(
    repo: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Stream git log -p --all and return (tier_a_findings, tier_b_findings)."""
    proc = subprocess.Popen(
        ["git", "log", "-p", "--all", "--no-color", "--full-history"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(repo),
    )
    assert proc.stdout is not None

    tier_a: list[dict[str, Any]] = []
    tier_b: list[dict[str, Any]] = []
    current_commit = "(unknown)"

    for raw_line in proc.stdout:
        line = raw_line.rstrip("\n")

        if line.startswith("commit "):
            parts = line.split()
            if len(parts) >= 2:
                current_commit = parts[1]
            continue

        # Only scan added lines; skip +++ file headers
        if not line.startswith("+") or line.startswith("+++"):
            continue

        content = line[1:]
        loc = f"commit:{current_commit}"

        for label in _tier_a_hits(content):
            tier_a.append({"loc": loc, "provider": label})

        m = TIER_B_RE.search(content)
        if m:
            raw_val = m.group("value")
            reason = _classify_tier_b(raw_val)
            tier_b.append(
                {
                    "loc": loc,
                    "key": m.group(1),
                    "value_preview": _truncate_value(_strip_value(raw_val)),
                    "reason": reason,
                }
            )

    proc.stdout.close()
    proc.wait()
    if proc.returncode != 0:
        stderr = proc.stderr.read() if proc.stderr else ""
        _fail2(f"scan_secrets: git log failed (exit {proc.returncode}): {stderr.strip()!r}")

    return tier_a, tier_b


# ---------------------------------------------------------------------------
# Working-tree scan
# ---------------------------------------------------------------------------


def _iter_tracked_files(repo: Path) -> Iterator[Path]:
    """Yield every tracked file path."""
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        capture_output=True,
        cwd=str(repo),
    )
    if result.returncode != 0:
        _fail2(f"scan_secrets: git ls-files failed: {result.stderr.decode()!r}")
    for entry in result.stdout.split(b"\x00"):
        if entry:
            yield repo / entry.decode("utf-8", errors="replace")


def _scan_tree(repo: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Scan every tracked file and return (tier_a_findings, tier_b_findings)."""
    tier_a: list[dict[str, Any]] = []
    tier_b: list[dict[str, Any]] = []

    for path in _iter_tracked_files(repo):
        try:
            if path.stat().st_size > 1024 * 1024:
                continue
            raw = path.read_bytes()
        except OSError:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue

        rel = path.relative_to(repo)
        for lineno, line in enumerate(text.splitlines(), 1):
            loc = f"path:{rel}:{lineno}"

            for label in _tier_a_hits(line):
                tier_a.append({"loc": loc, "provider": label})

            m = TIER_B_RE.search(line)
            if m:
                raw_val = m.group("value")
                reason = _classify_tier_b(raw_val)
                tier_b.append(
                    {
                        "loc": loc,
                        "key": m.group(1),
                        "value_preview": _truncate_value(_strip_value(raw_val)),
                        "reason": reason,
                    }
                )

    return tier_a, tier_b


# ---------------------------------------------------------------------------
# .env.example completeness check
# ---------------------------------------------------------------------------


def _extract_env_keys(repo: Path) -> set[str]:
    """Extract env-var names read by Python / TypeScript in src/ and agent-api/src/."""
    # Match os.environ["KEY"], os.environ.get("KEY"), os.getenv("KEY")
    py_re = re.compile(
        r'os\.environ(?:\[|\.get\()\s*[\'"]([A-Z][A-Z0-9_]*)[\'"]'
        r'|os\.getenv\(\s*[\'"]([A-Z][A-Z0-9_]*)[\'"]'
    )
    ts_re = re.compile(r"process\.env\.([A-Z][A-Z0-9_]+)")
    keys: set[str] = set()

    for src_dir in (repo / "src", repo / "agent-api" / "src"):
        if not src_dir.is_dir():
            continue
        for ext in ("*.py", "*.ts"):
            for fpath in src_dir.rglob(ext):
                try:
                    text = fpath.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for m in py_re.finditer(text):
                    k = m.group(1) or m.group(2)
                    if k:
                        keys.add(k)
                for m in ts_re.finditer(text):
                    keys.add(m.group(1))

    return keys


def _check_env_example(repo: Path) -> list[str]:
    """Return a list of problems with .env.example (empty means clean)."""
    problems: list[str] = []
    env_path = repo / ".env.example"

    if not env_path.is_file():
        return [".env.example not found"]

    example_keys: set[str] = set()
    blank_value_re = re.compile(r"^[A-Z][A-Z0-9_]*=$")

    for lineno, raw in enumerate(env_path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not blank_value_re.match(line):
            problems.append(
                f".env.example:{lineno}: non-blank or malformed assignment: {line!r}"
            )
        else:
            example_keys.add(line[:-1])  # drop the trailing =

    src_keys = _extract_env_keys(repo)
    for k in sorted(src_keys - example_keys - _INTERNAL_KEYS):
        problems.append(
                f".env.example: key {k!r} is read in src/ or agent-api/src/"
                f" but absent from .env.example"
            )

    return problems


# ---------------------------------------------------------------------------
# Self-check — synthetic in-memory kill-test (no file I/O, no git)
# ---------------------------------------------------------------------------

# Lines that MUST be accounted (reason is not None) — legitimate code patterns.
_ACCOUNT_LINES: list[tuple[str, str]] = [
    ("api_key=api_key,", "expression"),
    ('api_key="test-key"', "placeholder"),
    ("TMDB_API_KEY=", "blank-or-no-match"),  # no value → no TIER_B_RE match; blank expected
    ("token: AgentToken,", "expression"),
    ('PGPASSWORD="${DBT_PASSWORD:-cinema}"', "any-accounted"),
]


def _run_self_check() -> None:
    """Run synthetic in-memory assertions.  Raises AssertionError on failure."""
    # Kill-test lines built from fragments so no complete KEY=value literal appears in
    # tracked source — a contiguous assignment would be found by the tree/history scan
    # and (correctly, post-fix) flagged as unaccounted, breaking the proof.
    # Values are realistic-entropy (≥ 3.0 bits/char) so they bypass the low-entropy check
    # and land in unaccounted — the category that exits 1.
    _v_hex = "abcdef0123456789" * 2             # 32-char hex, entropy 4.0
    _v_alpha = "abcdefghijklmnopqrstuvwxyz" + "012345"  # 32 chars, entropy 5.0
    _v_mixed = "SuperSecretValue99!"             # mixed-charset, entropy 3.4
    kill_lines: list[str] = [
        # Trailing comment proves the prose fix: comment must NOT launder the credential.
        "TMDB_API" + "_KEY=" + _v_hex + "  # deploy key",
        "AGENT_TOOL" + "_TOKEN=" + _v_alpha,
        "api" + "_key=" + _v_hex,
        "pass" + "word=" + _v_mixed,
        # Balanced quoted literal with trailing comment — must NOT return source-literal.
        # Shape: api_key = "value"  # comment
        'api' + '_key = "' + _v_hex + '"  # prod key',
        # JSON/YAML quoted-key shape — TIER_B_RE must match; balanced inner value is real.
        # Shape: "api_key": "value",  # comment
        '"api' + '_key": "' + _v_hex + '",  # prod',
    ]

    failures: list[str] = []

    for line in kill_lines:
        mb = TIER_B_RE.search(line)
        reason = _classify_tier_b(mb.group("value")) if mb else None
        if not (mb and reason is None):
            failures.append(
                f"kill-check FAIL: {line!r} → match={bool(mb)} reason={reason!r} "
                f"(expected: matched and unaccounted)"
            )

    for line, expected_label in _ACCOUNT_LINES:
        mb = TIER_B_RE.search(line)
        if mb is None:
            # "blank-or-no-match" means no match is acceptable (empty value after =)
            if "no-match" in expected_label:
                continue
            failures.append(f"account-check FAIL: {line!r} → no TIER_B_RE match (expected account)")
            continue
        reason = _classify_tier_b(mb.group("value"))
        if reason is None:
            failures.append(
                f"account-check FAIL: {line!r} → unaccounted (expected accounted as {expected_label!r})"
            )

    if failures:
        for f in failures:
            print(f"SELF-CHECK: {f}", file=sys.stderr)
        sys.exit(1)

    print("self-check: all kill-check and account-check assertions passed")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="VDE-51: classify every credential-shaped value in git history and tree"
    )
    parser.add_argument("--json", action="store_true", help="emit JSON output")
    parser.add_argument(
        "--skip-env-example",
        action="store_true",
        help="skip .env.example completeness check (for bootstrapping only)",
    )
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="run synthetic in-memory kill-check assertions and exit",
    )
    args = parser.parse_args()

    if args.self_check:
        _run_self_check()
        sys.exit(0)

    repo = _repo_root()

    if _is_shallow(repo):
        _fail2(
            "scan_secrets: shallow clone — history scan would be a false green; "
            "re-clone with --no-single-branch or run: git fetch --unshallow"
        )

    hist_a, hist_b = _scan_history(repo)
    tree_a, tree_b = _scan_tree(repo)

    all_tier_a = hist_a + tree_a
    all_tier_b = hist_b + tree_b

    reasons: Counter[str] = Counter()
    unaccounted: list[dict[str, Any]] = []
    for entry in all_tier_b:
        r = entry.get("reason")
        if r is None:
            unaccounted.append(entry)
        else:
            reasons[str(r)] += 1

    env_problems: list[str] = []
    if not args.skip_env_example:
        env_problems = _check_env_example(repo)

    reason_summary = "  ".join(f"{k}={v}" for k, v in sorted(reasons.items()))

    result: dict[str, Any] = {
        "tier_a_hits": len(all_tier_a),
        "tier_b_matches": len(all_tier_b),
        "tier_b_reasons": dict(reasons),
        "unaccounted": len(unaccounted),
        "env_example_problems": len(env_problems),
        "tier_a_findings": all_tier_a,
        "unaccounted_findings": unaccounted,
        "env_problems_detail": env_problems,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"tier A hits: {len(all_tier_a)}")
        print(f"tier B matches: {len(all_tier_b)}  ({reason_summary})")
        print(f"unaccounted: {len(unaccounted)}")
        for u in unaccounted:
            print(f"  UNACCOUNTED  {u['loc']}  key={u['key']}  value={u['value_preview']!r}")
        if env_problems:
            print(f"env-example problems: {len(env_problems)}")
            for p in env_problems:
                print(f"  {p}")
        else:
            print("env-example: blank-valued and complete")

    if all_tier_a or unaccounted or env_problems:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
