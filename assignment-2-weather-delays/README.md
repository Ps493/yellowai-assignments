# Assignment 2: Weather-Aware Delivery Delays

Fetches the current weather for every order's city (all cities **concurrently**) and marks weather-affected orders as `Delayed`, with a personalised apology message.

Requires **Python 3.10+**.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # then put your OpenWeatherMap key in .env
cp orders.original.json orders.json                    # the script updates orders.json in place
python weather_delay_checker.py
```

Options: `-i input.json`, `-o output.json` (default: update the input in place), `-v` for debug logs. New OpenWeatherMap keys can take a while to activate; until then the API answers 401 and the script reports `invalid API key`.

Tests run offline and need no key: `pytest -q`

Exit codes: `0` ok, `1` orders file unreadable, `2` API key missing, `3` no order could be checked at all (for example a bad key).

## What it does

| Requirement | How |
|---|---|
| Concurrent fetching | `fetch_all()` creates one coroutine per distinct city and runs them with `asyncio.gather`. A test shows three 0.3 s calls finish in about 0.3 s, not 0.9 s. |
| Delay rule | `Rain`, `Snow` and `Extreme` weather set the status to `Delayed`. See the design notes for how "Extreme" works and for the three extra conditions. |
| Apology | `generate_apology()` writes e.g. `Hi Alice, your order to New York is delayed due to heavy intensity rain. We appreciate your patience!` into `apology_message`. |
| `InvalidCity123` | The 404 is logged and stored on that order (`weather_check: "error"`, `error: ...`). Its status stays `Pending` and every other city is still processed. |
| API key | Read from `.env` (git-ignored). Only `.env.example` is committed. |

Fields added to each order: `weather_check` (`ok` / `error`), `weather` (e.g. `Rain`), `apology_message` (only if delayed), `error` (only on failure). Running the script again on an already-processed file is safe: old delays and apologies are cleared if the weather has improved.

## Design decisions

| Decision | Why |
|---|---|
| `asyncio.gather` plus a semaphore (max 10 in flight) | `gather` gives the concurrency; the semaphore stops a big order list from firing hundreds of calls at once and hitting the API limit. |
| `return_exceptions=True` | Without it, the first failing city (like `InvalidCity123`) would raise out of `gather` and the other results would be lost. With it, every city returns either a weather result or its error. |
| Each distinct city is fetched once | 500 orders to London cost one API call. |
| "Extreme" is matched by condition id | OpenWeatherMap's `weather[0].main` has no literal `Extreme` value; extreme conditions appear as condition ids (extreme rain 504, freezing rain 511, tornado 781, 900-906, 960-962). The code checks those ids as well as `main`. |
| Thunderstorm, Squall and Tornado also count as delays | This is a deliberate superset of the brief's Rain / Snow / Extreme. A thunderstorm grounds deliveries just like rain does. It is one set (`DELAY_MAIN`) at the top of the file, so removing them is a one-line change. |
| 429 / 5xx / timeouts are retried (3 tries, backoff, honours `Retry-After`); 401 and 404 are not | The first group can succeed on a later try. A wrong key or an unknown city will fail the same way every time, so retrying only wastes time and quota. |
| Failed lookup leaves the order's status alone | An error means "unknown weather", not "good weather" and not "bad weather". |
| Output written atomically (temp file, then rename) | A crash can't leave a half-written `orders.json`. |
| `httpx` logging turned down to WARNING | The API key is in the request URL (OpenWeatherMap's design), and `httpx` logs URLs at INFO. |

## Sample output (mocked sample)

Produced by running the script against a mocked weather API (not live data), to show the log format:

```
11:04:55 | INFO    | Loaded 4 orders; fetching weather concurrently...
11:04:55 | WARNING | Order 1001 (New York): DELAYED - heavy intensity rain
11:04:55 | INFO    | Order 1002 (Mumbai): on track - scattered clouds
11:04:55 | WARNING | Order 1003 (London): DELAYED - light snow
11:04:55 | ERROR   | Order 1004 (InvalidCity123): city not found: 'InvalidCity123'
11:04:55 | INFO    | Done: 2 delayed, 1 on track, 1 errors
```
