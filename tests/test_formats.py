"""The portal sends times and prices in different formats. They must be stored in one format."""
from datetime import datetime, timedelta, timezone

import pytest

import sweep
from conftest import AS_OF, roster_store


@pytest.mark.parametrize("text, expected", [
    ("2026-09-28T04:30:00Z", "2026-09-28T04:30:00Z"),            # Mumbai and Bengaluru style
    ("2026-09-28T04:30:00+00:00", "2026-09-28T04:30:00Z"),
    ("2026-09-28T10:00:00+05:30", "2026-09-28T04:30:00Z"),       # Delhi style
    ("2026-09-27T23:59:00-05:00", "2026-09-28T04:59:00Z"),       # an offset behind UTC, across midnight
])
def test_times_in_any_timezone_become_utc_text(text, expected):
    assert sweep.utc_text(sweep.parse_time(text)) == expected


def test_a_time_without_a_timezone_is_rejected():
    with pytest.raises(ValueError):
        sweep.parse_time("2026-09-28T04:30:00")


def test_utc_text_has_one_fixed_format():
    ist = timezone(timedelta(hours=5, minutes=30))
    assert sweep.utc_text(datetime(2026, 9, 28, 10, 15, tzinfo=ist)) == "2026-09-28T04:45:00Z"


def test_saved_rows_use_utc_times_numeric_prices_and_zero_one_flags(tmp_path):
    conn = sweep.db.connect(str(tmp_path / "formats.db"))
    sweep.db.create_tables(conn)
    sweep.prepare_sweep(conn, AS_OF, sweep.parse_time(AS_OF), [roster_store("MUM-001")])
    items = [
        {"sku_id": "SKU-1", "name": "Delhi style", "in_stock": True, "qty": 3, "price": 237.5,
         "observed_at": "2026-09-28T10:15:00+05:30"},
        {"sku_id": "SKU-2", "name": "Bengaluru style", "in_stock": False, "qty": 0, "price": "443.00",
         "observed_at": "2026-09-28T04:41:00Z"},
        {"sku_id": "SKU-3", "name": "Mumbai style, ghost stock", "in_stock": True, "qty": 0, "price": 443.0,
         "observed_at": "2026-09-28T04:37:00Z"},
    ]
    sweep.save_store(conn, AS_OF, "MUM-001",
                     {"items": items, "code": None, "text": None, "attempts": 1, "ban_recoveries": 0})

    rows = conn.execute("SELECT sku_id, observed_at, price, typeof(price), in_stock, typeof(in_stock), qty "
                        "FROM observations ORDER BY sku_id").fetchall()
    assert [tuple(r) for r in rows] == [
        ("SKU-1", "2026-09-28T04:45:00Z", 237.5, "real", 1, "integer", 3),
        ("SKU-2", "2026-09-28T04:41:00Z", 443.0, "real", 0, "integer", 0),
        ("SKU-3", "2026-09-28T04:37:00Z", 443.0, "real", 1, "integer", 0),
    ]


def test_a_row_that_cannot_be_converted_saves_nothing_for_the_store(tmp_path):
    conn = sweep.db.connect(str(tmp_path / "formats.db"))
    sweep.db.create_tables(conn)
    sweep.prepare_sweep(conn, AS_OF, sweep.parse_time(AS_OF), [roster_store("MUM-001")])
    items = [
        {"sku_id": "SKU-1", "name": "Fine", "in_stock": True, "qty": 3, "price": 10.0,
         "observed_at": "2026-09-28T04:37:00Z"},
        {"sku_id": "SKU-2", "name": "Bad price", "in_stock": True, "qty": 3, "price": "free",
         "observed_at": "2026-09-28T04:37:00Z"},
    ]
    with pytest.raises(ValueError):
        sweep.save_store(conn, AS_OF, "MUM-001",
                         {"items": items, "code": None, "text": None, "attempts": 1, "ban_recoveries": 0})
    assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0   # the good row was rolled back too
    assert conn.execute("SELECT status FROM store_sweeps").fetchone()[0] == "pending"
