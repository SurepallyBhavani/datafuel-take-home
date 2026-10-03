"""Tests for sweep.py that need no portal: the portal's replies are replaced by small fakes."""
import pytest

import sweep
from conftest import make_roster


def test_late_utc_sweep_belongs_to_the_next_ist_day(tmp_path):
    conn = sweep.db.connect(str(tmp_path / "days.db"))
    sweep.db.create_tables(conn)
    expected = {"2026-09-27T04:30:00Z": "2026-09-27", "2026-09-27T10:30:00Z": "2026-09-27",
                "2026-09-27T19:00:00Z": "2026-09-28", "2026-09-28T18:40:00Z": "2026-09-29"}
    for as_of_text in expected:
        sweep.prepare_sweep(conn, as_of_text, sweep.parse_time(as_of_text), [])
    saved = dict(conn.execute("SELECT as_of, ist_date FROM sweeps").fetchall())
    assert saved == expected


def test_as_of_written_in_india_time_is_the_same_sweep():
    assert sweep.utc_text(sweep.parse_time("2026-09-28T10:00:00+05:30")) == "2026-09-28T04:30:00Z"
    with pytest.raises(ValueError):
        sweep.parse_time("2026-09-28T04:30:00")              # no timezone


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
