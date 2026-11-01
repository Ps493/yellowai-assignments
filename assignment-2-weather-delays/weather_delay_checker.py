"""Weather-aware delivery delay checker.

Reads orders from a JSON file, fetches current weather for every distinct city
concurrently from the OpenWeatherMap API, flags orders whose weather is likely
to delay delivery, and writes the result back to JSON.

Usage:
    python weather_delay_checker.py                       # orders.json in place
    python weather_delay_checker.py -i orders.original.json -o orders.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

API_URL = "https://api.openweathermap.org/data/2.5/weather"

# OpenWeatherMap's `weather[0].main` values that we treat as delivery-blocking.
# "Extreme" is not a literal `main` value in the OWM API (it is a condition
# group), so extreme conditions are also detected by condition id below.
DELAY_MAIN = {"Rain", "Snow", "Extreme", "Thunderstorm", "Squall", "Tornado"}
# Condition ids: 504 extreme rain, 511 freezing rain, 781 tornado,
# 900-906 extreme (tornado, tropical storm, hurricane, cold, hot, windy, hail),
# 960-962 storm / violent storm / hurricane.
EXTREME_IDS = {504, 511, 781, *range(900, 907), 960, 961, 962}

MAX_CONCURRENCY = 10  # polite ceiling; free tier allows 60 calls/min
MAX_RETRIES = 3
REQUEST_TIMEOUT = 10.0

log = logging.getLogger("weather-delays")


class CityNotFoundError(Exception):
    """The weather API does not know this city (HTTP 404)."""


class WeatherAPIError(Exception):
    """Any other failure talking to the weather API."""


@dataclass(frozen=True)
class Weather:
    main: str
    description: str
    condition_id: int

    @property
    def causes_delay(self) -> bool:
        return self.main in DELAY_MAIN or self.condition_id in EXTREME_IDS


# --------------------------------------------------------------------------- #
# Fetching
# --------------------------------------------------------------------------- #
async def fetch_weather(
    client: httpx.AsyncClient,
    city: str,
    api_key: str,
    semaphore: asyncio.Semaphore,
) -> Weather:
    """Fetch current weather for one city, with retry on transient failures."""
    params = {"q": city, "appid": api_key, "units": "metric"}

    async with semaphore:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = await client.get(API_URL, params=params)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt == MAX_RETRIES:
                    raise WeatherAPIError(f"network error: {exc!r}") from exc
                await asyncio.sleep(2 ** (attempt - 1))
                continue

            if resp.status_code == 200:
                return _parse_weather(resp.json())
            if resp.status_code == 404:
                raise CityNotFoundError(f"city not found: {city!r}")
            if resp.status_code == 401:
                # Retrying will not fix a bad key; fail fast and loudly.
                raise WeatherAPIError("invalid API key (HTTP 401)")
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == MAX_RETRIES:
                    raise WeatherAPIError(f"HTTP {resp.status_code} after {attempt} attempts")
                retry_after = resp.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 2 ** (attempt - 1)
                await asyncio.sleep(delay)
                continue
            raise WeatherAPIError(f"unexpected HTTP {resp.status_code}")

    raise WeatherAPIError("exhausted retries")  # pragma: no cover


def _parse_weather(payload: dict[str, Any]) -> Weather:
    try:
        first = payload["weather"][0]
        return Weather(
            main=first["main"],
            description=first.get("description", first["main"].lower()),
            condition_id=int(first.get("id", 0)),
        )
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise WeatherAPIError(f"malformed API response: {exc!r}") from exc


async def fetch_all(
    cities: list[str],
    api_key: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Weather | Exception]:
    """Fetch every distinct city concurrently.

    One failure never cancels the others: each result is either a Weather or
    the exception that city raised. `transport` lets tests inject a mock API.
    """
    unique = list(dict.fromkeys(cities))  # de-duplicate, keep order
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, transport=transport) as client:
        results = await asyncio.gather(
            *(fetch_weather(client, c, api_key, semaphore) for c in unique),
            return_exceptions=True,
        )
    return dict(zip(unique, results))


# --------------------------------------------------------------------------- #
# Business logic
# --------------------------------------------------------------------------- #
def generate_apology(customer: str, city: str, weather: Weather) -> str:
    """Build a personalised, weather-aware apology for a delayed order."""
    first_name = customer.strip().split()[0] if customer.strip() else "there"
    return (
        f"Hi {first_name}, your order to {city} is delayed due to "
        f"{_describe(weather)}. We appreciate your patience!"
    )


def _describe(weather: Weather) -> str:
    if weather.condition_id in EXTREME_IDS or weather.main == "Extreme":
        return f"extreme weather ({weather.description})"
    return weather.description  # e.g. "heavy intensity rain", "light snow"


def apply_weather(orders: list[dict], results: dict[str, Weather | Exception]) -> dict[str, int]:
    """Update orders in place and return summary counts."""
    summary = {"delayed": 0, "on_track": 0, "errors": 0}

    for order in orders:
        city = order["city"]
        result = results.get(city)

        if isinstance(result, Exception) or result is None:
            summary["errors"] += 1
            order["weather_check"] = "error"
            order["error"] = str(result) if result else "no result"
            # A failed lookup says nothing about the weather: drop what an earlier run
            # wrote so the file never shows stale data next to an error.
            order.pop("weather", None)
            order.pop("apology_message", None)
            log.error("Order %s (%s): %s", order["order_id"], city, order["error"])
            continue

        order.pop("error", None)
        order["weather_check"] = "ok"
        order["weather"] = result.main
        if result.causes_delay:
            order["status"] = "Delayed"
            order["apology_message"] = generate_apology(order["customer"], city, result)
            summary["delayed"] += 1
            log.warning("Order %s (%s): DELAYED - %s", order["order_id"], city, result.description)
        else:
            # Re-running on a file from an earlier run: clear the old delay.
            order.pop("apology_message", None)
            if order.get("status") == "Delayed":
                order["status"] = "Pending"
            summary["on_track"] += 1
            log.info("Order %s (%s): on track - %s", order["order_id"], city, result.description)

    return summary


# --------------------------------------------------------------------------- #
# I/O + CLI
# --------------------------------------------------------------------------- #
def load_orders(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a JSON array of orders")
    return data


def save_orders(path: Path, orders: list[dict]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(orders, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)  # atomic: never leaves a half-written file


async def run(
    input_path: Path,
    output_path: Path,
    api_key: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, int]:
    orders = load_orders(input_path)
    log.info("Loaded %d orders; fetching weather concurrently...", len(orders))
    results = await fetch_all([o["city"] for o in orders], api_key, transport=transport)
    summary = apply_weather(orders, results)
    save_orders(output_path, orders)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Flag delivery delays using live weather.")
    parser.add_argument("-i", "--input", type=Path, default=Path("orders.json"))
    parser.add_argument("-o", "--output", type=Path, default=None,
                        help="defaults to the input file (updated in place)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)  # keeps the API key out of logs

    load_dotenv()
    api_key = os.getenv("OPENWEATHER_API_KEY", "").strip()
    if not api_key:
        log.error("OPENWEATHER_API_KEY is not set. Copy .env.example to .env and add your key.")
        return 2

    try:
        summary = asyncio.run(run(args.input, args.output or args.input, api_key))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        log.error("Could not process orders file: %s", exc)
        return 1

    log.info("Done: %(delayed)d delayed, %(on_track)d on track, %(errors)d errors", summary)
    if summary["errors"] and not (summary["delayed"] or summary["on_track"]):
        # Every lookup failed (bad key, no network...): do not report success.
        log.error("No order could be checked.")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
