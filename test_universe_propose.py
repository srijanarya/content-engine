#!/usr/bin/env python3
"""Tests for monitor.universe_propose.

Run: /opt/homebrew/bin/python3 test_universe_propose.py
"""
import contextlib
import io
import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import monitor.universe_propose as universe_propose


NOW = datetime(2026, 7, 13, 8, 30, tzinfo=timezone.utc)


def _build_db(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE realtime_filings ("
            "bse_code TEXT, company_name TEXT, filing_type TEXT, detected_at TEXT, status TEXT)"
        )
        rows = [
            ("532281", "HCL Technologies Ltd", "earnings", (NOW - timedelta(hours=2)).isoformat(), "new"),
            ("100001", "New Proposal Ltd", "earnings", (NOW - timedelta(hours=3)).isoformat(), "new"),
            ("100002", "Already Proposed Ltd", "earnings", (NOW - timedelta(hours=4)).isoformat(), "new"),
        ]
        rows.extend(
            (str(100010 + index), f"Fresh Proposal {index} Ltd", "earnings",
             (NOW - timedelta(hours=5 + index)).isoformat(), "new")
            for index in range(7)
        )
        connection.executemany("INSERT INTO realtime_filings VALUES (?, ?, ?, ?, ?)", rows)


@contextlib.contextmanager
def _fixture(missing_db: bool = False):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        db = root / "filings.db"
        if not missing_db:
            _build_db(db)
        universe = root / "earnings_universe.txt"
        universe.write_text("# curated universe\nHCLTECH\nTCS\n")
        proposed = root / "universe_proposed.json"
        proposed.write_text(json.dumps({
            "100002": {"company_name": "Already Proposed Ltd", "first_proposed": "2026-07-12T08:30:00+00:00"}
        }))
        escalations = root / "autonomy" / "escalations"
        with patch.object(universe_propose, "UNIVERSE_PATH", universe), \
             patch.object(universe_propose, "PROPOSED_PATH", proposed), \
             patch.object(universe_propose, "ESC_DIR", escalations), \
             patch.dict(os.environ, {"AKSH_FILINGS_DB": str(db)}, clear=False):
            yield root, proposed, escalations


def test_proposes_only_new_out_of_universe_filings_with_cap():
    with _fixture() as (_, proposed_path, escalations):
        universe_propose.run(NOW)
        escalation = escalations / "universe-proposal-2026-07-13.md"
        body = escalation.read_text()
        proposed = json.loads(proposed_path.read_text())

    assert "HCL Technologies Ltd" not in body
    assert "Already Proposed Ltd" not in body
    assert "New Proposal Ltd" in body
    assert body.count("Action: add the symbol") == 5, body
    assert "+3 more" in body, body
    assert len(proposed) == 6, proposed  # seeded record + five emitted proposals


def test_escalation_name_is_idempotent_per_day():
    with _fixture() as (_, _, escalations):
        universe_propose.run(NOW)
        universe_propose.run(NOW + timedelta(hours=2))
        files = list(escalations.glob("universe-proposal-*.md"))

    assert [path.name for path in files] == ["universe-proposal-2026-07-13.md"]


def test_missing_db_exits_cleanly():
    with _fixture(missing_db=True):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            universe_propose.run(NOW)

    assert "filings DB missing" in stderr.getvalue()


if __name__ == "__main__":
    tests = [value for key, value in sorted(globals().items()) if key.startswith("test_")]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {test.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
