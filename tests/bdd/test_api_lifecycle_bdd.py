"""BDD: API 중지·재개에 따른 업데이트 동작 — features/api_lifecycle.feature"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from pytest_bdd import given, parsers, scenarios, then, when

from custom_components.kma_weather import coordinator as coordinator_module
from custom_components.kma_weather.sensor import KMACustomSensor
from testkit.aio import run
from testkit.factories import make_coordinator
from testkit.keywords import World

scenarios("features/api_lifecycle.feature")


@pytest.fixture
def world():
    coordinator_module._load_area_data()  # 구역코드 표 (정적 데이터)
    return World()


def stopped_payload(flag):
    return {"weather": {}, "air": {}, "pollen": None, "raw_forecast": {}, flag: True}


# ── 조건 (Given) ─────────────────────────────────────────────────────────────
@given("기기가 있고 단기예보와 중기예보가 승인된 상태이다")
def device_approved(world):
    world.coord = make_coordinator(location_entity="zone.home", location=(37.5, 127.0))
    world.coord.api._approved_apis, world.coord.api._pending_apis = {"short", "mid"}, set()


@given("기기가 있고 단기예보와 중기예보가 신청 대기 상태이다")
def device_pending(world):
    world.coord = make_coordinator(location_entity="zone.home", location=(37.5, 127.0))
    world.coord.api._approved_apis, world.coord.api._pending_apis = set(), {"short", "mid"}
    world.coord._cached_data = {"weather": {}, "air": {}, "pollen": None}


@given("이전에 받은 기온 20도 데이터가 캐시되어 있다")
def cached_data(world):
    world.coord._cached_data = {"weather": {"TMP": 20}, "air": {}, "pollen": None}
    world.coord.api._cache_forecast_map = {"20260411": {"1000": {"TMP": "20"}}}


@given(parsers.parse("이번 업데이트에서 {api} 가 미신청으로 판정된다"))
def api_unsubscribed(world, api):
    flag = {"단기예보": "_short_unsubscribed", "중기예보": "_mid_unsubscribed"}[api]
    world.coord.api.fetch_data = AsyncMock(return_value=stopped_payload(flag))


@given(parsers.parse("이번 업데이트에서 API 가 기온 {temp:d}도 정상 응답을 준다"))
def api_ok(world, temp):
    world.coord.api.fetch_data = AsyncMock(return_value={
        "weather": {"TMP": temp, "current_condition": "sunny"}, "air": {}, "pollen": {}, "raw_forecast": {}})


@given(parsers.parse('중지된 API 로 "{name}"가 기록되어 있다'))
def stopped_recorded(world, name):
    coord = MagicMock()
    coord.data = {"weather": {}, "air": {}, "pollen": None}
    coord.api._approved_apis = set()
    coord._shared_counts = {"단기예보": 5, "중기예보": 3, "에어코리아_측정소": 2, "에어코리아_대기": 2,
                            "기상특보": 2, "꽃가루": 1, "date": "20260428",
                            "last_reason": "자동 업데이트", "api_중지": name}
    coord.api_call_total = MagicMock(return_value=15)
    world.sensor_coordinator = coord


# ── 만일 (When) ──────────────────────────────────────────────────────────────
@when("업데이트가 실행된다")
def update(world):
    world.result = run(world.coord._async_update_data())


@when("API 호출 횟수 센서의 속성을 읽는다")
def read_attributes(world):
    with patch.object(CoordinatorEntity, "available", new_callable=lambda: property(lambda self: True)):
        sensor = KMACustomSensor(world.sensor_coordinator, "api_calls_today", "kma", MagicMock())
        world.attrs = sensor.extra_state_attributes


# ── 그러면 (Then) ────────────────────────────────────────────────────────────
@then("예보 캐시는 비워진다")
def forecast_cache_cleared(world):
    assert world.coord.api._cache_forecast_map == {}


@then("센서 데이터는 비어 있다")
def weather_empty(world):
    assert world.result.get("weather") == {}


@then(parsers.parse('중지된 API 로 "{name}"가 기록된다'))
def stopped_recorded_then(world, name):
    assert world.coord._shared_counts.get("api_중지") == name


@then(parsers.parse("센서 데이터의 기온은 {temp:d}도이다"))
def temperature(world, temp):
    assert world.result["weather"]["TMP"] == temp


@then(parsers.parse('"API_중지_감지" 속성에 "{name}"가 들어 있다'))
def stopped_attribute(world, name):
    assert name in world.attrs["API_중지_감지"]
