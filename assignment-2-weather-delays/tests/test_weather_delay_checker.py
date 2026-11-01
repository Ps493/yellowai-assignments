"""Offline tests: the OpenWeatherMap API is replaced by httpx.MockTransport."""

import asyncio
import json
import sys
import time
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import weather_delay_checker as wdc  # noqa: E402

ORIGINAL = Path(__file__).resolve().parents[1] / "orders.original.json"


def owm(main: str, description: str, cid: int) -> dict:
    return {"weather": [{"id": cid, "main": main, "description": description}]}


FAKE_WEATHER = {
    "New York": owm("Rain", "heavy intensity rain", 502),
    "Mumbai": owm("Clouds", "scattered clouds", 802),
    "London": owm("Snow", "light snow", 600),
}


def make_transport(delay: float = 0.0, calls: list | None = None):
    async def handler(request: httpx.Request) -> httpx.Response:
        city = request.url.params["q"]
        if calls is not None:
            calls.append(city)
        if delay:
            await asyncio.sleep(delay)
        if city in FAKE_WEATHER:
            return httpx.Response(200, json=FAKE_WEATHER[city])
        return httpx.Response(404, json={"cod": "404", "message": "city not found"})

    return httpx.MockTransport(handler)


def test_invalid_city_does_not_crash_and_valid_cities_still_processed():
    orders = json.loads(ORIGINAL.read_text())
    results = asyncio.run(
        wdc.fetch_all([o["city"] for o in orders], "k", transport=make_transport())
    )
    summary = wdc.apply_weather(orders, results)

    by_id = {o["order_id"]: o for o in orders}
    assert by_id["1001"]["status"] == "Delayed"  # Rain
    assert by_id["1002"]["status"] == "Pending"  # Clouds
    assert by_id["1003"]["status"] == "Delayed"  # Snow
    assert by_id["1004"]["status"] == "Pending"  # invalid city left untouched
    assert by_id["1004"]["weather_check"] == "error"
    assert "not found" in by_id["1004"]["error"]
    assert summary == {"delayed": 2, "on_track": 1, "errors": 1}


def test_requests_run_concurrently_not_sequentially():
    # 3 cities x 0.3s each: sequential would take >= 0.9s, concurrent ~0.3s.
    # The 0.8s bound leaves room for a slow CI machine and still fails if sequential.
    start = time.perf_counter()
    asyncio.run(
        wdc.fetch_all(["New York", "Mumbai", "London"], "k", transport=make_transport(delay=0.3))
    )
    elapsed = time.perf_counter() - start
    assert elapsed < 0.8, f"calls look sequential ({elapsed:.2f}s)"


def test_duplicate_cities_fetched_once():
    calls: list[str] = []
    asyncio.run(
        wdc.fetch_all(["London", "London", "London"], "k", transport=make_transport(calls=calls))
    )
    assert calls == ["London"]


def test_apology_message_is_personalised():
    w = wdc.Weather("Rain", "heavy intensity rain", 502)
    msg = wdc.generate_apology("Alice Smith", "New York", w)
    assert msg == (
        "Hi Alice, your order to New York is delayed due to heavy intensity rain. "
        "We appreciate your patience!"
    )


@pytest.mark.parametrize(
    "main,cid,expected",
    [
        ("Rain", 500, True),
        ("Snow", 601, True),
        ("Thunderstorm", 211, True),
        ("Clear", 800, False),
        ("Clouds", 804, False),
        ("Drizzle", 300, False),
        ("Clear", 902, True),  # extreme id even if main looks harmless
    ],
)
def test_delay_rules(main, cid, expected):
    assert wdc.Weather(main, "x", cid).causes_delay is expected


def test_retries_on_429_then_succeeds(monkeypatch):
    async def no_sleep(_):
        return None

    monkeypatch.setattr(wdc.asyncio, "sleep", no_sleep)
    attempts = {"n": 0}

    async def handler(request):
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(429)
        return httpx.Response(200, json=FAKE_WEATHER["London"])

    out = asyncio.run(wdc.fetch_all(["London"], "k", transport=httpx.MockTransport(handler)))
    assert isinstance(out["London"], wdc.Weather)
    assert attempts["n"] == 3


def test_bad_api_key_fails_fast_without_retry():
    attempts = {"n": 0}

    async def handler(request):
        attempts["n"] += 1
        return httpx.Response(401, json={"cod": 401})

    out = asyncio.run(wdc.fetch_all(["London"], "bad", transport=httpx.MockTransport(handler)))
    assert isinstance(out["London"], wdc.WeatherAPIError)
    assert attempts["n"] == 1


def test_malformed_response_is_an_error_not_a_crash():
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"unexpected": True}))
    out = asyncio.run(wdc.fetch_all(["London"], "k", transport=transport))
    assert isinstance(out["London"], wdc.WeatherAPIError)


def test_missing_api_key_exits_cleanly(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENWEATHER_API_KEY", raising=False)
    monkeypatch.setattr(wdc, "load_dotenv", lambda: None)
    assert wdc.main(["-i", str(tmp_path / "orders.json")]) == 2


def test_save_orders_roundtrip(tmp_path):
    path = tmp_path / "o.json"
    wdc.save_orders(path, [{"order_id": "1", "status": "Delayed"}])
    assert json.loads(path.read_text()) == [{"order_id": "1", "status": "Delayed"}]
    assert not list(tmp_path.glob("*.tmp"))


# --------------------------------------------------------------------------- #
# Re-running on an already-processed file
# --------------------------------------------------------------------------- #
def _order(city="London", status="Pending", **extra):
    return {"order_id": "1", "customer": "Alice Smith", "city": city, "status": status, **extra}


def test_rerun_with_clear_weather_clears_an_old_delay():
    order = _order(status="Delayed", weather="Rain", apology_message="old apology")
    results = {"London": wdc.Weather("Clear", "clear sky", 800)}
    wdc.apply_weather([order], results)
    assert order["status"] == "Pending"
    assert "apology_message" not in order
    assert order["weather"] == "Clear"


def test_rerun_does_not_touch_other_statuses():
    order = _order(status="Shipped")
    wdc.apply_weather([order], {"London": wdc.Weather("Clear", "clear sky", 800)})
    assert order["status"] == "Shipped"


def test_error_after_a_previous_success_drops_stale_weather():
    order = _order(status="Delayed", weather="Rain", apology_message="old apology")
    wdc.apply_weather([order], {"London": wdc.WeatherAPIError("HTTP 503 after 3 attempts")})
    assert order["weather_check"] == "error"
    assert "weather" not in order
    assert "apology_message" not in order
    assert order["status"] == "Delayed"  # unknown weather: we do not silently undo a delay


# --------------------------------------------------------------------------- #
# End to end through run() and main()
# --------------------------------------------------------------------------- #
def test_run_end_to_end_writes_the_expected_json(tmp_path):
    src = tmp_path / "orders.json"
    src.write_text(ORIGINAL.read_text())
    out = tmp_path / "result.json"

    summary = asyncio.run(wdc.run(src, out, "k", transport=make_transport()))

    assert summary == {"delayed": 2, "on_track": 1, "errors": 1}
    written = {o["order_id"]: o for o in json.loads(out.read_text())}
    assert written["1001"]["status"] == "Delayed"
    assert written["1001"]["apology_message"].startswith("Hi Alice, your order to New York")
    assert written["1002"]["status"] == "Pending"
    assert "apology_message" not in written["1002"]
    assert written["1004"]["weather_check"] == "error"
    assert json.loads(src.read_text()) == json.loads(ORIGINAL.read_text())  # input untouched


def test_exit_code_3_when_every_order_fails(monkeypatch, tmp_path):
    src = tmp_path / "orders.json"
    src.write_text(ORIGINAL.read_text())
    monkeypatch.setenv("OPENWEATHER_API_KEY", "bad")
    monkeypatch.setattr(wdc, "load_dotenv", lambda: None)

    real_fetch_all = wdc.fetch_all
    always_401 = httpx.MockTransport(lambda r: httpx.Response(401, json={"cod": 401}))

    async def fetch_with_mock(cities, api_key, transport=None):
        return await real_fetch_all(cities, api_key, transport=always_401)

    monkeypatch.setattr(wdc, "fetch_all", fetch_with_mock)
    assert wdc.main(["-i", str(src), "-o", str(tmp_path / "out.json")]) == 3


def test_exit_code_0_when_some_orders_succeed(monkeypatch, tmp_path):
    src = tmp_path / "orders.json"
    src.write_text(ORIGINAL.read_text())
    monkeypatch.setenv("OPENWEATHER_API_KEY", "k")
    monkeypatch.setattr(wdc, "load_dotenv", lambda: None)

    real_fetch_all = wdc.fetch_all

    async def fetch_with_mock(cities, api_key, transport=None):
        return await real_fetch_all(cities, api_key, transport=make_transport())

    monkeypatch.setattr(wdc, "fetch_all", fetch_with_mock)
    assert wdc.main(["-i", str(src), "-o", str(tmp_path / "out.json")]) == 0
