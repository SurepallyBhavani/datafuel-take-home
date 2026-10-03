"""The /osa report API. It reads osa.db only; it never calls the portal.

Run from this folder:  flask --app app run
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, jsonify, request

import db

app = Flask(__name__)
app.json.sort_keys = False

CITIES = ["Mumbai", "Delhi", "Bengaluru"]
IST = timezone(timedelta(hours=5, minutes=30))

REASON_TEXT = {
    "inactive": "store is inactive in the roster",
    "not_serviceable": "store is not serviceable in the roster",
    "not_attempted": "store was not fetched in this sweep",
}


def yesterday_in_ist(now=None):
    now = now or datetime.now(timezone.utc)
    return (now.astimezone(IST).date() - timedelta(days=1)).isoformat()


def percent(part, whole):
    """part as a percent of whole, 2 decimals, rounded half up. None if there is nothing to divide by."""
    if whole == 0:
        return None
    value = Decimal(part) * 100 / Decimal(whole)
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def build_report(conn, city, day):
    sweeps = [r["as_of"] for r in conn.execute(
        "SELECT as_of FROM sweeps WHERE ist_date = ? ORDER BY as_of", (day,))]

    # every store of this city in every sweep of this IST day
    store_sweeps = conn.execute(
        "SELECT ss.as_of, ss.store_id, ss.is_active, ss.is_serviceable, ss.status, "
        "       ss.reason_code, ss.reason_text, ss.item_count "
        "FROM store_sweeps ss "
        "JOIN sweeps sw ON sw.as_of = ss.as_of "
        "JOIN stores st ON st.store_id = ss.store_id "
        "WHERE sw.ist_date = ? AND st.city = ? "
        "ORDER BY ss.as_of, ss.store_id", (day, city)).fetchall()

    counted = []        # (as_of, store_id) of the store-sweeps whose rows we use
    incomplete = []
    excluded = []
    no_products = []
    statuses = {}       # store_id -> status in each sweep where the store qualified
    per_sweep = {as_of: {"sweep": as_of, "stores_counted": 0, "observations": 0} for as_of in sweeps}

    for r in store_sweeps:
        if not r["is_active"] or not r["is_serviceable"]:
            code = "inactive" if not r["is_active"] else "not_serviceable"
            excluded.append({"store_id": r["store_id"], "sweep": r["as_of"],
                             "reason_code": code, "reason": REASON_TEXT[code]})
            continue

        statuses.setdefault(r["store_id"], []).append(r["status"])
        if r["status"] == "complete":
            counted.append((r["as_of"], r["store_id"]))
            if r["item_count"] == 0:
                no_products.append({"store_id": r["store_id"], "sweep": r["as_of"]})
        else:
            code = r["reason_code"] or "not_attempted"
            incomplete.append({"store_id": r["store_id"], "sweep": r["as_of"], "reason_code": code,
                               "reason": r["reason_text"] or REASON_TEXT["not_attempted"]})

    # add up the rows of the counted store-sweeps, oldest sweep first so the latest name wins
    skus = {}
    for as_of, store_id in counted:
        rows = conn.execute("SELECT sku_id, name, in_stock FROM observations WHERE as_of = ? AND store_id = ?",
                            (as_of, store_id)).fetchall()
        for row in rows:
            sku = skus.setdefault(row["sku_id"], {"name": row["name"], "observations": 0, "in_stock": 0})
            sku["name"] = row["name"]
            sku["observations"] += 1
            sku["in_stock"] += row["in_stock"]
        per_sweep[as_of]["stores_counted"] += 1
        per_sweep[as_of]["observations"] += len(rows)

    total_observations = sum(s["observations"] for s in skus.values())
    total_in_stock = sum(s["in_stock"] for s in skus.values())

    if total_observations == 0:
        status = "no_data"
    elif incomplete:
        status = "partial"
    else:
        status = "ok"

    return {
        "city": city,
        "date": day,
        "status": status,
        "osa_pct": percent(total_in_stock, total_observations),
        "observations": total_observations,
        "in_stock": total_in_stock,
        "coverage": {
            "stores_expected": len(statuses),
            "stores_complete": sum(1 for s in statuses.values() if all(x == "complete" for x in s)),
            "incomplete": incomplete,
            "excluded": excluded,
            "no_products": no_products,
            "sweeps": list(per_sweep.values()),
        },
        "skus": [{"sku_id": sku_id, "name": s["name"], "observations": s["observations"],
                  "in_stock": s["in_stock"], "osa_pct": percent(s["in_stock"], s["observations"])}
                 for sku_id, s in sorted(skus.items())],
    }


@app.route("/osa")
def osa():
    city = request.args.get("city")
    if city not in CITIES:
        return jsonify(error="city must be one of: " + ", ".join(CITIES)), 400

    day = request.args.get("date")
    if day is None:
        day = yesterday_in_ist()
    else:
        try:
            valid = datetime.strptime(day, "%Y-%m-%d").date().isoformat() == day
        except ValueError:
            valid = False
        if not valid:
            return jsonify(error="date must be written as YYYY-MM-DD"), 400

    conn = db.connect()
    try:
        return jsonify(build_report(conn, city, day))
    finally:
        conn.close()
