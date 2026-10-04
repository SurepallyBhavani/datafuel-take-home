# Review of `review_me.py`

## How I reviewed it

I read the file, then ran each suspected problem to see what it actually does:
- I ran `python review_me.py` unchanged with the portal stopped. It printed nothing and spun until I pressed Ctrl+C.
- I ran the other cases against a private copy of the portal (`PORT=9000`) and against throwaway in-memory databases, so the real `osa.db` was never touched.
- One change before any of this: the script opened `osa.db`, the same name as the real project database. It now opens `review_me.db`, so running it cannot touch the real data.

The problems are ordered most serious first. A wrong number that nobody notices ranks above a crash, because a crash gets noticed.

| # | Problem | Status |
|---|---|---|
| 1 | Endless retry loop, and `as_of` has no timezone | Fixed |
| 2 | Mutable default `results=[]` | Fixed |
| 3 | A soft-banned reply is accepted as real data | Fixed |
| 4 | Availability decided with `qty > 0` instead of `in_stock` | Fixed |
| 5 | A store with no data counts as 0%, and store percentages are averaged | Fixed |
| 6 | The day is cut from `observed_at` text | Not fixed |
| 7 | The default day comes from the laptop's clock | Fixed |
| 8 | `partial` replies and duplicate rows are not handled | `partial` fixed, duplicates not |
| 9 | Division by zero, and the `stores` table is never filled | Division fixed, empty table not |
| 10 | SQL built with f-strings | Not fixed |
| 11 | No unique key, no sweep time, no completeness flag | Not fixed |

## The problems

### 1. Endless retry loop, and `as_of` has no timezone (fixed)
**What goes wrong.** `except Exception: time.sleep(0.1); continue` retries every error, including ones that can never succeed (400, 401, 404, a refused connection). There is no timeout, no cap, no `Retry-After`, and nothing is printed. The script's own `as_of` is `datetime.utcnow().isoformat()`, which has no timezone, so the portal answers 400 every time.
**Example.** With the original code and a running portal, 40 attempts took 4.4 seconds (about 9 requests per second) and never succeeded; the replies were 400, 429 and 503. Those requests count towards the portal's soft-ban limit and each request made during a ban extends it. With the portal stopped, the script hangs with no message.
**Fix.** A 5-second timeout, at most 6 attempts with growing waits, `Retry-After` honoured on 429, a 0.5-second gap between requests, no retry on 400, 401 and 404 (they raise an error with the reason), and an `as_of` with a timezone. A bad `as_of` now stops after 0.5 seconds with `as_of must include a timezone`. An unreachable portal gives up with a message after 6 attempts.

### 2. Mutable default `results=[]` (fixed)
**What goes wrong.** The default list is created once, so every call shares it and each store's result includes the earlier stores' rows.
**Example.** MUM-001 returned 33 items. The next call, for MUM-002, returned 61, though MUM-002 has 28. Saved under MUM-002 were 61 rows with 35 distinct SKUs, so MUM-002's rows contained MUM-001's products.
**Fix.** `results=None`, and a new list is created inside the function. MUM-002 now returns 28.

### 3. A soft-banned reply is accepted as real data (fixed)
**What goes wrong.** After too many requests the portal keeps answering HTTP 200 but sends degraded data (`meta.source` is `edge`, 0 to 4 items, `next_cursor` null). `raise_for_status()` passes, so the script treats that as the store's whole inventory.
**Example.** A store with about 32 products would be saved with 3 or 4, or none, and nothing marks it as wrong.
**Fix.** Every page's `meta.source` is checked. If it isn't `origin`, `SoftBanned` is raised and nothing from that attempt is returned. `fetch_store` waits (25, then 65, then 65 seconds), starts the store again from page 1, and raises the error if it is still banned. In a forced test it returned all 33 items, the same as a clean fetch, after 99 seconds.

### 4. `qty > 0` instead of `in_stock` (fixed)
**What goes wrong.** About 5% of in-stock rows have `qty` 0 (ghost stock), and API.md says `qty` is informational. Those rows count as out of stock.
**Example.** Two rows, both `in_stock = 1`, one with `qty` 0: the function returned 50.0, where the answer is 100.
**Fix.** The query reads `in_stock`.

### 5. A store with no data counts as 0%, and percentages are averaged (fixed)
**What goes wrong.** A store with no rows gets 0.0, which turns missing data into "out of stock". The city figure is the average of the stores' percentages, so a store with 1 row weighs as much as one with 29.
**Example.** One store 100% in stock and one with no rows: 50.0. One store 1 of 1 in stock and another 0 of 9: 50.0, where the pooled figure is 10.0.
**Fix.** The counts are added up across stores: total in stock over total rows. A store without rows adds nothing. When no rows were seen the function returns `None`, not 0.

### 6. The day is cut from `observed_at` text (not fixed)
**What goes wrong.** `substr(observed_at, 1, 10)` takes the first 10 characters and ignores the timezone. Mumbai and Bengaluru write UTC (`Z`) and Delhi writes IST (`+05:30`).
**Example.** A row observed at `2026-09-27T19:00:00Z` is counted for 27 Sep, but that moment is 28 Sep in India. Delhi writes `2026-09-28T00:30:00+05:30` for the same sweep, so one sweep falls on two days. In the real data, converting properly gave the right IST date for 26 of 26 stores on the 19:00Z sweep, while the text cut gave it for 9 of 26.
**Why not fixed.** A proper fix needs the sweep time (`as_of`) saved with each row and the day worked out from it. That means changing the table, which is a bigger change than this review asks for. The real project does it (`sweeps.ist_date`).

### 7. The default day comes from the laptop's clock (fixed)
**What goes wrong.** `date.today()` uses the machine's timezone, not India's. README defines the day as the IST calendar day, so the default ("yesterday") must be worked out in IST. A laptop already set to India time would happen to get the right answer; a machine set to UTC, such as most servers, does not.
**Example.** On a machine set to UTC, at 20:00 UTC on 3 Oct it is already 01:30 on 4 Oct in India. "Yesterday" in India is 3 Oct, but `date.today()` says 3 Oct and the code looked at 2 Oct.
**Fix.** The default is yesterday in IST (`datetime.now(IST).date() - 1 day`).

### 8. `partial` replies and duplicate rows (partly fixed)
**What goes wrong.** A `partial: true` reply is saved as if complete. A product repeated at a page boundary is counted twice.
**Example.** DEL-004 at `2026-09-28T10:30:00Z` always returns `partial: true` with no items. MUM-001 returned 33 rows for 32 distinct SKUs.
**Fix.** `partial` now raises an error and returns nothing. Duplicates are not fixed.

### 9. Division by zero, and the `stores` table is never filled (partly fixed)
**What goes wrong.** `__main__` creates the `stores` table but never fills it, so `city_osa` finds no stores and divides by zero.
**Example.** `city_osa(conn, "Mumbai", "2026-09-28")` on an empty `stores` table raised `ZeroDivisionError`.
**Fix.** The function returns `None` when there is nothing to divide. The table is still never filled, so the script prints `None`.

### 10. SQL built with f-strings (not fixed)
**What goes wrong.** Values are pasted into the SQL text, so a product name with an apostrophe breaks the statement, and it is open to injection.
**Example.** A product named `Kellogg's Corn Flakes` raised `OperationalError: near "s": syntax error`.
**Fix, if done.** Use `?` placeholders, as the real project does.

### 11. No unique key, no sweep time, no completeness flag (not fixed)
**What goes wrong.** The `inventory` table has no primary key and does not store the sweep time or whether the store's data was complete. I read this from the code and did not run a second pass.
**Example.** Running the script twice would insert every row twice, and an incomplete store cannot be told from a complete one.

## Smaller issues, not fixed
Recursion for paging, the deprecated `datetime.utcnow()` (no longer used), settings hard-coded in the file, and the database connection never closed.

## What I changed in the file

| Place | Change |
|---|---|
| `fetch_inventory` | `results=None`; timeout, attempt limit, `Retry-After`, 0.5-second gap; no retry on 400/401/404; checks `meta.source` and `partial` |
| `fetch_store` (new) | Waits out a soft-ban and starts the store again, up to 3 times |
| `city_osa` | `in_stock`, pooled counts, `None` when nothing was seen, default day in IST |
| `__main__` | `as_of` with a timezone; calls `fetch_store`; database file `review_me.db` |

I fixed more than three because the fixes are small and sit in three places: `fetch_inventory`, `fetch_store` and `city_osa`.
