"""BDD: 통합구성요소의 센서·예보 출력 — features/integration_sensors.feature
실제 Home Assistant 에 구성요소를 등록한다. pytest-bdd 는 async 스텝을 실행하지 않으므로 스텝은 동기 함수이고
코루틴은 testkit.aio.run_on(hass, ...) 으로 돌린다."""
from unittest.mock import AsyncMock, patch

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from custom_components.kma_weather.const import DOMAIN
from custom_components.kma_weather.sensor import SENSOR_TYPES
from testkit.aio import run_on
from testkit.keywords import World
from conftest import MOCK_SCENARIOS

scenarios("features/integration_sensors.feature")

PREFIX = "test"
# 오염 데이터에서도 unknown 을 기대하지 않는 센서: 이전 캐시로 복원되는 실시간 값, 좌표로 계산되는 천문 값, 항상 값이 있는 센서
SKIP_UNKNOWN = {
    "TMP", "REH", "WSD", "VEC_KOR", "POP", "apparent_temp",
    "dawn", "sunrise", "sunset", "dusk", "astro_dawn", "astro_dusk",
    "moon_phase", "moon_illumination", "moonrise", "moonset",
    "observation_condition", "pollen", "api_calls_today",
}
NEVER_CHECKED = {"last_updated", "api_expire"}
API_KEYS = ["단기예보", "중기예보", "에어코리아_측정소", "에어코리아_대기", "기상특보", "꽃가루"]


@pytest.fixture
def world():
    return World()


def sensor(hass, suffix):
    return hass.states.get(f"sensor.{PREFIX}_{suffix}")


# ── 조건 (Given) ─────────────────────────────────────────────────────────────
@given("서울 좌표에 정상 데이터(full_test)로 통합구성요소가 등록되어 있다")
def integration_loaded(hass, mock_config_entry, kma_api_mock_factory, world):
    hass.config.latitude, hass.config.longitude = 37.56, 126.98
    world.factory = kma_api_mock_factory
    kma_api_mock_factory("full_test")
    mock_config_entry.add_to_hass(hass)

    async def setup():
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    run_on(hass, setup())
    world.coordinator = hass.data[DOMAIN][mock_config_entry.entry_id]
    world.entry = mock_config_entry


# ── 만일 (When) ──────────────────────────────────────────────────────────────
@when("센서 상태를 읽는다")
def read_sensors(hass):
    run_on(hass, hass.async_block_till_done())


@when("하루 두 번 예보를 요청한다")
def request_forecast(hass, world):
    response = run_on(hass, hass.services.async_call(
        "weather", "get_forecasts", {"type": "twice_daily"},
        target={"entity_id": f"weather.{PREFIX}_weather"}, blocking=True, return_response=True))
    world.forecast = response[f"weather.{PREFIX}_weather"]["forecast"]


@when("기기가 부산으로 이동해 위치 정보가 갱신된다")
def device_moves_to_busan(hass, world):
    busan = {**MOCK_SCENARIOS["full_test"],
             "weather": {**MOCK_SCENARIOS["full_test"]["weather"], "address": "부산광역시", "현재 위치": "부산광역시"}}

    async def move():
        with patch("custom_components.kma_weather.api_kma.KMAWeatherAPI.fetch_data",
                   new_callable=AsyncMock, return_value=busan):
            hass.states.async_set("device_tracker.my_phone", "home", {"latitude": 35.1, "longitude": 129.0})
            await hass.async_block_till_done()
            await world.coordinator.async_refresh()
            await hass.async_block_till_done()
    run_on(hass, move())


@when("데이터가 누락된 응답(jeju_missing)으로 갱신한다")
def refresh_with_missing(hass, world):
    world.factory("jeju_missing")
    run_on(hass, world.coordinator.async_refresh())
    run_on(hass, hass.async_block_till_done())


@when("정상 데이터(full_test)로 다시 갱신한다")
def refresh_with_full(hass, world):
    world.factory("full_test")
    run_on(hass, world.coordinator.async_refresh())
    run_on(hass, hass.async_block_till_done())


@when(parsers.parse('모든 값이 "{bad}"인 응답으로 갱신한다'))
def refresh_with_polluted(hass, world, bad):
    payload = {"weather": {key: bad for key in SENSOR_TYPES}, "air": {key: bad for key in SENSOR_TYPES}, "pollen": {}}

    async def refresh():
        with patch("custom_components.kma_weather.api_kma.KMAWeatherAPI.fetch_data",
                   new_callable=AsyncMock, return_value=payload):
            await world.coordinator.async_refresh()
            await hass.async_block_till_done()
    run_on(hass, refresh())
    world.states = {key: sensor(hass, details[4]) for key, details in SENSOR_TYPES.items()}


# ── 그러면 (Then) ────────────────────────────────────────────────────────────
@given(parsers.re(r'"(?P<suffix>[^"]+)" 센서는 "(?P<state>[^"]+)"이다'))
@then(parsers.re(r'"(?P<suffix>[^"]+)" 센서는 "(?P<state>[^"]+)"이다'))
def sensor_state(hass, suffix, state):
    assert sensor(hass, suffix).state == state


@then(parsers.parse('"{suffix}" 센서는 "{state}"이고 단위는 "{unit}", 종류는 "{device_class}"이다'))
def sensor_state_unit_class(hass, suffix, state, unit, device_class):
    current = sensor(hass, suffix)
    assert (current.state, current.attributes.get("unit_of_measurement"),
            current.attributes.get("device_class")) == (state, unit, device_class)


@then(parsers.parse('"{suffix}" 센서는 "{state}"이고 단위는 "{unit}", 아이콘은 "{icon}"이다'))
def sensor_state_unit_icon(hass, suffix, state, unit, icon):
    current = sensor(hass, suffix)
    assert (current.state, current.attributes.get("unit_of_measurement"),
            current.attributes.get("icon")) == (state, unit, icon)


@then(parsers.parse('"{suffix}" 센서는 양수이다'))
def sensor_positive(hass, suffix):
    assert float(sensor(hass, suffix).state) > 0  # 풍속은 HA 단위계(km/h)로 자동 변환되므로 값 대신 부호만 확인


@then(parsers.parse("예보는 {count:d}개 이상이다"))
def forecast_count(world, count):
    assert len(world.forecast) >= count


@then("첫 예보에는 기온과 날씨 상태가 있다")
def first_forecast(world):
    first = world.forecast[0]
    assert first["temperature"] is not None and first["condition"] is not None


@then("어떤 센서도 unavailable 이 아니다")
def none_unavailable(world):
    assert all(state.state != "unavailable" for key, state in world.states.items()
               if state and key not in NEVER_CHECKED)


@then("API 값에 의존하는 단위 있는 센서는 unknown 이다")
def dependent_sensors_unknown(world):
    for key, details in SENSOR_TYPES.items():
        state = world.states[key]
        if state and key not in NEVER_CHECKED | SKIP_UNKNOWN and details[1] is not None:
            assert state.state == "unknown", f"{key}: {state.state}"


@then(parsers.parse('"{suffix}" 센서의 속성은 다음과 같다'))
def sensor_attributes(hass, suffix, datatable):
    attributes = sensor(hass, suffix).attributes
    print('DT', datatable, dict(attributes))
    for name, value in datatable[1:]:
        assert str(attributes.get(name)) == value, f"{name}: {attributes.get(name)!r}"


@then("API 호출 횟수 센서에 모든 API 별 속성과 집계일이 있다")
def api_calls_attributes(hass):
    attributes = sensor(hass, "api_calls_today").attributes
    assert all(attributes.get(key) == 0 for key in API_KEYS) and "집계일" in attributes
