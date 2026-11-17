"""BDD: 코디네이터의 예보 보정과 실시간 값 보존 — features/coordinator_sync.feature"""
from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from testkit.aio import run
from testkit.factories import KST, make_coordinator
from testkit.keywords import World

scenarios("features/coordinator_sync.feature")

NONE_TOKENS = {"(None)": None, "(빈칸)": ""}


@pytest.fixture
def world():
    coord = make_coordinator(location_entity="zone.home", location=(37.5, 127.0))
    coord._daily_date = coord._daily_max_temp = coord._daily_min_temp = None
    return World(coord=coord, weather={"TMP": 20}, previous={"TMP": "20"})


def entry(items, day_index, daytime=None):
    return next(e for e in items if e["_day_index"] == day_index and (daytime is None or e["is_daytime"] is daytime))


# ── 조건 (Given) ─────────────────────────────────────────────────────────────
@given(parsers.parse("오늘 예보에서 최저 {low:d}도, 최고 {high:d}도가 누적되어 있다"))
def accumulated(world, low, high):
    today = datetime.now(KST).strftime("%Y%m%d")
    world.coord._update_daily_temperatures({today: {"0900": {"TMP": str(low)}, "1500": {"TMP": str(high)}}})


@given(parsers.parse('오늘 요약은 오전 "{am}", 오후 "{pm}"로 저장되어 있다'))
def stored_summary(world, am, pm):
    world.coord._wf_am_today, world.coord._wf_pm_today = am, pm
    world.coord._resolve_area_codes(37.5, 127.0)  # 구역을 이미 정한 상태 (처음 정할 때는 요약을 비운다)
    world.coord._wf_am_today, world.coord._wf_pm_today = am, pm


@given("API 가 오늘·내일의 하루 요약 예보와 하루 두 번 예보를 알려 준다")
def api_forecasts(world):
    def twice(day, daytime):
        return {"_day_index": day, "is_daytime": daytime, "native_temperature": 0, "native_templow": 0, "condition": "fog"}
    world.weather.update({
        "TMX_tomorrow": 26, "TMN_tomorrow": 16, "wf_am_tomorrow": "흐림", "wf_pm_tomorrow": "맑음",
        "forecast_daily": [{"_day_index": d, "native_temperature": 0, "native_templow": 0, "condition": "fog"} for d in (0, 1)],
        "forecast_twice_daily": [twice(d, t) for d in (0, 1) for t in (True, False)]})


@given(parsers.parse('직전 응답의 "{key}" 값은 "{value}"이었다'))
@given(parsers.parse('직전 응답의 "{key}" 값은 "{value}"였다'))
def previous_value(world, key, value):
    world.coord._cached_data = {"weather": {key: NONE_TOKENS.get(value, value)}, "air": {}}


@given(parsers.parse('이번 응답의 "{key}" 값은 "{value}"이다'))
def new_value(world, key, value):
    world.weather = {key: NONE_TOKENS.get(value, value)}


# ── 만일 (When) ──────────────────────────────────────────────────────────────
@when("업데이트가 실행된다")
def update(world):
    world.coord.api.fetch_data = AsyncMock(return_value={
        "weather": dict(world.weather), "air": {}, "pollen": None, "raw_forecast": {}})
    world.result = run(world.coord._async_update_data())


# ── 그러면 (Then) ────────────────────────────────────────────────────────────
@then(parsers.parse("오늘 하루 예보는 최고 {high:d}도, 최저 {low:d}도이다"))
def today_daily(world, high, low):
    day = entry(world.result["weather"]["forecast_daily"], 0)
    assert (day["native_temperature"], day["native_templow"]) == (high, low)


@then(parsers.parse('내일 하루 예보는 최고 {high:d}도, 최저 {low:d}도, 날씨 "{condition}"이다'))
def tomorrow_daily(world, high, low, condition):
    day = entry(world.result["weather"]["forecast_daily"], 1)
    assert (day["native_temperature"], day["native_templow"], day["condition"]) == (high, low, condition)


@then(parsers.re(r'(?P<day>오늘|내일) (?P<half>오전|오후) 예보는 최고 (?P<high>\d+)도, 최저 (?P<low>\d+)도, 날씨 "(?P<condition>[^"]+)"이다'))
def half_day(world, day, half, high, low, condition):
    item = entry(world.result["weather"]["forecast_twice_daily"], 0 if day == "오늘" else 1, half == "오전")
    assert (item["native_temperature"], item["native_templow"], item["condition"]) == (int(high), int(low), condition)


@then(parsers.parse('결과의 "{key}" 값은 "{value}"이다'))
def result_value(world, key, value):
    assert world.result["weather"][key] == NONE_TOKENS.get(value, value)
