"""BDD: 구역코드·좌표가 각 조회로 전달되는 배선 — features/fetch_wiring.feature"""
import logging

import pytest
from unittest.mock import AsyncMock
from pytest_bdd import given, parsers, scenarios, then, when

from custom_components.kma_weather import coordinator as coordinator_module
from testkit.aio import run
from testkit.factories import kst, make_api, make_coordinator
from testkit.keywords import World

scenarios("features/fetch_wiring.feature")


@pytest.fixture
def world(caplog):
    coordinator_module._load_area_data()
    return World(calls={}, caplog=caplog)


# ── 조건 (Given) ─────────────────────────────────────────────────────────────
@given(parsers.parse("서울 중랑구({lat:f}, {lon:f})에 있는 기기가 있다"))
def device_in_jungnang(world, lat, lon):
    coord = make_coordinator(location_entity="zone.home", location=(lat, lon))
    coord._cached_data = {"weather": {}, "air": {}}

    async def fake_fetch_data(reg_id_temp, reg_id_land, warn_area_code, **_):
        world.calls.update(temp=reg_id_temp, land=reg_id_land, warn=warn_area_code)
        return None

    coord.api.fetch_data = fake_fetch_data
    world.coord = coord


@given("모든 조회가 가짜로 대체된 API 가 있다")
def stubbed_api(world):
    api = make_api()
    announced = kst(2026, 4, 11, 6)

    async def mid_term(now, reg_id_temp, reg_id_land):
        world.calls.update(mid=(reg_id_temp, reg_id_land))
        return (None, None, announced)

    async def air(lat, lon):
        world.calls["air"] = (lat, lon)
        return {}

    async def warning(warn_area_code):
        world.calls["warning"] = warn_area_code
        return world.warning_text

    world.warning_text = "없음"
    api._get_short_term = AsyncMock(return_value=None)
    api._get_mid_term, api._get_air_quality, api._get_warning = mid_term, air, warning
    api._get_address = AsyncMock(return_value="서울시")
    api._get_pollen = AsyncMock(return_value={})
    world.api = api


@given(parsers.parse('기상특보 조회는 "{text}"를 돌려준다'))
def warning_returns(world, text):
    world.warning_text = text


@given(parsers.parse('꽃가루 조회는 등급 "{grade}"을 돌려준다'))
def pollen_returns(world, grade):
    async def pollen(now, area_no, area_name):
        world.calls["pollen"] = (area_no, area_name)
        return {"worst": grade}
    world.api._get_pollen = pollen


@given("주소 조회 중 예외가 발생한다")
def address_raises(world):
    world.api._get_address = AsyncMock(side_effect=Exception("boom"))


# ── 만일 (When) ──────────────────────────────────────────────────────────────
def fetch(world, **overrides):
    args = dict(lat=37.56, lon=126.98, nx=60, ny=127, reg_id_temp="11B10101", reg_id_land="11B00000",
                warn_area_code="L1100200", pollen_area_no="", pollen_area_name="")
    world.data = run(world.api.fetch_data(**{**args, **overrides}))


@when("업데이트가 실행된다")
def update(world):
    run(world.coord._async_update_data())


@when(parsers.parse('기온구역 "{temp}", 육상구역 "{land}"으로 데이터를 가져온다'))
def fetch_with_reg_ids(world, temp, land):
    fetch(world, reg_id_temp=temp, reg_id_land=land)


@when(parsers.parse('특보구역 "{code}"으로 데이터를 가져온다'))
def fetch_with_warn_code(world, code):
    fetch(world, warn_area_code=code)


@when(parsers.parse('꽃가루 지역 "{area_no}", 이름 "{area_name}"로 데이터를 가져온다'))
def fetch_with_pollen_area(world, area_no, area_name):
    fetch(world, pollen_area_no=area_no, pollen_area_name=area_name)


@when(parsers.parse("위도 {lat:f}, 경도 {lon:f}로 데이터를 가져온다"))
def fetch_with_position(world, lat, lon):
    fetch(world, lat=lat, lon=lon)


# ── 그러면 (Then) ────────────────────────────────────────────────────────────
@then(parsers.parse('API 에는 기온구역 "{temp}", 육상구역 "{land}", 특보구역 "{warn}"이 전달된다'))
def area_codes_passed(world, temp, land, warn):
    assert (world.calls["temp"], world.calls["land"], world.calls["warn"]) == (temp, land, warn)


@then(parsers.parse('중기예보 조회에 기온구역 "{temp}", 육상구역 "{land}"이 전달된다'))
def mid_term_args(world, temp, land):
    assert world.calls["mid"] == (temp, land)


@then(parsers.parse('기상특보 조회에 "{code}"이 전달된다'))
def warning_arg(world, code):
    assert world.calls["warning"] == code


@then(parsers.parse('가져온 데이터의 기상특보는 "{text}"이다'))
def fetched_warning(world, text):
    assert world.data["weather"]["warning"] == text


@then(parsers.parse("대기질 조회에 위도 {lat:f}, 경도 {lon:f}이 전달된다"))
def air_args(world, lat, lon):
    assert world.calls["air"] == pytest.approx((lat, lon))


@then(parsers.parse('꽃가루 조회에 지역 "{area_no}", 이름 "{area_name}"이 전달된다'))
def pollen_args(world, area_no, area_name):
    assert world.calls["pollen"] == (area_no, area_name)


@then(parsers.parse('가져온 데이터의 꽃가루 최악 등급은 "{grade}"이다'))
def fetched_pollen(world, grade):
    assert world.data["pollen"]["worst"] == grade


@then("가져온 데이터는 없다")
def no_data(world):
    assert world.data is None


@then("ERROR 로그가 한 건 남는다")
def one_error_log(world):
    assert len([r for r in world.caplog.records if r.levelno == logging.ERROR]) == 1
