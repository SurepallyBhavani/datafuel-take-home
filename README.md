# QuickMart inventory scraper and OSA report

A scraper (`sweep.py`) that collects store inventory from the QuickMart portal into a SQLite database, and a small
API (`app.py`) that reports on-shelf availability (OSA) for a city on an Indian (IST) calendar day.

Python 3.10 or newer. Everything runs on one machine: the portal, the scraper and the API.

## 1. Set up

Run all commands from the project folder.

**Windows (PowerShell)**
```powershell
python -m venv datafuel
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass     # only if PowerShell blocks the next line
.\datafuel\Scripts\Activate.ps1
pip install -r requirements.txt
```

**macOS / Linux**
```bash
python3 -m venv datafuel
source datafuel/bin/activate
pip install -r requirements.txt
```

## 2. Start the portal

In its own terminal, leave it running:
```
python mock_portal.py
```
It serves http://127.0.0.1:8765. If that port is taken, start it on another one (PowerShell:
`$env:PORT=9000; python mock_portal.py`, bash: `PORT=9000 python3 mock_portal.py`) and tell the scraper where it is
with `PORTAL_URL` (PowerShell: `$env:PORTAL_URL="http://127.0.0.1:9000"`, bash: `export PORTAL_URL=http://127.0.0.1:9000`).

## 3. Run the six sweeps

In a second terminal (venv active, project folder), one at a time:
```
python sweep.py --as-of 2026-09-27T04:30:00Z
python sweep.py --as-of 2026-09-27T10:30:00Z
python sweep.py --as-of 2026-09-27T19:00:00Z
python sweep.py --as-of 2026-09-28T04:30:00Z
python sweep.py --as-of 2026-09-28T10:30:00Z
python sweep.py --as-of 2026-09-28T18:40:00Z
```
Each takes about a minute, because requests are paced at about two per second to stay clear of the portal's soft-ban.
The last line is a summary, for example:
```
26 active stores: 26 complete, 0 incomplete | 4 inactive skipped | 0m48s
```
The sweep for `2026-09-28T10:30:00Z` should end with one incomplete store:
```
26 active stores: 25 complete, 1 incomplete [DEL-004: partial (portal returned partial: true)] | 4 inactive skipped | 0m42s
```
The data goes into `osa.db`, created in the folder you run the command from, so always run from the project folder.

Things to know:
- **Safe to run twice.** Stores that are already complete are skipped. Incomplete ones are fetched again. Running a
  sweep again does not change the numbers.
- **`--as-of` must have a timezone.** `2026-09-28T10:00:00+05:30` and `2026-09-28T04:30:00Z` are the same sweep.
- **Soft-ban.** If the portal starts returning degraded data, the scraper discards that store, waits (25 seconds, then
  65), and fetches it again from the first page. If three stores in a row stay banned, the sweep stops with a message
  and exit code 1; run the same command later to fetch the rest. Restarting the portal clears a ban at once.

## 4. Start the API

In a third terminal (venv active, project folder):
```
flask --app app run --port 5055
```
Then open, for example:
```
http://127.0.0.1:5055/osa?city=Mumbai&date=2026-09-28
http://127.0.0.1:5055/osa?city=Delhi&date=2026-09-28
http://127.0.0.1:5055/osa?city=Bengaluru&date=2026-09-28
```
`city` must be `Mumbai`, `Delhi` or `Bengaluru`. `date` is `YYYY-MM-DD`, the IST day. Without `date` it uses yesterday in
IST. Anything else returns HTTP 400 with a message. The API reads `osa.db` only and never calls the portal.

After the six sweeps you should get:

| City | `osa_pct` | `observations` | `status` |
|---|---|---|---|
| Mumbai | 86.06 | 753 | `ok` |
| Delhi | 80.3 | 665 | `partial` (DEL-004 is incomplete in one sweep) |
| Bengaluru | 89.57 | 690 | `ok` |

The response has `osa_pct`, `observations`, `in_stock`, a `skus` list, and a `coverage` block: stores expected and
complete, every incomplete store and sweep with its reason, every excluded store with its reason, stores with no
products, and the stores and rows counted in each sweep. A day with no data returns `"status": "no_data"` and
`"osa_pct": null`, never 0.

## 5. Run the tests

```
python -m pytest
```
This runs without the portal and does not touch `osa.db`. Add `-v` to see one line per test.

## What counts as a store, a day and a complete sweep

- **Stores counted.** A store counts in a sweep only if it is active **and** serviceable in the roster as read during that
  sweep. Those flags are saved with each sweep. Stores left out are listed in `coverage.excluded` with the reason.
- **Days.** A sweep belongs to the IST day of its `--as-of` time. The `2026-09-27T19:00:00Z` sweep is 28 Sep in India.
- **Complete.** All pages fetched, every page from the origin and not partial. Anything else is incomplete, saved with a
  reason, and none of its rows are stored. Incomplete stores are never counted as out of stock.
- **Availability** is the portal's `in_stock` flag. A day's figure is total in-stock rows over total rows seen.

The reasons for each choice, the numbers behind them, and the comparison with counting active stores only are in
[NOTES.md](NOTES.md).

## Files

| File | What it is |
|---|---|
| `sweep.py` | The scraper: one run is one sweep |
| `db.py` | The SQLite tables |
| `app.py` | The `/osa` API |
| `tests/` | The pytest tests |
| `mock_portal.py`, `API.md` | The portal and its contract, unchanged |
| `review_me.py`, `REVIEW.md` | The reviewed file with fixes, and the review |
| `NOTES.md` | Observations, decisions and short answers |
| `AI_LOG.md` | How AI was used |
| `RECORDING.md` | Recording links and key moments |
| `requirements.txt` | Libraries |

## Troubleshooting

- **PowerShell will not run the activate script:** `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`. It only
  lasts for that window.
- **`/osa` says "no such table", or every day is `no_data`:** the API was started from another folder, or no sweep has
  been run yet. Start it from the project folder.
- **A sweep takes only a few seconds and has few items:** the portal may be soft-banning you. Restart the portal and
  run the sweep again.
