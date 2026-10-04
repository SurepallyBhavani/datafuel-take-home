"""The sweep command line: a bad --as-of is refused before anything is fetched, and spellings of a time are one sweep."""
import sys

import pytest

import sweep
from conftest import make_roster


def run_main(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["sweep.py", *args])
    sweep.main()


@pytest.fixture
def nothing_is_fetched(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sweep, "get_roster", lambda: pytest.fail("the portal should not be asked anything"))


def test_as_of_without_a_timezone_is_refused_with_a_message(monkeypatch, nothing_is_fetched):
    with pytest.raises(SystemExit) as stop:
        run_main(monkeypatch, "--as-of", "2026-09-28T04:30:00")
    assert "bad --as-of" in str(stop.value) and "no timezone" in str(stop.value)


def test_as_of_that_is_not_a_time_is_refused_with_a_message(monkeypatch, nothing_is_fetched):
    with pytest.raises(SystemExit) as stop:
        run_main(monkeypatch, "--as-of", "yesterday")
    assert "bad --as-of" in str(stop.value)


def test_missing_as_of_is_refused_by_the_parser(monkeypatch, nothing_is_fetched):
    with pytest.raises(SystemExit) as stop:
        run_main(monkeypatch)
    assert stop.value.code == 2


def test_a_time_that_is_not_a_sweep_time_gives_a_warning_but_still_runs(run_sweep, capsys):
    _, exit_code = run_sweep(make_roster(1), lambda store_id: "ok", as_of="2026-09-28T05:00:00Z")
    assert "not one of the six sweep times" in capsys.readouterr().out
    assert exit_code == 0


def test_india_time_and_utc_spellings_are_the_same_sweep(run_sweep):
    conn, _ = run_sweep(make_roster(2), lambda store_id: "ok", as_of="2026-09-28T10:00:00+05:30")
    assert [r[0] for r in conn.execute("SELECT as_of FROM sweeps")] == ["2026-09-28T04:30:00Z"]

    conn, _ = run_sweep(make_roster(2), lambda store_id: "ok", as_of="2026-09-28T04:30:00Z")
    assert run_sweep.fetched == []                           # already complete, so nothing is fetched again
    assert [r[0] for r in conn.execute("SELECT as_of FROM sweeps")] == ["2026-09-28T04:30:00Z"]


def test_summary_line_names_incomplete_stores_and_their_reasons(run_sweep, capsys):
    run_sweep(make_roster(3), lambda store_id: "partial" if store_id == "MUM-002" else "ok")
    summary = capsys.readouterr().out.strip().splitlines()[-1]
    assert summary.startswith("3 active stores: 2 complete, 1 incomplete")
    assert "MUM-002: partial (fake partial)" in summary
