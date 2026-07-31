"""VDE-11 — raw payloads are immutable.

Mirrors the issue proof:
  grep -rniE "update bronze|delete from bronze|truncate bronze" src/ | wc -l
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
PATTERN = re.compile(r"update bronze|delete from bronze|truncate bronze", re.I)
SQL_ROLE = REPO_ROOT / "sql" / "init" / "002_extractor_role.sql"


def test_src_has_no_bronze_mutations_via_grep() -> None:
    """Shell proof from VDE-11 — green exit code on a clean clone."""
    script = REPO_ROOT / "scripts" / "prove-bronze-immutable.sh"
    result = subprocess.run(
        ["bash", str(script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_src_has_no_bronze_mutations_via_scan() -> None:
    """Same invariant without depending on grep flags."""
    assert SRC.is_dir(), "src/ must exist for the bronze mutation scan"
    offenders: list[str] = []
    for path in SRC.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if PATTERN.search(line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{i}:{line.strip()}")
    assert offenders == [], "bronze mutations in src/\n" + "\n".join(offenders)


def test_extractor_role_sql_withholds_update_and_delete() -> None:
    """Database enforcement: grants INSERT, never UPDATE/DELETE/TRUNCATE."""
    sql = SQL_ROLE.read_text(encoding="utf-8")
    assert re.search(r"GRANT\s+INSERT\s+ON\s+ALL\s+TABLES\s+IN\s+SCHEMA\s+bronze", sql, re.I)
    assert re.search(r"REVOKE\s+UPDATE,\s*DELETE,\s*TRUNCATE", sql, re.I)
    # Positive grants must not include mutating verbs on bronze tables.
    for verb in ("UPDATE", "DELETE", "TRUNCATE"):
        assert not re.search(
            rf"GRANT\s+{verb}\b.*\bSCHEMA\s+bronze",
            sql,
            re.I | re.S,
        )
