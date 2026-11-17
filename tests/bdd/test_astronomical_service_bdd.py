"""BDD: 날짜를 정해 조회하는 천문 계산과 서비스 — features/astronomical_service.feature (실제 Home Assistant + skyfield)"""
import re
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.exceptions import HomeAssistantError
from pytest_bdd import given, parsers, scenarios, then, when

from custom_components.kma_weather.const import DOMAIN
from custom_components.kma_weather.coordinator import KMAWeatherUpdateCoordinator
from testkit.aio import run_on
from testkit.astro import needs_skyfield

scenarios("features/astronomical_service.feature")
pytestmark = needs_skyfield

KST = ZoneInfo("Asia/Seoul")


def today_kst():
    """서비스와 같은 기준(한국 시간)의 오늘 날짜."""
    return datetime.now(KST).date()


NO_SHORT = {"weather": {"address": "경기도 화성시", "forecast_twice_daily": []}, "air": {}}


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


def forecast_response(*slots):
    """slots: (시각, 카테고리, 값) 목록 → 단기예보 응답 (오늘 날짜)."""
    today = today_kst().strftime("%Y%m%d")
    items = [{"fcstDate": today, "fcstTime": time, "category": category, "fcstValue": value}
             for time, category, value in slots]
    return {"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": items}}}}


# ── 조건 (Given) ─────────────────────────────────────────────────────────────
@given(parsers.parse("서울({lat:f}, {lon:f})의 천문 계산을 할 수 있는 통합구성요소가 있다"))
def integration_ready(hass, mock_config_entry, kma_api_mock_factory, world, lat, lon):
    kma_api_mock_factory("full_test")
    world["coordinator"] = setup_entry(hass, mock_config_entry)
    world["lat"], world["lon"] = lat, lon


@given("단기예보 API 가 승인되지 않은 통합구성요소가 있다")
def integration_without_short(hass, mock_config_entry, world):
    real_init = KMAWeatherUpdateCoordinator.__init__

    def init_without_approval(self, hass_arg, entry_arg):
        real_init(self, hass_arg, entry_arg)
        self.api._approved_apis = set()

    with patch.object(KMAWeatherUpdateCoordinator, "__init__", init_without_approval), \
         patch("custom_components.kma_weather.api_kma.KMAWeatherAPI.fetch_data",
               new_callable=AsyncMock, return_value=NO_SHORT):
        world["coordinator"] = setup_entry(hass, mock_config_entry)
    world["lat"], world["lon"] = 37.56, 126.98
    world["fetch_patch"] = patch.object(world["coordinator"].api, "_fetch", new_callable=AsyncMock)


def approve_short(world, response=None, error=None):
    coordinator = world["coordinator"]
    coordinator.api._approved_apis.add("short")
    world["fetch_patch"] = patch.object(coordinator.api, "_fetch", new_callable=AsyncMock,
                                        return_value=response, side_effect=error)


@given(parsers.parse("단기예보 API 가 승인되어 있고 낮 12시 예보가 하늘상태 {sky}, 강수형태 {pty} 이다"))
def short_with_sky_pty(world, sky, pty):
    approve_short(world, forecast_response(("1200", "SKY", sky), ("1200", "PTY", pty)))


@given("단기예보 API 가 승인되어 있고 낮 12시 예보에는 풍속이 없고 15시 예보에만 풍속 3.0 이 있다")
def short_wind_only_at_15(world):
    approve_short(world, forecast_response(
        ("1200", "SKY", "1"), ("1200", "PTY", "0"), ("1500", "WSD", "3.0")))


@given("단기예보 API 가 승인되어 있지만 조회하면 오류가 난다")
def short_fails(world):
    approve_short(world, error=Exception("네트워크 오류"))


# ── 만일 (When) ──────────────────────────────────────────────────────────────
def calculate(hass, world, eval_dt=None, target_date=None):
    async def go():
        return await world["coordinator"].calc_astronomical_for_date(
            lat=world["lat"], lon=world["lon"], target_date=target_date or today_kst(), eval_dt=eval_dt)
    fetch_patch = world.get("fetch_patch")
    if fetch_patch:
        with fetch_patch as spy:
            world["fetch_spy"] = spy
            world["result"] = run_on(hass, go())
    else:
        world["result"] = run_on(hass, go())


@when("오늘 날짜를 계산한다")
def calculate_today(hass, world):
    calculate(hass, world)


@when(parsers.parse("{day} 의 천문 정보를 계산한다"))
def calculate_given_day(hass, world, day):
    calculate(hass, world, target_date=date.fromisoformat(day))


@when("오늘 새벽 1시를 기준으로 계산한다")
def calculate_at_1am(hass, world):
    today = today_kst()
    calculate(hass, world, eval_dt=datetime(today.year, today.month, today.day, 1, 0, tzinfo=KST))


@when(parsers.parse('천문 서비스를 오늘 기준 {days:d}일, 시각 "{clock}" 으로 호출한다'))
def call_service(hass, world, days, clock):
    data = {"address": "경기도 화성시 동탄면", "date": today_kst() + timedelta(days=days)}
    if clock != "-":
        data["time"] = clock

    async def call():
        try:
            await hass.services.async_call(DOMAIN, "get_astronomical_info", data,
                                           blocking=True, return_response=True)
        except HomeAssistantError as err:
            return err
    world["error"] = run_on(hass, call())


# ── 그러면 (Then) ────────────────────────────────────────────────────────────
@then("오류 없이 결과에 다음 항목이 모두 있다")
def result_has_keys(world, datatable):
    assert "error" not in world["result"], world["result"].get("error")
    for (key,) in datatable[1:]:
        assert key in world["result"], f"결과에 '{key}' 없음"


@then(parsers.parse('날씨 출처는 "{source}" 이고 날씨는 "{weather}" 이다'))
def weather_source(world, source, weather):
    assert (world["result"]["weather_source"], world["result"]["weather_condition"]) == (source, weather)


@then(parsers.parse('오류 없이 관측 조건이 계산되고 주야간은 "{day_night}" 이다'))
def observation_at_night(world, day_night):
    assert "error" not in world["result"]
    assert world["result"]["observation_condition"]
    assert world["result"]["observation_attrs"]["주야간"] == day_night


@then(parsers.parse('관측 조건의 풍속은 "{wind}" 이다'))
def observation_wind(world, wind):
    assert world["result"]["observation_attrs"]["풍속"] == wind


@then(parsers.parse('"{phrase}" 가 담긴 오류가 난다'))
def service_error(world, phrase):
    assert world["error"] is not None, "오류가 나지 않음"
    assert phrase in str(world["error"])


@then(parsers.parse('달 위상은 "{phase}" 이고 달이 뜨는 시각은 {rise}, 지는 시각은 {sets} 이다'))
def moon_times(world, phase, rise, sets):
    result = world["result"]
    assert result["moon_phase"] == phase
    for key, expectation in (("moonrise", rise), ("moonset", sets)):
        value = result[key]
        if expectation == "있음":
            assert re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", value), f"{key}={value!r}"
        else:
            assert value is None, f"{key}={value!r}"


@then("단기예보는 조회하지 않았다")
def short_not_queried(world):
    assert world["fetch_spy"].await_count == 0
