"""Fetch one sweep of inventory from the QuickMart portal into osa.db.

Usage:  python sweep.py --as-of 2026-09-28T04:30:00Z
"""
import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

import db

PORTAL = os.environ.get("PORTAL_URL", "http://127.0.0.1:8765")
HEADERS = {"X-Api-Key": "dfhire-2026"}
IST = timezone(timedelta(hours=5, minutes=30))

TIMEOUT = 5          # seconds; the slow replies take 8
MAX_ATTEMPTS = 6     # per request
GAP = 0.5            # seconds between requests, about 2 per second
MAX_RETRY_AFTER = 60 # never wait longer than this because of one Retry-After header
MAX_PAGES = 50       # safety limit so a broken cursor cannot loop forever
BAN_WAITS = [25, 65, 65]   # seconds to wait after each soft-ban; also the number of recoveries
MAX_BANNED_IN_A_ROW = 3    # stop the sweep when this many stores in a row stay soft-banned

SWEEP_TIMES = [
    "2026-09-27T04:30:00Z", "2026-09-27T10:30:00Z", "2026-09-27T19:00:00Z",
    "2026-09-28T04:30:00Z", "2026-09-28T10:30:00Z", "2026-09-28T18:40:00Z",
]

last_request = 0.0


def parse_time(text):
    """Read an ISO time, require a timezone, return it in UTC."""
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))  # Python 3.10 can't read a bare Z
    if dt.tzinfo is None:
        raise ValueError("timestamp has no timezone: " + text)
    return dt.astimezone(timezone.utc)


def utc_text(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_json(path, params, counts):
    """GET with a timeout, pacing and limited retries. Returns (body, None) or (None, error text)."""
    global last_request
    error = "no attempt made"
    wait = 1
    for _ in range(MAX_ATTEMPTS):
        pause = last_request + GAP - time.monotonic()
        if pause > 0:
            time.sleep(pause)
        last_request = time.monotonic()
        counts["attempts"] += 1

        try:
            r = requests.get(PORTAL + path, params=params, headers=HEADERS, timeout=TIMEOUT)
        except requests.RequestException as e:
            error = "network error: " + type(e).__name__
        else:
            if r.status_code == 200:
                try:
                    return r.json(), None
                except ValueError:
                    error = "reply was not JSON"
            elif r.status_code == 429:
                error = "HTTP 429"
                try:
                    pause = float(r.headers.get("Retry-After", 2))
                except ValueError:
                    pause = 2
                time.sleep(min(max(pause, 0), MAX_RETRY_AFTER))
                continue
            elif r.status_code in (400, 401, 404):
                return None, "HTTP %d: %s" % (r.status_code, r.text[:100])   # retrying cannot help
            else:
                error = "HTTP %d" % r.status_code

        time.sleep(wait)
        wait = min(wait * 2, 8)

    return None, "gave up after %d attempts, last error: %s" % (MAX_ATTEMPTS, error)


def get_roster():
    """Read every page of the store list. Stops the program if any page cannot be read."""
    counts = {"attempts": 0}
    stores = []
    page = 1
    while page:
        body, error = get_json("/v1/stores", {"page": page}, counts)
        if body is None:
            sys.exit("could not read the store list (page %d): %s" % (page, error))
        stores += body["stores"]
        page = body["next_page"]
    return stores


def fetch_all_pages(store_id, as_of_text, counts):
    """Read every inventory page of one store.
    Returns (items, None, None) if all is well, or (None, reason_code, reason_text)."""
    items_by_sku = {}
    cursor = "0"
    for _ in range(MAX_PAGES):
        body, error = get_json("/v1/stores/%s/inventory" % store_id,
                               {"as_of": as_of_text, "cursor": cursor}, counts)
        if body is None:
            return None, "fetch_failed", error

        source = body.get("meta", {}).get("source")
        if source != "origin":
            return None, "soft_banned", "meta.source was %r" % source
        if body.get("partial"):
            return None, "partial", "portal returned partial: true"
        if body.get("store_id") != store_id:
            return None, "fetch_failed", "reply was for store %r" % body.get("store_id")

        for item in body["items"]:
            sku = item["sku_id"]
            if sku not in items_by_sku:
                items_by_sku[sku] = item
            elif items_by_sku[sku] != item:
                return None, "conflicting_duplicate", "%s appeared twice with different values" % sku

        cursor = body["next_cursor"]
        if cursor is None:
            return list(items_by_sku.values()), None, None

    return None, "fetch_failed", "more than %d pages" % MAX_PAGES


def fetch_store(store_id, as_of_text):
    """Fetch one store, waiting out a soft-ban and starting the store again from page 1."""
    counts = {"attempts": 0}
    ban_recoveries = 0
    while True:
        items, code, text = fetch_all_pages(store_id, as_of_text, counts)
        if code != "soft_banned":
            break
        if ban_recoveries == len(BAN_WAITS):
            text += " (still banned after %d recoveries)" % ban_recoveries
            break
        wait = BAN_WAITS[ban_recoveries]
        print("  %s: soft-ban seen (%s), waiting %ds" % (store_id, text, wait), flush=True)
        time.sleep(wait)
        ban_recoveries += 1
    return {"items": items, "code": code, "text": text,
            "attempts": counts["attempts"], "ban_recoveries": ban_recoveries}


def prepare_sweep(conn, as_of_text, as_of, roster):
    """Save the sweep, the stores and this run's flags. Complete store-sweeps are left as they are."""
    with conn:
        conn.execute("INSERT OR IGNORE INTO sweeps (as_of, ist_date) VALUES (?, ?)",
                     (as_of_text, as_of.astimezone(IST).date().isoformat()))
        for s in roster:
            conn.execute(
                "INSERT INTO stores (store_id, city, name) VALUES (?, ?, ?) "
                "ON CONFLICT (store_id) DO UPDATE SET city = excluded.city, name = excluded.name",
                (s["store_id"], s["city"], s["name"]))
            conn.execute(
                "INSERT INTO store_sweeps (as_of, store_id, is_active, is_serviceable, status) "
                "VALUES (?, ?, ?, ?, 'pending') "
                "ON CONFLICT (as_of, store_id) DO UPDATE SET "
                "  is_active = excluded.is_active, is_serviceable = excluded.is_serviceable, "
                "  status = 'pending', reason_code = NULL, reason_text = NULL, item_count = NULL "
                "WHERE store_sweeps.status != 'complete'",
                (as_of_text, s["store_id"], int(s["is_active"]), int(s["is_serviceable"])))
        conn.execute(
            "UPDATE store_sweeps SET status = 'skipped', reason_code = 'inactive', "
            "reason_text = 'is_active is false in the roster' "
            "WHERE as_of = ? AND is_active = 0 AND status != 'complete'", (as_of_text,))


def save_store(conn, as_of_text, store_id, result):
    """Save one store in one transaction: its rows and its status, or nothing."""
    items = result["items"]
    now = utc_text(datetime.now(timezone.utc))
    with conn:
        conn.execute("DELETE FROM observations WHERE as_of = ? AND store_id = ?", (as_of_text, store_id))
        if items is None:
            status, count = "incomplete", None
        else:
            status, count = "complete", len(items)
            for item in items:
                conn.execute(
                    "INSERT INTO observations (as_of, store_id, sku_id, name, in_stock, qty, price, observed_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (as_of_text, store_id, item["sku_id"], item["name"], 1 if item["in_stock"] else 0,
                     item["qty"], float(item["price"]), utc_text(parse_time(item["observed_at"]))))
        conn.execute(
            "UPDATE store_sweeps SET status = ?, reason_code = ?, reason_text = ?, item_count = ?, "
            "attempts = ?, ban_recoveries = ?, fetched_at = ? WHERE as_of = ? AND store_id = ?",
            (status, result["code"], result["text"], count, result["attempts"],
             result["ban_recoveries"], now, as_of_text, store_id))


def print_summary(conn, as_of_text, seconds):
    rows = conn.execute("SELECT store_id, status, reason_code, reason_text FROM store_sweeps "
                        "WHERE as_of = ? ORDER BY store_id", (as_of_text,)).fetchall()
    complete = [r for r in rows if r["status"] == "complete"]
    skipped = [r for r in rows if r["status"] == "skipped"]
    incomplete = [r for r in rows if r["status"] == "incomplete"]
    not_fetched = [r for r in rows if r["status"] == "pending"]

    line = "%d active stores: %d complete, %d incomplete" % (
        len(complete) + len(incomplete) + len(not_fetched), len(complete), len(incomplete))
    if incomplete:
        details = ["%s: %s (%s)" % (r["store_id"], r["reason_code"], r["reason_text"]) for r in incomplete]
        line += " [" + "; ".join(details) + "]"
    if not_fetched:
        line += ", %d not fetched" % len(not_fetched)
    line += " | %d inactive skipped | %dm%02ds" % (len(skipped), seconds // 60, seconds % 60)
    print(line)
    return len(complete)


def main():
    parser = argparse.ArgumentParser(description="Fetch one sweep from the QuickMart portal.")
    parser.add_argument("--as-of", required=True, help="UTC time with timezone, e.g. 2026-09-28T04:30:00Z")
    args = parser.parse_args()

    try:
        as_of = parse_time(args.as_of)
    except ValueError as e:
        sys.exit("bad --as-of: %s" % e)
    as_of_text = utc_text(as_of)
    if as_of_text not in SWEEP_TIMES:
        print("warning: %s is not one of the six sweep times" % as_of_text)

    started = time.monotonic()
    run_started = utc_text(datetime.now(timezone.utc))
    conn = db.connect()
    db.create_tables(conn)

    roster = get_roster()
    prepare_sweep(conn, as_of_text, as_of, roster)

    todo = conn.execute("SELECT store_id FROM store_sweeps WHERE as_of = ? AND status = 'pending' "
                        "ORDER BY store_id", (as_of_text,)).fetchall()

    # started_at and finished_at describe the latest run that fetched something.
    # A run with nothing to fetch leaves both as they were.
    if todo:
        with conn:
            conn.execute("UPDATE sweeps SET started_at = ?, finished_at = NULL WHERE as_of = ?",
                         (run_started, as_of_text))

    banned_in_a_row = 0
    stopped_early = False
    for row in todo:
        store_id = row["store_id"]
        try:
            result = fetch_store(store_id, as_of_text)
        except Exception as e:
            result = {"items": None, "code": "fetch_failed", "text": "unexpected error: " + repr(e),
                      "attempts": 0, "ban_recoveries": 0}
        save_store(conn, as_of_text, store_id, result)
        if result["items"] is None:
            print("%s: incomplete - %s: %s" % (store_id, result["code"], result["text"]), flush=True)
        else:
            print("%s: complete, %d items, %d requests" % (store_id, len(result["items"]), result["attempts"]),
                  flush=True)

        # a store that ends any other way means the ban is over, so the count starts again
        if result["code"] == "soft_banned":
            banned_in_a_row += 1
        else:
            banned_in_a_row = 0
        if banned_in_a_row == MAX_BANNED_IN_A_ROW:
            stopped_early = True
            break

    if stopped_early:
        with conn:
            conn.execute("UPDATE store_sweeps SET reason_code = 'not_attempted', reason_text = ? "
                         "WHERE as_of = ? AND status = 'pending'",
                         ("sweep stopped after %d stores in a row stayed soft-banned" % MAX_BANNED_IN_A_ROW,
                          as_of_text))

    if todo:
        with conn:
            conn.execute("UPDATE sweeps SET finished_at = ? WHERE as_of = ?",
                         (utc_text(datetime.now(timezone.utc)), as_of_text))
    seconds = int(time.monotonic() - started)
    completed = print_summary(conn, as_of_text, seconds)
    if stopped_early:
        print("stopped early: %d stores in a row stayed soft-banned. Run the same command later to fetch the rest."
              % MAX_BANNED_IN_A_ROW)
        sys.exit(1)
    if completed == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
