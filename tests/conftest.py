"""Helpers shared by the sweep tests. The portal is never used: its replies are replaced by small fakes."""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sweep  # noqa: E402

AS_OF = "2026-09-28T04:30:00Z"
GOOD_ITEM = {"sku_id": "SKU-0001", "name": "Milk", "in_stock": True, "qty": 5,
             "price": "10.50", "observed_at": "2026-09-28T10:15:00+05:30"}


def roster_store(store_id, active=True, serviceable=True, city="Mumbai"):
    return {"store_id": store_id, "city": city, "name": "Store " + store_id,
            "is_active": active, "is_serviceable": serviceable}


def make_roster(count):
    return [roster_store("MUM-%03d" % i) for i in range(1, count + 1)]


@pytest.fixture
def run_sweep(tmp_path, monkeypatch):
    """Run sweep.main() in a temporary folder with a fake roster and a fake fetch for each store.

    run(roster, outcome_for_store, as_of) returns (database connection, exit code).
    outcome_for_store(store_id) returns 'ok', 'empty', or a reason code such as 'soft_banned' or 'partial'.
    run_sweep.fetched lists the stores that were fetched in the latest run."""
    monkeypatch.chdir(tmp_path)               # osa.db is created here
    monkeypatch.setattr(sweep.time, "sleep", lambda seconds: None)
    fetched = []

    def run(roster, outcome_for_store, as_of=AS_OF):
        fetched.clear()

        def fake_fetch_all_pages(store_id, as_of_text, counts):
            fetched.append(store_id)
            outcome = outcome_for_store(store_id)
            if outcome == "ok":
                return [dict(GOOD_ITEM)], None, None
            if outcome == "empty":
                return [], None, None
            return None, outcome, "fake " + outcome

        monkeypatch.setattr(sweep, "get_roster", lambda: roster)
        monkeypatch.setattr(sweep, "fetch_all_pages", fake_fetch_all_pages)
        monkeypatch.setattr(sys, "argv", ["sweep.py", "--as-of", as_of])
        try:
            sweep.main()
            exit_code = 0
        except SystemExit as e:
            exit_code = e.code
        return sqlite3.connect(tmp_path / "osa.db"), exit_code

    run.fetched = fetched
    return run
