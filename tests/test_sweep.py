"""Tests for sweep.py that need no portal: the portal's replies are replaced by small fakes."""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sweep  # noqa: E402

AS_OF = "2026-09-28T04:30:00Z"
GOOD_ITEM = {"sku_id": "SKU-0001", "name": "Milk", "in_stock": True, "qty": 5,
             "price": "10.50", "observed_at": "2026-09-28T10:15:00+05:30"}


def make_roster(count):
    return [{"store_id": "MUM-%03d" % i, "city": "Mumbai", "name": "Store %d" % i,
             "is_active": True, "is_serviceable": True} for i in range(1, count + 1)]


@pytest.fixture
def run_sweep(tmp_path, monkeypatch):
    """Run sweep.main() in a temporary folder with a fake roster and a fake fetch for each store."""
    monkeypatch.chdir(tmp_path)               # osa.db is created here
    monkeypatch.setattr(sweep.time, "sleep", lambda seconds: None)

    def run(roster, outcome_for_store):
        """outcome_for_store(store_id) returns 'ok', or a reason code such as 'soft_banned' or 'partial'."""
        def fake_fetch_all_pages(store_id, as_of_text, counts):
            outcome = outcome_for_store(store_id)
            if outcome == "ok":
                return [dict(GOOD_ITEM)], None, None
            return None, outcome, "fake " + outcome

        monkeypatch.setattr(sweep, "get_roster", lambda: roster)
        monkeypatch.setattr(sweep, "fetch_all_pages", fake_fetch_all_pages)
        monkeypatch.setattr(sys, "argv", ["sweep.py", "--as-of", AS_OF])
        try:
            sweep.main()
            exit_code = 0
        except SystemExit as e:
            exit_code = e.code
        return sqlite3.connect(tmp_path / "osa.db"), exit_code

    return run


def test_soft_banned_store_saves_no_rows(run_sweep):
    conn, _ = run_sweep(make_roster(1), lambda store_id: "soft_banned")
    assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0
    status, code = conn.execute("SELECT status, reason_code FROM store_sweeps").fetchone()
    assert (status, code) == ("incomplete", "soft_banned")


def test_sweep_stops_after_three_banned_stores_in_a_row(run_sweep):
    conn, exit_code = run_sweep(make_roster(6), lambda store_id: "soft_banned")
    rows = dict(conn.execute("SELECT store_id, status FROM store_sweeps").fetchall())
    assert [rows["MUM-00%d" % i] for i in range(1, 7)] == ["incomplete"] * 3 + ["pending"] * 3
    reason = conn.execute("SELECT reason_code FROM store_sweeps WHERE store_id = 'MUM-004'").fetchone()[0]
    assert reason == "not_attempted"
    assert exit_code == 1


def test_a_good_store_resets_the_banned_count(run_sweep):
    # banned, banned, ok, banned, banned, ok: never three in a row, so every store is tried
    order = {"MUM-001": "soft_banned", "MUM-002": "soft_banned", "MUM-003": "ok",
             "MUM-004": "soft_banned", "MUM-005": "soft_banned", "MUM-006": "ok"}
    conn, exit_code = run_sweep(make_roster(6), lambda store_id: order[store_id])
    statuses = [row[0] for row in conn.execute("SELECT status FROM store_sweeps ORDER BY store_id")]
    assert statuses.count("pending") == 0
    assert exit_code == 0


def test_rerun_with_nothing_to_fetch_keeps_the_run_times(run_sweep):
    conn, _ = run_sweep(make_roster(2), lambda store_id: "ok")
    started, finished = conn.execute("SELECT started_at, finished_at FROM sweeps").fetchone()
    assert started is not None and finished is not None
    conn.execute("UPDATE sweeps SET started_at = 'old', finished_at = 'old'")   # mark the times
    conn.commit()

    conn, _ = run_sweep(make_roster(2), lambda store_id: "ok")   # everything is already complete
    assert conn.execute("SELECT started_at, finished_at FROM sweeps").fetchone() == ("old", "old")


def test_rerun_that_fetches_something_updates_both_times(run_sweep):
    conn, _ = run_sweep(make_roster(2), lambda store_id: "partial" if store_id == "MUM-002" else "ok")
    conn.execute("UPDATE sweeps SET started_at = 'old', finished_at = 'old'")   # mark the times
    conn.commit()

    conn, _ = run_sweep(make_roster(2), lambda store_id: "ok")   # MUM-002 is retried
    started, finished = conn.execute("SELECT started_at, finished_at FROM sweeps").fetchone()
    assert started != "old" and finished != "old"
