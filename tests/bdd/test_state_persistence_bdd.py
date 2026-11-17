"""BDD: 재시작 후에도 이어지는 오늘 기온과 측정소 정보 — features/state_persistence.feature (실제 Home Assistant)"""
from datetime import date, datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kma_weather.const import DOMAIN
from custom_components.kma_weather.coordinator import KMAWeatherUpdateCoordinator
from testkit.aio import run_on

scenarios("features/state_persistence.feature")


@pytest.fixture
def coord(hass):
    """저장소 입출력은 가짜로 바꾼 실제 코디네이터."""
    async def build():
        entry = MockConfigEntry(domain=DOMAIN, data={"api_key": "key", "location_entity": ""},
                                entry_id="persistence")
        return KMAWeatherUpdateCoordinator(hass, entry)

    coordinator = run_on(hass, build())
    for store in (coordinator._store, coordinator._station_store):
        store.async_load, store.async_save = AsyncMock(return_value=None), AsyncMock()
    return coordinator


@pytest.fixture
def outcome():
    """When 단계에서 잡아 둔 예외를 Then 단계로 넘긴다."""
    return {"error": None}


@pytest.fixture
def run(hass):
    return lambda coro: run_on(hass, coro)


def today_text():
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d")


# ── 조건 (Given): 오늘 기온 저장소 ───────────────────────────────────────────
@given(parsers.parse('저장소에 오늘 날짜로 최고 {high:f}도, 최저 {low:f}도, 오전 "{am}", 오후 "{pm}" 이 저장되어 있다'))
def stored_today(coord, high, low, am, pm):
    coord._store.async_load.return_value = {
        "date": today_text(), "max": high, "min": low, "wf_am": am, "wf_pm": pm}


@given(parsers.parse("저장소에 2020년 1월 1일 날짜로 최고 {high:f}도, 최저 {low:f}도가 저장되어 있다"))
def stored_other_day(coord, high, low):
    coord._store.async_load.return_value = {"date": "20200101", "max": high, "min": low}


@given(parsers.parse('저장소에 오늘 날짜로 최고 "{high}", 최저 {low:f}도가 저장되어 있다'))
def stored_broken(coord, high, low):
    coord._store.async_load.return_value = {"date": today_text(), "max": high, "min": low}


@given("저장소가 비어 있다")
def store_empty(coord):
    coord._store.async_load.return_value = None


@given(parsers.parse('오늘 날짜가 2025년 6월 1일이고 최고 {high:f}도, 최저 {low:f}도, 오전 "{am}", 오후 "{pm}" 이다'))
def daily_state(coord, high, low, am, pm):
    coord._daily_date = date(2025, 6, 1)
    coord._daily_max_temp, coord._daily_min_temp = high, low
    coord._wf_am_today, coord._wf_pm_today = am, pm


@given("오늘 날짜가 아직 정해지지 않았다")
def no_daily_date(coord):
    coord._daily_date = None


# ── 조건 (Given): 측정소 저장소 ──────────────────────────────────────────────
@given(parsers.parse('저장소에 측정소 "{name}", 위도 {lat:f}, 경도 {lon:f} 이 저장되어 있다'))
def stored_station(coord, name, lat, lon):
    coord._station_store.async_load.return_value = {"station": name, "lat": lat, "lon": lon}


@given("측정소 저장소가 비어 있다")
def station_store_empty(coord):
    coord._station_store.async_load.return_value = None


@given("측정소 저장소를 읽으면 오류가 난다")
def station_store_read_fails(coord):
    coord._station_store.async_load.side_effect = OSError("disk")


@given(parsers.parse('API 가 측정소 "{name}", 코드 "{code}", 위도 {lat:f}, 경도 {lon:f} 을 알고 있다'))
def api_knows_station(coord, name, code, lat, lon):
    api = coord.api
    api._cached_station, api._cached_station_code = name, code
    api._cached_station_lat, api._cached_station_lon = lat, lon


@given("API 가 측정소를 아직 모른다")
def api_knows_no_station(coord):
    coord.api._cached_station = None


@given("측정소 저장소에 쓰면 오류가 난다")
def station_store_write_fails(coord):
    coord._station_store.async_save.side_effect = OSError("disk")


# ── 만일 (When) ──────────────────────────────────────────────────────────────
@when("오늘 기온을 복구한다")
def restore_daily(coord, run):
    run(coord._restore_daily_temps())


@when("오늘 기온을 두 번 복구한다")
def restore_daily_twice(coord, run):
    run(coord._restore_daily_temps())
    run(coord._restore_daily_temps())


@when("오늘 기온을 저장한다")
def save_daily(coord, run):
    run(coord._save_daily_temps())


@when("측정소 정보를 복구한다")
def restore_station(coord, run):
    run(coord._restore_station_cache())


@when("측정소 정보를 두 번 복구한다")
def restore_station_twice(coord, run):
    run(coord._restore_station_cache())
    run(coord._restore_station_cache())


@when("측정소 정보를 저장한다")
def save_station(coord, run, outcome):
    try:
        run(coord._save_station_cache())
    except Exception as err:  # 오류 없이 끝나는지 '그러면' 단계에서 확인한다
        outcome["error"] = err


# ── 그러면 (Then): 오늘 기온 ─────────────────────────────────────────────────
@then(parsers.parse("오늘 최고기온은 {high:f}도, 최저기온은 {low:f}도이다"))
def daily_values(coord, high, low):
    assert (coord._daily_max_temp, coord._daily_min_temp) == (high, low)


@then(parsers.parse('오늘 날씨는 오전 "{am}", 오후 "{pm}" 이다'))
def daily_weather(coord, am, pm):
    assert (coord._wf_am_today, coord._wf_pm_today) == (am, pm)


@then("오늘 최고기온과 최저기온은 비어 있다")
def daily_empty(coord):
    assert coord._daily_max_temp is None and coord._daily_min_temp is None


@then("복구 시도는 끝난 것으로 표시된다")
def restore_done(coord):
    assert coord._store_loaded is True


@then("저장소는 한 번만 읽혔다")
def store_read_once(coord):
    coord._store.async_load.assert_called_once()


@then(parsers.parse('저장소에는 날짜 "{day}", 최고 {high:f}, 최저 {low:f} 이 기록된다'))
def saved_daily(coord, day, high, low):
    saved = coord._store.async_save.call_args.args[0]
    assert (saved["date"], saved["max"], saved["min"]) == (day, high, low)


@then("저장소에는 아무것도 기록되지 않는다")
def nothing_saved_daily(coord):
    coord._store.async_save.assert_not_called()


# ── 그러면 (Then): 측정소 ────────────────────────────────────────────────────
@then(parsers.parse('API 의 측정소는 "{name}", 위도 {lat:f}, 경도 {lon:f} 이다'))
def restored_station(coord, name, lat, lon):
    api = coord.api
    assert (api._cached_station, api._cached_station_lat, api._cached_station_lon) == (name, lat, lon)


@then("API 의 측정소는 비어 있다")
def restored_no_station(coord):
    assert coord.api._cached_station is None


@then("측정소 저장소는 한 번만 읽혔다")
def station_store_read_once(coord):
    coord._station_store.async_load.assert_called_once()


@then("측정소 복구 시도는 끝난 것으로 표시된다")
def station_restore_done(coord):
    assert coord._station_store_loaded is True


@then(parsers.parse('측정소 저장소에 "{name}", "{code}", {lat:f}, {lon:f} 이 기록된다'))
def saved_station(coord, name, code, lat, lon):
    assert coord._station_store.async_save.call_args.args[0] == {
        "station": name, "station_code": code, "lat": lat, "lon": lon}


@then("측정소 저장소에는 아무것도 기록되지 않는다")
def nothing_saved_station(coord):
    coord._station_store.async_save.assert_not_called()


@then("오류 없이 끝난다")
def finished_without_error(outcome):
    assert outcome["error"] is None
