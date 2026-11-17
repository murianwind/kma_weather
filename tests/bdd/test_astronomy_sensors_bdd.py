"""BDD: 천문·꽃가루 센서 — features/astronomy_sensors.feature (실제 Home Assistant + skyfield)"""
import re
from unittest.mock import AsyncMock, patch

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from custom_components.kma_weather.const import DOMAIN
from custom_components.kma_weather.coordinator import KMAWeatherUpdateCoordinator
from testkit.aio import run_on
from testkit.astro import needs_skyfield

scenarios("features/astronomy_sensors.feature")
pytestmark = needs_skyfield

MOON_PHASES = {"삭", "초승달", "상현달", "준상현달", "보름달", "준하현달", "하현달", "그믐달"}
OBSERVATION_GRADES = {"최우수", "우수", "보통", "불량", "관측불가", "분석불가"}
FORMATS = {
    "오늘/내일 HH:MM": lambda text: re.fullmatch(r"(오늘|내일) ([01]\d|2[0-3]):[0-5]\d", text) is not None,
    "달 위상 8단계": lambda text: text in MOON_PHASES,
    "0~100 정수": lambda text: text.isdigit() and 0 <= int(text) <= 100,
    "관측 조건 등급": lambda text: text in OBSERVATION_GRADES,
}
NO_POLLEN = {"weather": {"address": "경기도 화성시", "forecast_twice_daily": []}, "air": {}}
WITH_POLLEN = {**NO_POLLEN, "pollen": {"oak": "좋음", "pine": "좋음", "grass": "좋음", "worst": "좋음"}}


@pytest.fixture
def world():
    return {}


def setup_entry(hass, entry):
    async def setup():
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    entry.add_to_hass(hass)
    run_on(hass, setup())
    return hass.data[DOMAIN][entry.entry_id]


def refresh(hass, coordinator):
    async def go():
        await coordinator.async_refresh()
        await hass.async_block_till_done()
    run_on(hass, go())


# ── 조건 (Given) ─────────────────────────────────────────────────────────────
@given(parsers.parse("서울 노원({lat:f}, {lon:f})에 설정된 통합구성요소가 있다"))
def configured_integration(hass, mock_config_entry, kma_api_mock_factory, world, lat, lon):
    hass.config.latitude, hass.config.longitude = lat, lon
    kma_api_mock_factory("full_test")
    world["coordinator"] = setup_entry(hass, mock_config_entry)


@given("꽃가루 API 가 승인되지 않은 통합구성요소가 있다")
def without_pollen_approval(hass, mock_config_entry, world):
    hass.config.latitude, hass.config.longitude = 37.608, 127.094
    real_init = KMAWeatherUpdateCoordinator.__init__

    def init_without_approval(self, hass_arg, entry_arg):
        real_init(self, hass_arg, entry_arg)
        self.api._approved_apis = set()

    with patch.object(KMAWeatherUpdateCoordinator, "__init__", init_without_approval), \
         patch("custom_components.kma_weather.api_kma.KMAWeatherAPI.fetch_data",
               new_callable=AsyncMock, return_value=NO_POLLEN):
        world["coordinator"] = setup_entry(hass, mock_config_entry)


# ── 만일 (When) ──────────────────────────────────────────────────────────────
@when("센서를 한 번 갱신한다")
def refresh_once(hass, world):
    refresh(hass, world["coordinator"])


@when("꽃가루 API 가 승인되고 센서를 갱신한다")
def approve_pollen_and_refresh(hass, world):
    coordinator = world["coordinator"]
    coordinator.api._approved_apis = {"pollen"}
    with patch.object(coordinator.api, "fetch_data", new_callable=AsyncMock, return_value=WITH_POLLEN):
        refresh(hass, coordinator)


# ── 그러면 (Then) ────────────────────────────────────────────────────────────
@then("다음 센서들이 모두 등록되어 사용할 수 있다")
def sensors_registered(hass, datatable):
    for (name,) in datatable[1:]:
        state = hass.states.get(f"sensor.test_{name}")
        assert state is not None, f"센서 {name} 미등록"
        assert state.state != "unavailable", f"센서 {name} 사용 불가"


@then(parsers.parse('센서 "{name}" 의 상태는 "{form}" 이다'))
def sensor_state_format(hass, name, form):
    state = hass.states.get(f"sensor.test_{name}")
    assert state is not None
    assert FORMATS[form](state.state), f"{name}={state.state!r} 가 형식 '{form}' 이 아님"


@then('관측 조건 센서에는 "주야간"과 "날씨" 속성이 있다')
def observation_attributes(hass):
    attributes = hass.states.get("sensor.test_observation_condition").attributes
    assert "주야간" in attributes and "날씨" in attributes


@then('관측 조건 센서의 주야간 속성은 "주간" 또는 "야간" 이다')
def observation_day_night(hass):
    assert hass.states.get("sensor.test_observation_condition").attributes["주야간"] in ("주간", "야간")


@then(parsers.parse('꽃가루 센서의 상태는 "{grade}" 이다'))
def pollen_state(hass, grade):
    state = hass.states.get("sensor.test_pollen")
    assert state is not None and state.state == grade


@then('꽃가루 센서에는 "참나무", "소나무", "잡초류" 속성이 있다')
def pollen_attributes(hass):
    attributes = hass.states.get("sensor.test_pollen").attributes
    assert all(key in attributes for key in ("참나무", "소나무", "잡초류"))


@then("꽃가루 센서는 만들어지지 않았다")
def no_pollen_sensor(hass):
    assert hass.states.get("sensor.test_pollen") is None
