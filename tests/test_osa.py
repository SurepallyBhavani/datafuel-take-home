"""Tests for the /osa numbers. They use a small throwaway database, never the portal or osa.db."""
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import app as osa_app  # noqa: E402
import db  # noqa: E402

DAY = "2026-09-28"
SWEEP = "2026-09-28T04:30:00Z"


@pytest.fixture
def conn(tmp_path):
    conn = db.connect(str(tmp_path / "test.db"))
    db.create_tables(conn)
    return conn


def add_sweep(conn, as_of, ist_date):
    conn.execute("INSERT OR IGNORE INTO sweeps (as_of, ist_date) VALUES (?, ?)", (as_of, ist_date))


def add_store_sweep(conn, store_id, items=None, as_of=SWEEP, ist_date=DAY, city="Mumbai",
                    active=1, serviceable=1, status="complete", reason_code=None, reason_text=None):
    """items is a list of (sku_id, name, in_stock, qty). Rows are only saved for complete store-sweeps."""
    add_sweep(conn, as_of, ist_date)
    conn.execute("INSERT OR IGNORE INTO stores (store_id, city, name) VALUES (?, ?, ?)", (store_id, city, store_id))
    items = items or []
    count = len(items) if status == "complete" else None
    conn.execute("INSERT INTO store_sweeps (as_of, store_id, is_active, is_serviceable, status, reason_code, "
                 "reason_text, item_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 (as_of, store_id, active, serviceable, status, reason_code, reason_text, count))
    for sku_id, name, in_stock, qty in items:
        conn.execute("INSERT INTO observations (as_of, store_id, sku_id, name, in_stock, qty, price) "
                     "VALUES (?, ?, ?, ?, ?, ?, 10.0)", (as_of, store_id, sku_id, name, in_stock, qty))
    conn.commit()


def test_bad_city_and_bad_date_are_400():
    client = osa_app.app.test_client()
    for url in ["/osa?city=Chennai", "/osa?city=mumbai", "/osa", "/osa?city=Mumbai&date=28-09-2026",
                "/osa?city=Mumbai&date=2026-9-8"]:
        response = client.get(url)
        assert response.status_code == 400, url
        assert "error" in response.get_json()


def test_day_with_no_sweeps_is_no_data_not_zero(conn):
    report = osa_app.build_report(conn, "Mumbai", DAY)
    assert report["status"] == "no_data"
    assert report["osa_pct"] is None
    assert report["observations"] == 0
    assert report["skus"] == []


def test_incomplete_store_is_listed_and_not_counted_as_out_of_stock(conn):
    add_store_sweep(conn, "MUM-001", [("SKU-1", "Milk", 1, 5)])
    add_store_sweep(conn, "MUM-002", status="incomplete", reason_code="partial", reason_text="portal said partial")
    report = osa_app.build_report(conn, "Mumbai", DAY)
    assert report["osa_pct"] == 100.0                       # not 50
    assert report["status"] == "partial"
    assert report["coverage"]["stores_expected"] == 2
    assert report["coverage"]["stores_complete"] == 1
    assert report["coverage"]["incomplete"] == [{"store_id": "MUM-002", "sweep": SWEEP,
                                                 "reason_code": "partial", "reason": "portal said partial"}]


def test_total_is_pooled_not_an_average_of_percentages(conn):
    add_store_sweep(conn, "MUM-001", [("SKU-1", "Milk", 1, 5), ("SKU-2", "Bread", 1, 5)])            # 2 of 2
    add_store_sweep(conn, "MUM-002", [("SKU-%d" % i, "Item", 0, 0) for i in range(3, 11)])           # 0 of 8
    report = osa_app.build_report(conn, "Mumbai", DAY)
    assert report["observations"] == 10
    assert report["osa_pct"] == 20.0                        # an average of 100 and 0 would say 50


def test_ghost_stock_counts_as_in_stock(conn):
    add_store_sweep(conn, "MUM-001", [("SKU-1", "Milk", 1, 0)])    # in_stock true but qty 0
    assert osa_app.build_report(conn, "Mumbai", DAY)["osa_pct"] == 100.0


def test_a_real_zero_percent_is_not_no_data(conn):
    add_store_sweep(conn, "MUM-001", [("SKU-1", "Milk", 0, 0), ("SKU-2", "Bread", 0, 0)])
    report = osa_app.build_report(conn, "Mumbai", DAY)
    assert report["osa_pct"] == 0.0
    assert report["observations"] == 2
    assert report["status"] == "ok"


def test_stores_that_do_not_qualify_are_excluded_and_listed(conn):
    add_store_sweep(conn, "MUM-001", [("SKU-1", "Milk", 1, 5)])
    add_store_sweep(conn, "MUM-002", [("SKU-1", "Milk", 0, 0)], serviceable=0)   # active, not serviceable
    add_store_sweep(conn, "MUM-003", active=0, serviceable=1, status="skipped", reason_code="inactive")
    report = osa_app.build_report(conn, "Mumbai", DAY)
    assert report["osa_pct"] == 100.0                       # MUM-002's stock is left out
    assert report["status"] == "ok"                         # excluded stores are the rule working
    excluded = {(e["store_id"], e["reason_code"]) for e in report["coverage"]["excluded"]}
    assert excluded == {("MUM-002", "not_serviceable"), ("MUM-003", "inactive")}
    assert report["coverage"]["stores_expected"] == 1


def test_a_sweep_belongs_to_the_day_stored_for_it(conn):
    # the 19:00Z sweep on 27 Sep is already 28 Sep in India, so its rows count for the 28th only
    add_store_sweep(conn, "MUM-001", [("SKU-1", "Milk", 1, 5)], as_of="2026-09-27T19:00:00Z", ist_date="2026-09-28")
    assert osa_app.build_report(conn, "Mumbai", "2026-09-28")["observations"] == 1
    assert osa_app.build_report(conn, "Mumbai", "2026-09-27")["status"] == "no_data"


def test_renamed_sku_appears_once_with_the_latest_name(conn):
    add_store_sweep(conn, "MUM-001", [("SKU-0001", "Milk 500ml", 1, 5)], as_of="2026-09-27T19:00:00Z")
    add_store_sweep(conn, "MUM-001", [("SKU-0001", "Milk 500 ml Pouch", 0, 0)], as_of=SWEEP)
    report = osa_app.build_report(conn, "Mumbai", DAY)
    assert len(report["skus"]) == 1
    assert report["skus"][0]["name"] == "Milk 500 ml Pouch"
    assert report["skus"][0]["observations"] == 2
    assert report["skus"][0]["osa_pct"] == 50.0


def test_only_the_requested_city_is_counted(conn):
    add_store_sweep(conn, "MUM-001", [("SKU-1", "Milk", 1, 5)])
    add_store_sweep(conn, "DEL-001", [("SKU-1", "Milk", 0, 0)], city="Delhi")
    assert osa_app.build_report(conn, "Mumbai", DAY)["osa_pct"] == 100.0
    assert osa_app.build_report(conn, "Delhi", DAY)["osa_pct"] == 0.0


def test_percent_rounds_half_up():
    assert osa_app.percent(1, 800) == 0.13                  # 0.125 exactly; float rounding would give 0.12
    assert osa_app.percent(2, 3) == 66.67
    assert osa_app.percent(0, 0) is None


def test_default_date_is_yesterday_in_india():
    # 20:00 UTC on 3 Oct is 01:30 on 4 Oct in India, so yesterday there is 3 Oct
    now = datetime(2026, 10, 3, 20, 0, tzinfo=timezone.utc)
    assert osa_app.yesterday_in_ist(now) == "2026-10-03"


def test_store_with_no_products_adds_no_rows_and_is_listed(conn):
    add_store_sweep(conn, "MUM-001", [])                                    # complete, zero items
    add_store_sweep(conn, "MUM-002", [("SKU-1", "Milk", 1, 5)])
    report = osa_app.build_report(conn, "Mumbai", DAY)
    assert report["osa_pct"] == 100.0
    assert report["observations"] == 1
    assert report["coverage"]["no_products"] == [{"store_id": "MUM-001", "sweep": SWEEP}]
    assert report["coverage"]["stores_complete"] == 2


def test_day_where_only_empty_stores_were_seen_is_no_data(conn):
    add_store_sweep(conn, "MUM-001", [])
    report = osa_app.build_report(conn, "Mumbai", DAY)
    assert report["status"] == "no_data"
    assert report["osa_pct"] is None


def test_store_that_was_never_fetched_is_listed_as_not_attempted(conn):
    add_store_sweep(conn, "MUM-001", [("SKU-1", "Milk", 1, 5)])
    add_store_sweep(conn, "MUM-002", status="pending")
    report = osa_app.build_report(conn, "Mumbai", DAY)
    assert report["status"] == "partial"
    assert [(e["store_id"], e["reason_code"]) for e in report["coverage"]["incomplete"]] == [("MUM-002", "not_attempted")]


def test_day_where_every_qualifying_store_is_incomplete_is_no_data_with_coverage(conn):
    add_store_sweep(conn, "MUM-001", status="incomplete", reason_code="soft_banned", reason_text="still banned")
    add_store_sweep(conn, "MUM-002", status="pending")
    report = osa_app.build_report(conn, "Mumbai", DAY)
    assert report["status"] == "no_data"
    assert report["osa_pct"] is None
    assert report["coverage"]["stores_expected"] == 2
    assert report["coverage"]["stores_complete"] == 0
    assert len(report["coverage"]["incomplete"]) == 2


def test_store_that_qualifies_in_only_one_sweep_of_the_day(conn):
    early = "2026-09-27T19:00:00Z"
    add_store_sweep(conn, "MUM-001", [("SKU-1", "Milk", 1, 5)], as_of=early)
    add_store_sweep(conn, "MUM-001", [("SKU-1", "Milk", 0, 0)], as_of=SWEEP, serviceable=0)   # flag changed
    report = osa_app.build_report(conn, "Mumbai", DAY)
    assert report["osa_pct"] == 100.0                       # only the first sweep counts
    assert report["observations"] == 1
    assert report["coverage"]["stores_expected"] == 1
    assert report["coverage"]["stores_complete"] == 1
    assert [(e["sweep"], e["reason_code"]) for e in report["coverage"]["excluded"]] == [(SWEEP, "not_serviceable")]


def test_store_incomplete_in_one_sweep_is_not_counted_as_complete_for_the_day(conn):
    add_store_sweep(conn, "MUM-001", [("SKU-1", "Milk", 1, 5)], as_of="2026-09-27T19:00:00Z")
    add_store_sweep(conn, "MUM-001", as_of=SWEEP, status="incomplete", reason_code="partial", reason_text="partial")
    report = osa_app.build_report(conn, "Mumbai", DAY)
    assert report["coverage"]["stores_expected"] == 1
    assert report["coverage"]["stores_complete"] == 0
    assert report["observations"] == 1


def test_osa_route_returns_the_report_as_json(conn, monkeypatch):
    add_store_sweep(conn, "MUM-001", [("SKU-1", "Milk", 1, 5), ("SKU-2", "Bread", 0, 0)])
    monkeypatch.setattr(osa_app.db, "connect", lambda: conn)
    response = osa_app.app.test_client().get("/osa?city=Mumbai&date=2026-09-28")
    assert response.status_code == 200
    body = response.get_json()
    assert (body["city"], body["date"], body["status"]) == ("Mumbai", DAY, "ok")
    assert body["osa_pct"] == 50.0 and body["observations"] == 2
    assert [s["sku_id"] for s in body["skus"]] == ["SKU-1", "SKU-2"]
