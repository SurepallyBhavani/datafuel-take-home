# NOTES

## 1. What I observed from the portal

Probed on 2026-10-03 against a fresh `mock_portal.py` with two throwaway scripts (not part of the submission).
Unless stated, inventory numbers are from one sweep, `as_of=2026-09-28T04:30:00Z`, over the 26 active stores.

### Stores
- 30 stores in 3 roster pages (12, 12, 6). `next_page` is `null` on the last page. 10 stores per city, and every store ID prefix (MUM, DEL, BLR) matches its city. No other city appears.
- 26 stores have `is_active: true`. The flags disagree on five stores:

| Store | is_active | is_serviceable |
|---|---|---|
| MUM-009 | false | true |
| BLR-004 | false | true |
| DEL-006 | true | false |
| DEL-010 | false | false |
| BLR-010 | false | false |

### Inventory pages
- About 15 items per page. The number of pages varies by store: MUM-001 has 3 pages (15, 15, 3), and 744 rows came from 26 stores (about 29 per store). Cursors are numeric strings, and `next_cursor` is `null` on the last page.
- **Seam duplicates:** 10 of 26 stores had one SKU repeated at the start of page 2 or page 3. Every copy was identical to the first, so keeping the first occurrence is safe.
- **Empty is not one thing.** DEL-004 at `2026-09-28T10:30:00Z` returns 0 items with `partial: true`. BLR-007 at `2026-09-27T04:30:00Z` (before its launch) returns 0 items with `partial: false`. Both say `source: origin`. At other times both stores return normal data.

### Formats
- `observed_at` is `as_of` plus 0 to 20 minutes (seen: 0 to 20), and is the same on every row of one store's sweep.
- Delhi writes `observed_at` in IST (`2026-09-28T10:15:00+05:30`). Mumbai and Bengaluru write UTC with `Z`.
- Bengaluru prices are strings (`'443.00'`); the other cities send numbers.
- `as_of` without a timezone returns HTTP 400 `as_of must include a timezone`. An unencoded `+05:30` returns HTTP 400 `Invalid isoformat string: '2026-09-28T10:00:00 05:30'` (the `+` became a space). `%2B05:30` works.

### Data quirks
- **SKU-0001 is renamed:** `Amul Taaza Toned Milk 500ml` on the 27 Sep sweeps, `Amul Taaza Toned Milk 500 ml Pouch` from the 28 Sep sweeps. The `sku_id` does not change.
- **Ghost stock:** 29 of 624 in-stock rows (4.6%) have `qty: 0`. No out-of-stock row has `qty` above 0. So `qty` cannot be used to decide availability.
- **Out-of-stock share:** Mumbai 13.5%, Delhi 19.8%, Bengaluru 14.8% of listed rows. Out-of-stock rows are still listed.
- **A real 0% did not appear.** In every city, all 36 SKUs had at least one in-stock observation; the lowest was 3 of 5 (60%).

### IST day versus `observed_at`
For the two sweeps nearest the IST midnight line (`2026-09-27T19:00Z` and `2026-09-28T18:40Z`), I checked all 26 stores:
- Converting `observed_at` to IST with the timezone gave the sweep's IST date for 26 of 26 stores.
- Cutting the first 10 characters of `observed_at` gave the right date for only 9 of 26. The 9 are the Delhi stores, because only Delhi writes IST.
- On the other four sweeps (3 stores each), both methods agreed.

### Errors and limits
- **429:** 20 parallel requests gave 8 successes and 12 429s. `Retry-After: 2`.
- **500 on MUM-007:** the first two requests for each new `as_of` return 500 and the third returns 200 (confirmed directly, and seen 6 times in the read-only run across 3 different `as_of` values).
- **503:** 12 in about 170 requests (about 7%). I saw one timeout, from a call that does not retry; that is not enough to estimate the rate of slow responses.

### The soft-ban
45 inventory calls in a tight loop, with no pause and ignoring `Retry-After`:

| Calls | Result |
|---|---|
| 1 to 8 | HTTP 200, `source: origin`, 15 items |
| 9 to 30 | HTTP 429 (22 calls) |
| 31 onwards | HTTP 200, `source: edge` |

- 8 + 22 = 30 attempts passed before the ban, so **429s count towards the ban**. The 31st attempt triggered it.
- `edge` replies had `partial: false` and `next_cursor: null`, with 0 items or 1 to 4 items (never more than a third of a page). About 9 of 15 were empty. Each looks like a small, finished store; only `meta.source` gives it away.
- After the ban started there were no more 429s, so a missing 429 does not mean you are fine.
- After 25 seconds of silence the next call was **still `edge`**, so 25 seconds was not enough here. Every call made during the ban pushes the end of the ban further out, so the 14 extra calls plus the probe itself extended it. Later, with no restart of the portal, it was `origin` again, so it clears on its own after enough silence. I did not measure how long it took.

## 2. Decisions

### 2.1 Which stores to track
**Track a store only if it is both `is_active` and `is_serviceable`.** That is 25 stores: Mumbai 9, Delhi 8, Bengaluru 8.

Why: a store that is not accepting orders cannot sell, so its stock flags do not say whether a customer could buy the product. `is_active` alone is not enough, and `is_serviceable` alone is wrong, because MUM-009 and BLR-004 are decommissioned but marked serviceable.

Left out, and why:

| Store | Reason |
|---|---|
| MUM-009, BLR-004 | inactive (serviceable flag is true) |
| DEL-006 | active but not serviceable |
| DEL-010, BLR-010 | inactive and not serviceable |

Known limitations of this rule:
- The roster has no `as_of`, so the flags are the values at fetch time and are applied to the 27 to 29 Sep sweeps as well. The flag can flip during the day; this is not captured.
- If a flag changes later, OSA for past days can change. `/osa` should state when the flags were read, and the excluded stores are listed in `coverage` with the reason.
- DEL-006's inventory looks normal in the data; only the roster flag marks it as unusable.

### 2.2 Flags are saved per sweep, and a day is totalled by summing
- For every sweep I save each roster store's `is_active` and `is_serviceable` as read in that run, together with the store's fetch status. `/osa` counts a store in a sweep only if the flags saved for that sweep say active and serviceable.
- A sweep's saved flags are not overwritten when a complete store-sweep is run again, so re-running does not change old numbers.
- `/osa` reads only the database; it never calls the portal.
- A day's OSA is the sum of in-stock rows over the sum of rows seen, across all sweeps of that IST day, counting only the stores that qualified in each sweep. It is not an average of percentages. SKU-level percentages are totalled the same way.
- `is_active` is treated like `is_serviceable`: nothing in API.md says a store cannot become inactive during a day.

### 2.3 Coverage gives the exact reason for every store that is left out
`coverage` lists each store and sweep that was not counted, with a reason that states only what was observed (for example: portal returned `partial: true`; soft-ban detected, `source: edge`; HTTP 503 after the retry limit; inactive per roster; not serviceable per roster). It does not guess at causes. Reasons come from a small fixed list of codes, each with a plain-language message.

Known limitations:
- The flags saved for the 27 to 29 Sep sweeps are those read when I ran the sweeps, not the values at the time of the sweep.
- The set of stores can differ between the sweeps of one day, so `coverage` also shows what was counted in each sweep.
- Leaving a store out of one sweep changes the weighting of that day's total slightly.
- The grader's own solution may track all 26 active stores (README's example summary says "26 stores"); this rule would then give slightly different Delhi numbers.

### 2.4 Handling the soft-ban
- **Detect:** every inventory page is checked for `meta.source`. Anything other than `origin` is treated as a soft-ban, even though it is HTTP 200 with `partial: false` (probe: edge replies look like a small, finished store).
- **React:** stop all inventory requests, not just those for that store, because the ban is per API key. Wait about 25 seconds, then try once. If the reply is still `edge`, wait about 65 seconds before the next try, because every request made during a ban pushes its end out by 5 seconds (probe: a call after 25 seconds of silence was still `edge`).
- **Discard the whole store:** if any page of a store is not `origin`, throw away all of that store's pages, including earlier good ones, and fetch it again from the start. Rows are saved only after every page of the store was `origin` with `partial: false`, so nothing needs undoing.
- **Limit:** after a few failed recoveries for one store, mark it incomplete with the reason `soft_banned` so the sweep always finishes.
- **Prevent:** pace requests (target about 2 per second), honour `Retry-After`, and count every attempt, including 429s and 503s, because they all count towards the ban (probe: 8 successes plus 22 429s were followed by the ban at the 31st attempt).
- **Cost:** one ban adds roughly 25 seconds to a sweep of about 30 seconds. This is an estimate, not something I measured.

### 2.5 When a store's sweep is complete
A store-sweep is complete only if all of these hold:
- every page was fetched, ending with `next_cursor: null`;
- every page was HTTP 200 with `meta.source == "origin"` and `partial: false`;
- the `store_id` in the reply is the store that was asked for.

Treatment of each case:

| Case | Status | Reason code |
|---|---|---|
| `partial: true` | not complete; all its items are discarded, even if some came back | `partial` |
| zero items, `partial: false`, source `origin` | complete, with no rows; `coverage` notes "no products listed" | none (it adds no rows) |
| retries used up (503, timeout, ...) | not complete; the reason states what was seen, e.g. "HTTP 503 on 6 of 6 attempts" | `fetch_failed` |
| source is not `origin` | not complete, handled as in 2.4 | `soft_banned` |
| a SKU repeated at a page boundary | complete if the copies are identical; one copy is kept | none |
| a SKU repeated with different values | not complete, because we cannot tell which copy is right | `conflicting_duplicate` |

Rows are saved only for complete store-sweeps. An empty store is told apart from a soft-ban reply only by `meta.source`, so that check always runs first. In the probes, all 10 repeated SKUs were identical to their first copy.

Stores that are active but do not qualify (DEL-006) are still fetched and stored, at a cost of about 2 requests per store per sweep, so that changing the rule later does not need a re-scrape. Inactive stores are not fetched. `coverage` lists every store left out for the requested city, once per sweep, with its reason, including inactive ones.

### 2.6 Which time decides a sweep's IST day
Each sweep belongs to the IST day of its `as_of` (UTC converted to UTC+5:30, using a fixed offset). `observed_at` is kept, converted to UTC, but does not decide the day.

- `as_of` is the time I ask about. It is a request parameter, the same for every store in a sweep, and I record it myself. `observed_at` comes back inside each item and says when the store's snapshot was taken (API.md). It is set by the portal, so I cannot control it.
- Example, sweep `as_of` 04:30Z: MUM-001 `observed_at` 04:37Z (7 min), BLR-001 04:41Z (11 min), DEL-001 `10:15+05:30`, which is 04:45Z (15 min).
- Using `as_of` keeps a sweep whole: every row gets one day, and `coverage` per sweep stays meaningful.

| Sweep (UTC) | IST time | IST day |
|---|---|---|
| 09-27 04:30 | 09-27 10:00 | 27 |
| 09-27 10:30 | 09-27 16:00 | 27 |
| 09-27 19:00 | 09-28 00:30 | 28 |
| 09-28 04:30 | 09-28 10:00 | 28 |
| 09-28 10:30 | 09-28 16:00 | 28 |
| 09-28 18:40 | 09-29 00:10 | 29 |

So 27 Sep has 2 sweeps, 28 Sep has 3 and 29 Sep has 1. In the probe (all 26 stores on the 19:00Z and 18:40Z sweeps), converting `observed_at` to IST properly gave the sweep's date for 26 of 26, but cutting its first 10 characters gave it for only 9 of 26 (the Delhi stores, which already write IST).

### 2.7 Requests, retries and pacing
These numbers are my choices, not measurements.
- One request at a time, at least 0.5 seconds between requests (about 2 per second), including retries. Probes: the ban came on the 31st attempt within a short burst, so staying near 2 per second keeps well under it.
- Timeout 5 seconds, because the slow replies take 8 seconds.
- Up to 6 attempts per request. Wait 1 second, doubling up to 8 seconds. A `Retry-After` header is always honoured. MUM-007 fails twice for each new `as_of`, and random 503s also occur, so a small retry count would lose stores.
- 400, 401 and 404 are not retried, because they cannot succeed.
- Up to 3 soft-ban recoveries per store (see 2.4).

### 2.8 Re-runs and failed sweeps
- A second run of a sweep skips store-sweeps that are already complete and keeps their rows and saved flags. It retries only the others. Running a sweep again therefore does not change the numbers.
- `--as-of` must have a timezone. It is normalised to UTC, so `...04:30:00Z` and `...10:00:00+05:30` are the same sweep.
- The portal returns believable data for any timestamp, so a mistyped `--as-of` would produce fake data. `sweep.py` accepts any timezone-aware time but prints a warning if it is not one of the six sweep times.
- If no store completes in a sweep, the summary is still printed with the reasons and the exit code is non-zero.

### 2.9 How rows are stored
- All times are stored as UTC text. Each sweep also stores its IST date.
- Products are identified by `sku_id`, not by name, because names change (SKU-0001 is renamed from 28 Sep). The name shown in a report is the one from the latest sweep.
- `in_stock` is stored as 0/1 and is the only field used for availability. `qty` is stored for information. `price` is stored as a number (Bengaluru sends a string).
- Unique key: `(as_of, store_id, sku_id)`. The database file is listed in `.gitignore`.
- Timestamps are parsed by replacing `Z` with `+00:00`, because Python 3.10 cannot read a bare `Z`. A timestamp without a timezone is rejected. `as_of` is passed through `requests` parameters so that `+` is encoded.

### 2.10 Behaviour of `/osa`
- `city` must be exactly `Mumbai`, `Delhi` or `Bengaluru`. Anything else, including `mumbai`, returns 400 with the valid values listed.
- `date` must be `YYYY-MM-DD`, otherwise 400. If it is missing, it is yesterday in IST.
- A day with no data returns HTTP 200 with `status: "no_data"`, `osa_pct: null`, `observations: 0`, `skus: []` and `coverage`. Statuses are `ok`, `partial` (something was excluded or incomplete) and `no_data`. A real 0% shows `0.00` with observations above 0.
- Percentages are rounded to 2 decimals, half up, using exact arithmetic. `skus` are sorted by `sku_id`.
- `coverage` lists the sweeps that were used. A sweep that was never run is not in the database, so I make no claim about missing sweeps.
- Stack: Python 3.10, Flask, `requests`, `pytest`, SQLite.

## 3. Short answers
_To be filled in Step 11._
