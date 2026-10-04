"""
review_me.py: written by an AI coding assistant in one shot and merged without review.

Your job (write it in REVIEW.md):
  1. Find at least 5 real problems, most serious first. For each, say what goes wrong,
     with a concrete example (not just "bad practice").
  2. Fix the 2-3 most serious ones in this file.
Don't rewrite it from scratch. Reviewing is the skill being tested.
"""
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import requests

PORTAL = "http://127.0.0.1:8765"
HEADERS = {"X-Api-Key": "dfhire-2026"}
IST = timezone(timedelta(hours=5, minutes=30))

MAX_ATTEMPTS = 6            # per request
BAN_WAITS = [25, 65, 65]    # seconds to wait after each soft-ban, then start the store again


class SoftBanned(Exception):
    pass


def fetch_inventory(store_id, as_of, cursor="0", results=None):
    """Fetch every inventory page for a store. Gives up with an error rather than retrying forever."""
    if results is None:                 # a default of [] would be shared by every call
        results = []
    wait = 1
    for _ in range(MAX_ATTEMPTS):
        time.sleep(0.5)                 # about 2 requests per second
        try:
            r = requests.get(
                f"{PORTAL}/v1/stores/{store_id}/inventory",
                params={"as_of": as_of, "cursor": cursor},
                headers=HEADERS,
                timeout=5,
            )
        except requests.RequestException:
            r = None
        if r is not None and r.status_code == 200:
            break
        if r is not None and r.status_code in (400, 401, 404):
            raise RuntimeError(f"{store_id}: HTTP {r.status_code}, not retrying: {r.text[:100]}")
        if r is not None and r.status_code == 429:
            time.sleep(float(r.headers.get("Retry-After", 2)))
        else:
            time.sleep(wait)
            wait = min(wait * 2, 8)
    else:
        raise RuntimeError(f"{store_id}: gave up after {MAX_ATTEMPTS} attempts")

    body = r.json()
    if body.get("meta", {}).get("source") != "origin":
        raise SoftBanned(store_id)
    if body.get("partial"):
        raise RuntimeError(f"{store_id}: the portal returned a partial snapshot")
    results.extend(body["items"])
    if body["next_cursor"]:
        return fetch_inventory(store_id, as_of, body["next_cursor"], results)
    return results


def fetch_store(store_id, as_of):
    """fetch_inventory, waiting out a soft-ban and starting the store again from page 1."""
    for wait in BAN_WAITS:
        try:
            return fetch_inventory(store_id, as_of)
        except SoftBanned:
            time.sleep(wait)
    return fetch_inventory(store_id, as_of)     # raises SoftBanned if it is still banned


def save(conn, store_id, items):
    for it in items:
        conn.execute(
            f"INSERT INTO inventory VALUES ('{store_id}', '{it['sku_id']}', '{it['name']}', "
            f"{int(it['in_stock'])}, {it['qty']}, '{it['observed_at']}')"
        )
    conn.commit()


def city_osa(conn, city, day=None):
    """On-shelf availability for a city on a day. Defaults to yesterday in India."""
    day = day or (datetime.now(IST).date() - timedelta(days=1)).isoformat()
    stores = [r[0] for r in conn.execute(
        "SELECT store_id FROM stores WHERE city = ?", (city,))]
    in_stock_total = 0
    seen_total = 0
    for s in stores:
        rows = conn.execute(
            "SELECT in_stock FROM inventory WHERE store_id = ? AND substr(observed_at, 1, 10) = ?",
            (s, day),
        ).fetchall()
        in_stock_total += sum(1 for (flag,) in rows if flag)
        seen_total += len(rows)
    if seen_total == 0:
        return None                 # no data is not 0%, and there is nothing to divide by
    return round(100 * in_stock_total / seen_total, 2)


if __name__ == "__main__":
    conn = sqlite3.connect("review_me.db")   # not osa.db, which belongs to the real project
    conn.execute("CREATE TABLE IF NOT EXISTS stores (store_id TEXT, city TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS inventory (store_id TEXT, sku_id TEXT, name TEXT, "
                 "in_stock INT, qty INT, observed_at TEXT)")
    for sid in ["MUM-001", "MUM-002"]:
        save(conn, sid, fetch_store(sid, datetime.now(timezone.utc).isoformat()))
    print(city_osa(conn, "Mumbai"))
