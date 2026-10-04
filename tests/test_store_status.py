"""The store flags and statuses that sweep.py saves: who is fetched, what is recorded, what is kept on a re-run."""
import pytest

import sweep
from conftest import make_roster, roster_store


def states(conn):
    """store_id -> (status, reason_code, is_active, is_serviceable, item_count)"""
    rows = conn.execute("SELECT store_id, status, reason_code, is_active, is_serviceable, item_count "
                        "FROM store_sweeps").fetchall()
    return {row[0]: tuple(row[1:]) for row in rows}


def test_inactive_store_is_skipped_and_never_fetched(run_sweep):
    roster = [roster_store("MUM-001"), roster_store("MUM-009", active=False)]
    conn, _ = run_sweep(roster, lambda store_id: "ok")
    assert run_sweep.fetched == ["MUM-001"]
    assert states(conn)["MUM-009"] == ("skipped", "inactive", 0, 1, None)


def test_active_but_not_serviceable_store_is_fetched_and_its_flags_are_saved(run_sweep):
    roster = [roster_store("DEL-006", serviceable=False, city="Delhi")]
    conn, _ = run_sweep(roster, lambda store_id: "ok")
    assert run_sweep.fetched == ["DEL-006"]
    assert states(conn)["DEL-006"] == ("complete", None, 1, 0, 1)
    assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1


def test_every_roster_store_gets_a_row_with_the_flags_it_had(run_sweep):
    roster = [roster_store("MUM-001"), roster_store("MUM-002", serviceable=False),
              roster_store("MUM-003", active=False), roster_store("MUM-004", active=False, serviceable=False)]
    conn, _ = run_sweep(roster, lambda store_id: "ok")
    flags = {sid: (s[2], s[3]) for sid, s in states(conn).items()}
    assert flags == {"MUM-001": (1, 1), "MUM-002": (1, 0), "MUM-003": (0, 1), "MUM-004": (0, 0)}


def test_each_sweep_keeps_the_flags_it_saw(run_sweep):
    first, second = "2026-09-27T04:30:00Z", "2026-09-27T10:30:00Z"
    run_sweep([roster_store("MUM-001", serviceable=True)], lambda store_id: "ok", as_of=first)
    conn, _ = run_sweep([roster_store("MUM-001", serviceable=False)], lambda store_id: "ok", as_of=second)
    rows = conn.execute("SELECT as_of, is_serviceable FROM store_sweeps ORDER BY as_of").fetchall()
    assert rows == [(first, 1), (second, 0)]


def test_complete_store_keeps_its_saved_flags_and_is_not_fetched_again(run_sweep):
    run_sweep([roster_store("MUM-001", serviceable=True)], lambda store_id: "ok")
    conn, _ = run_sweep([roster_store("MUM-001", serviceable=False)], lambda store_id: "ok")   # the roster changed
    assert run_sweep.fetched == []
    assert states(conn)["MUM-001"][:1] + states(conn)["MUM-001"][3:4] == ("complete", 1)


def test_incomplete_store_gets_fresh_flags_and_is_fetched_again(run_sweep):
    run_sweep([roster_store("MUM-001", serviceable=True)], lambda store_id: "partial")
    conn, _ = run_sweep([roster_store("MUM-001", serviceable=False)], lambda store_id: "ok")
    assert run_sweep.fetched == ["MUM-001"]
    assert states(conn)["MUM-001"] == ("complete", None, 1, 0, 1)


def test_store_with_no_products_is_complete_with_zero_items(run_sweep):
    conn, _ = run_sweep([roster_store("BLR-007", city="Bengaluru")], lambda store_id: "empty")
    assert states(conn)["BLR-007"] == ("complete", None, 1, 1, 0)
    assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0


def test_partial_store_is_incomplete_with_its_reason_and_saves_nothing(run_sweep):
    conn, _ = run_sweep(make_roster(2), lambda store_id: "partial" if store_id == "MUM-002" else "ok")
    assert states(conn)["MUM-002"][:2] == ("incomplete", "partial")
    assert conn.execute("SELECT COUNT(*) FROM observations WHERE store_id = 'MUM-002'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM observations WHERE store_id = 'MUM-001'").fetchone()[0] == 1


def test_a_store_that_gives_up_does_not_stop_the_sweep_and_its_reason_is_saved(run_sweep):
    outcomes = {"MUM-001": "ok", "MUM-002": "fetch_failed", "MUM-003": "ok"}
    conn, exit_code = run_sweep(make_roster(3), lambda store_id: outcomes[store_id])
    assert run_sweep.fetched == ["MUM-001", "MUM-002", "MUM-003"]       # the store after the failure was still tried
    assert exit_code == 0
    assert states(conn)["MUM-002"][:2] == ("incomplete", "fetch_failed")
    assert states(conn)["MUM-001"][0] == states(conn)["MUM-003"][0] == "complete"
    reason = conn.execute("SELECT reason_text FROM store_sweeps WHERE store_id = 'MUM-002'").fetchone()[0]
    assert reason                                                       # a message is kept, not left empty


def test_sweep_with_no_complete_store_exits_with_code_1(run_sweep):
    _, exit_code = run_sweep(make_roster(2), lambda store_id: "partial")
    assert exit_code == 1


def test_roster_that_cannot_be_read_stops_the_sweep(monkeypatch):
    monkeypatch.setattr(sweep, "get_json", lambda path, params, counts: (None, "HTTP 503 on every attempt"))
    with pytest.raises(SystemExit) as stop:
        sweep.get_roster()
    assert "could not read the store list" in str(stop.value)
