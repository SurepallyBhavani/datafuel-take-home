# NOTES

## 1. Main decisions and why

### Which stores I track
A store counts in a sweep only if it is **active and serviceable**. The flags are saved with each sweep, as read when the
sweep ran. The roster has no `as_of`, so they cannot be recovered for an earlier moment. All active stores are fetched
(including DEL-006, active but not serviceable), and the rule is applied when `/osa` runs. Stores left out are listed in
`coverage.excluded` with the reason.

Why: stock in a store that is not accepting orders cannot be bought, so counting it would overstate what a shopper can
get. It is left out and listed, not scored as out of stock.

I compared it with counting active stores only, on the stored data. Mumbai and Bengaluru are identical, because DEL-006 is
the only store that differs. Delhi changes by +0.50, −0.67 and −0.55 percentage points on 27, 28 and 29 Sep (28 Sep:
80.30% against 79.63%). That is below the sampling error of about 1.5 points, and DEL-006's own stock looks like any other
store's (78.6% in stock against 80.7% for the other eight). So the choice rests on the principle and not on a difference I could measure. Limits: the flags are read when the sweep runs, and Delhi is measured on fewer stores than the other cities.

### How I handle each server problem

| Problem | What the scraper does |
|---|---|
| 429 | Waits for `Retry-After` (never more than 60 s) and retries. Requests are paced at about 2 per second, one at a time. |
| 500 / 503 | Retried with growing waits (1, 2, 4, 8 s), at most 6 attempts per request, then the store is incomplete with the reason. MUM-007 fails twice for each new `as_of`, so a store needs at least 3 attempts. |
| Slow replies | 5-second timeout, then retried. |
| 400 / 401 / 404 | Not retried: they cannot succeed. The store is incomplete with the message. |
| Soft-ban | See below. |
| Partial (`partial: true`) | The store is incomplete and none of its rows are saved (DEL-004 at 28 Sep 10:30Z). |
| Duplicates | A product repeated at a page boundary is kept once if the copies are identical (10 of 26 stores had one). Different copies make the store incomplete. |
| Timezones | Every time is parsed with its timezone and stored as UTC. `--as-of` must have a timezone, and `+05:30` and `Z` spellings are the same sweep. |
| Price type | Stored as a number (Bengaluru sends text). |
| Renamed product | Products are identified by `sku_id`, and the latest name is shown (SKU-0001). |
| Store before launch | An empty list from the origin, not partial, is complete with 0 items (BLR-007). It adds no rows, is listed under `coverage.no_products`, and is never 0%. |
| Ghost stock | Availability is the portal's `in_stock` flag. `qty` is stored but not used. |

### How I detect and recover from the soft-ban
A banned reply is HTTP 200 with `meta.source` of `edge`, 0 to 4 items and no next cursor, so it looks like a small finished
store. Every page must come from `origin`. Otherwise the whole store is thrown away, all requests stop, and after 25
seconds the store is fetched again from page 1. If it is still banned the scraper waits 65 seconds, up to 3 recoveries,
then the store is incomplete with the reason `soft_banned`. If 3 stores in a row stay banned, the sweep stops (exit
code 1), the rest stay unfetched, and running the same command later fetches them.

What the probes showed: the ban started at the 31st inventory request within a short burst, and 429 replies count towards
it. After 25 seconds of silence the portal was still banned, because every request made during a ban extends it. That is
why the second wait is 65 seconds, and why requests are paced to stay far below the limit.

### How sweeps are mapped to IST days
A sweep belongs to the IST day of its `as_of` (UTC plus 5:30), not of the `observed_at` on its rows. `observed_at` is set
by the portal, Delhi writes it in IST, and cutting its first ten characters gave the right date for only 9 of 26 stores
on the late sweeps. So 27 Sep has 2 sweeps, 28 Sep has 3 (including the `2026-09-27T19:00:00Z` one) and 29 Sep has 1.
A day's figure is total in-stock rows over total rows seen across the day's sweeps, counting only the stores that
qualified in each sweep.

### What happens when a re-run gives a worse result than the first run
Complete store-sweeps are never overwritten. A re-run skips them and keeps their rows and flags, and retries only the
others. A store is saved in one transaction, so a failed attempt leaves nothing half-written. `started_at` and
`finished_at` change only when a run fetched something.

## 2. Short answers

### The brand says our Delhi availability fell from 92% to 41% yesterday. What would I check first?
I would check the data first, not the stock. I would look at the OSA coverage for yesterday and for the day before: the status (`partial` or `no_data`), the number of observations, and the stores listed there with their reasons (`partial`, `soft_banned`, `fetch_failed`). A drop to 41% on fewer rows, or with store data missing, is a data problem. Next I would check the sweeps: which ones were counted, since a wrong IST day mapping would shift them. I would also check whether stores were excluded because of the serviceable flag, or whether the store list changed. Only once the data and the sweeps are confirmed would I look at the in-stock figures of individual products, and tell the brand whether it is a real drop.

### The dashboard says ₹4.20 lakh, but its store-level numbers add up to ₹4.61 lakh. Which would I show the brand, and why?
I would show only the total that I can trace by adding up the totals, and I would say that there is a gap. The store-level sum can be checked line by line, so I would start from that, but I would not pick either number silently. The ₹0.41 lakh gap (about 9%) can have many causes: different calculations, returns or cancellations counted differently, stores left out of the total, day boundaries and UTC changes, late-arriving orders, or double counting. Until the gap is reconciled, the brand sees the traceable figure with a note on the difference. A wrong number is worse than no number.

### Where would I not use an AI or LLM in this project, and why?
I would not use AI where a number is produced or a decision changes a number: parsing times, assigning a sweep to its IST day, deciding `in_stock`, removing duplicates, deciding whether a store's data is complete or incomplete, detecting the soft-ban, calculating the OSA, and so on. These must give the same answer every time, be testable and be explainable, so I prefer facts and statistics here over assumptions. An AI can sound sure and be wrong, and a second run can give a different answer. I would use it for writing and explaining code, never inside the pipeline.
