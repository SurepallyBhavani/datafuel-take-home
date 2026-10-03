# Plan: DataFuel take-home

Tags used below:
- **[DOC]** stated in README.md or API.md
- **[CODE]** read in `mock_portal.py`, not yet verified by running it
- **[GUESS]** my judgment or inference; needs a decision or a check

---

## 1. What you're building and what's tested

You're building three things against a deliberately misbehaving fake quick-commerce server (QuickMart).

- **`sweep.py`** takes an `--as-of` timestamp and fetches every tracked store's full inventory. It stores the rows in SQLite and records per store whether the data was complete and why not. It must be safe to re-run, and it must survive 429s, 5xx errors, slow requests, partial data and the silent soft-ban.
- **`GET /osa?city=&date=`** returns the percentage of observations where a product was in stock. It uses the IST calendar day, includes a `coverage` block, and returns `no_data` instead of 0%.
- **Written parts and tests**: REVIEW.md (reviewing `review_me.py`), NOTES.md, AI_LOG.md, RECORDING.md, and at least 3 pytest tests.

What's really being tested is the rule "a wrong number is worse than no number" [DOC] (README step 2). The grading order is: correct and honest numbers, then scraper robustness (especially the soft-ban), then whether you can explain your choices, then how you use AI, then code cleanliness.

---

## 2. Everything that can produce a wrong number

### 2a. Mentioned in README.md / API.md

| # | Behaviour | How it goes wrong |
|---|---|---|
| A1 | **429 burst limit**, about 8 req/s, with `Retry-After` [DOC] | If you ignore it or skip pages, you get silent gaps. Retrying fast feeds A4. |
| A2 | **Random 500/503** [DOC] | A skipped failure means a missing store or page. |
| A3 | **Slow requests** [DOC] | With no timeout you hang. A timeout that is too short can look like a failure. |
| A4 | **Soft-ban**: HTTP 200 with empty or shortened data and `meta.source: "edge"` [DOC] | The data looks valid but is a fraction of the real inventory. Stored as-is, it produces fake "not listed" or low-count rows. |
| A5 | **`partial: true`** [DOC] | The snapshot is incomplete. Storing it as "no products" or as OOS is wrong. |
| A6 | **Mixed time formats and zones** [DOC] | Delhi uses `+05:30` and the others use `Z`. Cutting the date with `substr(…,1,10)` gives the wrong day. |
| A7 | **`+` in `as_of` must be URL-encoded** [DOC] | An unencoded `+05:30` arrives as a space and the request fails with 400. |
| A8 | **`is_active` vs `is_serviceable`** [DOC] | `is_serviceable` is "right now" and "can flip during the day". The roster has no `as_of`, so you only see today's value, not the value at sweep time. |
| A9 | **Legitimately empty stores** [DOC] | An empty list is not "everything out of stock". |
| A10 | **Pagination**: roster pages plus the inventory cursor [DOC] | A dropped roster page silently loses stores. A dropped inventory page loses SKUs. |
| A11 | **`qty` is informational, use `in_stock`** [DOC] | See B7. |
| A12 | **`observed_at` ≠ `as_of`, and `generated_at` is wall-clock** [DOC] | Don't date a snapshot with `generated_at`. |
| A13 | **UTC sweeps vs the IST day** [DOC] | See the table in section 3, decision 4. |
| A14 | **Default date = yesterday IST** [DOC] | Today is 2026-10-03, so the default is 2026-10-02, which has no data. |
| A15 | **"A few smaller surprises aren't listed"** [DOC] | These are the B items below. |

### 2b. Found by reading mock_portal.py

| # | Behaviour | Why it matters |
|---|---|---|
| B1 | **4 inactive stores**: MUM-009, DEL-010, BLR-004, BLR-010 ([L47](mock_portal.py#L47)). MUM-009 and BLR-004 have `is_serviceable: true` despite being inactive. The inventory function never checks `is_active`, so these stores still return data ([L122](mock_portal.py#L122)). | Tracking them adds phantom observations. Filtering on `is_serviceable` is a trap: it gives 27 stores including 2 inactive ones. |
| B2 | **DEL-006 is active but not serviceable** ([L49](mock_portal.py#L49)). | It is the only store where the two flags disagree in the other direction. Whether to track it is a judgment call (see decision 1). |
| B3 | **Soft-ban mechanics** ([L87-102](mock_portal.py#L87-L102)). The 31st inventory request within 10s triggers a 20s ban. Every request during the ban extends it by 5s, up to 60s. The state is per API key and held in server memory. 429s, 503s and timeouts all count towards the limit, because the counter runs before the rate limiter. `/v1/stores` does not count. | A tight retry loop makes the ban last longer. Sleeping about 25s is the way out. Restarting the server clears it. |
| B4 | **Degraded response shape** ([L175-191](mock_portal.py#L175-L191)). Half the time it is empty. Otherwise it is cut to 1 to a third of the page. It always has `next_cursor: null`, `partial: false` and `source: "edge"`. During a ban you never see a 429 or 503. | A truncated response looks like a small, finished store. Only `meta.source` gives it away. It also masks the DEL-004 partial flag. |
| B5 | **DEL-004 is always `partial: true` with `items: []`** for exactly `2026-09-28T10:30:00Z` ([L232](mock_portal.py#L232)). | This is permanent, so retrying won't fix it. It hits Delhi's IST 28 Sep numbers. |
| B6 | **BLR-007 returns `[]` before 2026-09-27T12:00Z**, with `partial: false` and source origin ([L79](mock_portal.py#L79), [L123](mock_portal.py#L123)). | The first two sweeps (27th 04:30Z and 10:30Z) are empty for this store. |
| B7 | **Ghost stock**: about 5% of in-stock rows have `qty: 0` ([L132](mock_portal.py#L132)). | Using `qty > 0` undercounts availability by about 4%. That is what `review_me.py` does. |
| B8 | **Duplicate row at page seams**: for `cursor > 0`, there is a 35% deterministic chance the page is prefixed with the previous page's last item ([L239-240](mock_portal.py#L239)). | The SKU is double-counted, and API.md's "about 15" page size hides this. |
| B9 | **MUM-007 returns 500 for the first 2 requests per (store, as_of)**, per server lifetime ([L225-230](mock_portal.py#L225)). The count is shared across cursors. | You need at least 3 attempts. A re-run won't reproduce it unless you restart the server. |
| B10 | **SKU-0001 is renamed** from `as_of ≥ 2026-09-28T00:00Z` ([L44](mock_portal.py#L44), [L135](mock_portal.py#L135)). | Grouping by name splits one SKU into two. The IST 28 Sep day spans old and new names. |
| B11 | **BLR prices are strings** (`"237.50"`), the others are floats ([L141](mock_portal.py#L141)). | This only matters if you store or compute with price. It isn't used for OSA. |
| B12 | **`observed_at` is `as_of` + 0 to 20 minutes**, the same for every row of a store-sweep ([L126](mock_portal.py#L126)). Delhi's is formatted in IST ([L116](mock_portal.py#L116)). | See decision 4. |
| B13 | **The server never validates `as_of` against reality.** It returns deterministic, plausible data for any timestamp, so a typo gives fake data. Data is a pure function of (store, sku, as_of). | Re-fetching gives identical data, which is useful for verifying idempotency. |
| B14 | **The 429 limit is global**, not per client ([L193](mock_portal.py#L193)). 503 and slow responses consume slots too. | Your own parallel probes can trigger 429s. |
| B15 | **Expected OSA levels**: about 88% in-stock for Mumbai and Bengaluru, about 80% for Delhi ([L130](mock_portal.py#L130)). Each store carries a fixed 80% of the 36 SKUs. | It's a sanity check. A Delhi value lower than the others is by design, not a bug. Don't hard-code it. |
| B16 | A garbage `cursor` crashes the handler and drops the connection with no JSON ([L183](mock_portal.py#L183)). | Your client should survive non-JSON replies. |

---

## 3. Decisions before coding

**1. Which stores to track.** I recommend `is_active == true`, which gives 26 stores. It includes DEL-006, with `is_serviceable` recorded in the DB but not used as a filter.
- Inactive stores are decommissioned, yet the server still serves them (B1). Tracking them would pollute the numbers.
- `is_serviceable` is a momentary state, and the roster is today's snapshot, so applying it to a historical sweep is meaningless.
- README's example summary says "26 stores". That matches active-only and implicitly includes DEL-006. **[GUESS]**: it is only an example, not a spec, so this is your call.
- Also store the roster snapshot with each sweep, since it can change.

**2. When a store-sweep is "complete".** Mark it complete only if all of these hold:
- every page was fetched by following `next_cursor` to `null`;
- every response was HTTP 200, `meta.source == "origin"` and `partial == false`;
- the response `store_id` matches the store requested.

The four non-complete outcomes need distinct reasons: `partial`, `soft_banned`, `fetch_failed` (retries exhausted) and `not_attempted` (e.g. crashed mid-sweep). **[GUESS]** An optional extra check is to compare the item count to the store's other sweeps. In the mock a store's carried set is constant, but in real life it wouldn't be.
- Store items only for complete store-sweeps, committed atomically per store. That way no partial or edge data can ever be read as truth.
- README is ambiguous on whether to save incomplete rows (see section 6).

**3. Detecting and recovering from the soft-ban.**
- **Detect:** `meta.source != "origin"` is the reliable signal. Don't rely on "few items" alone.
- **React:** discard the whole store's fetch, stop all inventory calls for about 25s (don't probe, since probes extend the ban), then refetch that store from scratch. Cap the recoveries (e.g. 3) so the sweep always terminates.
- **Prevent:** throttle client-side so the budget is not exceeded. Count every attempt, including retries and 429s. I'd target ≤ 2 req/s, since the observed limit is about 3/s (30 per 10s). That would give about 30 to 40 seconds per sweep. README says "a minute or so" is normal and "a few seconds" means you were banned. **[GUESS]** The numbers 2 req/s and 25s are my safety margins, not documented values.
- Run strictly sequentially, one worker.

**4. Mapping sweeps to IST days.** IST = UTC + 5:30 [DOC].

| Sweep (UTC) | IST time | IST day |
|---|---|---|
| 09-27 04:30 | 09-27 10:00 | 27 |
| 09-27 10:30 | 09-27 16:00 | 27 |
| 09-27 19:00 | 09-28 00:30 | **28** |
| 09-28 04:30 | 09-28 10:00 | 28 |
| 09-28 10:30 | 09-28 16:00 | 28 |
| 09-28 18:40 | 09-29 00:10 | **29** |

- So IST 28 has 3 sweeps, IST 27 has 2 and IST 29 has 1.
- The 19:00Z sweep is the trap: it is still 27 Sep in UTC and in Mumbai and Bengaluru `observed_at`, but 28 Sep in IST.
- I recommend the day be determined by the sweep's `as_of`, not row-level `observed_at`. For these six sweeps both give the same IST day (the lag only moves later, and 18:40Z is already past the 18:30Z boundary). **[GUESS]** that the sweep-level rule is the better choice. Add a test asserting the two agree.
- Use a fixed `timezone(timedelta(hours=5, minutes=30))`. Don't use `zoneinfo`, which needs the `tzdata` package on Windows.

**5. Stores with no products.** I recommend a distinct status `empty` (origin, not partial, zero items), reported in `coverage` with a reason like "no products listed" but not counted as a failure.
- It contributes zero observations. It is never 0% and never all-OOS.
- This is safe because an empty reply with `edge` or `partial` is already handled separately (B4, B5).
- The risk is that a real glitch could look like legit emptiness. Re-fetch once to confirm before accepting. **[GUESS]**: whether it counts in `stores_complete` is your call.

**6. Others you didn't list:**
- **Duplicates:** dedupe on `(sweep, store, sku_id)` and assert the duplicate rows are identical (B8).
- **In stock:** use `in_stock` only. Never infer from `qty` (B7).
- **Aggregation:** pool as `sum(in_stock) / sum(observations)`. Don't average per-store percentages (README's own wording says total ÷ total). Items listed with `in_stock: false` count as observations, since "seen listed" includes OOS. **[GUESS]**
- **Naming:** group by `sku_id`; show the latest name (B10).
- **Retry policy:** respect `Retry-After`, use exponential backoff with a cap, and set a read timeout (about 5s, since the slow responses are 8s). Retry 5xx at least 3 times (B9). Don't retry 400/401/404. **[GUESS]** on the specific numbers.
- **Idempotency:** unique key `(as_of_utc, store_id, sku_id)`, with one transaction per store-sweep and a status row per (sweep, store). On re-run, skip store-sweeps already complete and retry the rest. **[GUESS]** that skipping is better than re-fetching. Either satisfies "doesn't change the numbers", and skipping avoids burning the request budget.
- **Status rows up front:** insert `pending` rows for all tracked stores at sweep start, so a crash can never look like an absent store.
- **Timestamps:** normalise to UTC when writing. Python 3.10's `fromisoformat` doesn't accept `Z`, so replace it with `+00:00`. Reject naive timestamps in the CLI.
- **City:** take it from the roster's `city` field, not from the store ID prefix.
- **Roster failure:** if you can't fetch all roster pages, abort. Don't continue with a partial list.
- **Rounding:** use exact arithmetic (Decimal or integers, round half up) rather than float `round()`. **[GUESS]**: low risk.
- **`/osa` with no data:** return `status: "no_data"`, `osa_pct: null`, `observations: 0` and the coverage.

---

## 4. Order of work, with checks

0. **Repo hygiene:** venv, `.gitignore` (db, venv, `__pycache__`), `requirements.txt`, and confirm the recording is running. *Check:* `git diff` on `mock_portal.py` stays empty all the way to submission.
1. **Explore by hand:** probe the server and see what the sections above predict. *Check:* each row in section 2 has a verdict.
2. **Write the decisions** into NOTES.md draft. *Check:* each decision has a one-line "why".
3. **DB schema and write layer.** *Check:* creating it twice is harmless. Inserting a duplicate key can't create two rows.
4. **HTTP client** with timeout, backoff, `Retry-After` and a rate/budget limiter. *Check:* 100 `/v1/stores` calls finish with no crash and no hang.
5. **Fetch and classify one store-sweep.** *Check on known cases:*
   - MUM-001 is complete.
   - DEL-004 at `28T10:30Z` gives `partial`.
   - BLR-007 at `27T04:30Z` gives `empty`.
   - MUM-007 recovers after its 2 failures.
   - A deliberate soft-ban is classified as edge, with no rows stored.
6. **`sweep.py` CLI:** roster, loop, summary line. *Check:* one sweep takes about 30 to 60 seconds, not seconds. 26 stores are accounted for. Zero edge responses leaked into the DB. Re-run, then compare row counts and a content hash. They must be identical.
7. **Run all six sweeps.** *Check:*
   - Every sweep accounts for 26 stores.
   - The only non-complete results are DEL-004 on `28T10:30Z` (`partial`) and BLR-007 on the two earliest sweeps (`empty`).
   - Per-store item counts are stable across sweeps (about 29).
8. **`/osa` app,** with the calculation as a pure function. *Check:* cross-check one city and day by hand in SQL. Better, write a slow independent script that calls the portal directly and compare. Also check a bad city gives 400, a no-data date gives `no_data`, and the default date works.
9. **Tests (≥ 3):** duplicate SKU not double-counted, partial excluded from the numerator and denominator, 19:00Z lands in IST 28, edge response never stored, pooled vs averaged, ghost stock counted. *Check:* one command runs them. Break the code on purpose and see them fail.
10. **review_me.py → REVIEW.md** (section 5).
11. **NOTES.md** (decisions plus the three questions, plus optional bonus), **AI_LOG.md** and README. Keep AI_LOG running as you go. The "AI was wrong twice" entries are far easier to record when they happen.
12. **Final:** fresh clone, run the README commands exactly, 5-minute talk-through, `RECORDING.md`, and open every link in incognito. Then send the email: repo, recordings, `/osa` for `2026-09-28` in 3 cities, and hours.

---

## 5. review_me.py

**What it is:** an AI-written, unreviewed, naive version of this same task. It fetches inventory, saves it and computes OSA. The task is to find at least 5 real problems, ordered most serious first and each with a concrete example. Then fix the 2 or 3 most serious in the file without rewriting it, and put the review in REVIEW.md. The fixed file also ships in your repo.

**Problems I spotted.** These are leads, not verified results, so reproduce each one before writing it up.

1. **Mutable default `results=[]`** ([L20](review_me.py#L20)). The list is shared across calls. The second call (MUM-002) returns MUM-001's items plus its own, so MUM-002's rows contain MUM-001's products.
2. **The retry loop is unbounded** ([L22-33](review_me.py#L22-L33)). It catches every exception, including 400, 401 and 404. It has no timeout, no backoff and ignores `Retry-After`, and it retries every 0.1s. The 429s then lead to a soft-ban.
3. **The script hangs forever as written.** `datetime.utcnow().isoformat()` ([L72](review_me.py#L72)) has no timezone, so the server returns 400. The loop retries it forever and hammers the server.
4. **No handling of `partial`, `meta.source == "edge"` or duplicate rows.** A soft-banned truncated response is saved as truth, and seam duplicates are double-counted.
5. **OSA uses `qty > 0`** ([L61](review_me.py#L61)), so ghost-stock rows count as out-of-stock.
6. **Stores with no rows count as 0.0%** ([L62](review_me.py#L62)), which breaks the golden rule. It also averages per-store ratios instead of pooling.
7. **The `stores` table is created but never populated.** `city_osa` then divides by zero ([L63](review_me.py#L63)).
8. **The day filter is `substr(observed_at,1,10)`** ([L58](review_me.py#L58)), which ignores the Delhi `+05:30` format and the IST boundary. "Yesterday" uses the machine's local `date.today()` and not IST ([L52](review_me.py#L52)).
9. **SQL is built with f-strings** ([L43-46](review_me.py#L43-L46)). A name with an apostrophe breaks the insert, and it's an injection risk.
10. **No unique key and no `as_of` stored.** A re-run duplicates every row.

**What I'd fix (your decision):**
- #1, because it is a one-line fix and silently corrupts data.
- #2 and #3 together, since both sit in the fetch loop. Add a status check, a timeout and a retry cap.
- #5 and #6: switch to `in_stock`, return `None` when there's no data and pool the counts.

If you pick different ones, defend that in REVIEW.md. Also run it yourself first and show what actually happens. I'd expect the hang in #3, but **I haven't run it**.

---

## 6. What I'm unsure about in the README / API.md

1. **DEL-006:** track it or not? Is `is_serviceable` supposed to affect anything? Nothing says. **[GUESS]** that README's "26 stores" example implies tracking it.
2. **What `coverage` counts.** I assume `stores_complete` means stores whose every sweep that day was complete, with `incomplete` listing per store-sweep. Neither README nor API.md defines this. The README sample says `"sweep": "..."`, so the format is unspecified. **[GUESS]**: UTC `as_of` string.
3. **Does a legit-empty store count as "complete" or neither?** (Decision 5.)
4. **Should incomplete store-sweeps keep their rows?** Step 3 says "save the products", while the golden rule says never store a guess. My reading: store only trusted rows.
5. **Whether to reject a lower-case city** (e.g. `mumbai`). The brief says only the three exact names are valid.
6. **A bad or future `date`:** 400 or `no_data`? I'd say 400 for bad format and `no_data` for a valid date with no data. **[GUESS]**
7. **HTTP status for `no_data`.** I assume 200 with the `status` field, since README suggests "status": "no_data".
8. **"Seen" includes OOS rows.** I assume items listed with `in_stock: false` count as observations. It is the natural reading of "times we saw a product listed".
9. **The ghost-stock rule.** README tells you to use `in_stock`, but it isn't clear whether `qty: 0` with `in_stock: true` is a data fault or a real in-stock. I follow the README.
10. **The ordering of `skus`.** I'd sort by `sku_id`, but the brief doesn't say.
11. **The soft-ban thresholds** are unpublished ([DOC]); my numbers come from reading the code. A real portal wouldn't let you do that, so keep the throttle conservative and don't hard-code them.
12. **`observed_at` staleness.** Nothing says what to do if it were far from `as_of`. The mock never does this.
13. **Roster staleness:** statuses are today's, not those at the time of each sweep. You can't recover the historical values, so say so in NOTES.md.
