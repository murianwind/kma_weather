"""BDD: 자외선지수 조회(_get_uv_index) — features/uv_query.feature"""
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from custom_components.kma_weather.api_kma import KMAWeatherAPI
from testkit.aio import run
from testkit.factories import kst
from testkit.keywords import World

scenarios("features/uv_query.feature")

AREA = "1111051500"
RESPONSES = {  # 장애·자료 없음·미신청 응답 모음
    "미신청(resultCode 30)": {"response": {"header": {
        "resultCode": "30", "resultMsg": "SERVICE_KEY_IS_NOT_REGISTERED_ERROR"}}},
    "자료 없음(resultCode 03)": {"response": {"header": {
        "resultCode": "03", "resultMsg": "NODATA_ERROR"}}},
    "HTTP 5xx 오류": {"_http_error": "504"},
}


def ok_response(h0="5", date="2026081606", **hours):
    item = {"code": "d", "areaNo": AREA, "date": date, "h0": h0, **hours}
    return {"response": {"header": {"resultCode": "00", "resultMsg": "NORMAL_SERVICE"},
                         "body": {"dataType": "JSON", "items": {"item": [item]},
                                  "pageNo": 1, "numOfRows": 1, "totalCount": 1}}}


@pytest.fixture
def world():
    api = KMAWeatherAPI(MagicMock(), "test_key")
    api.hass = None
    return World(api=api)


def at(hhmm):
    hour, minute = map(int, hhmm.split(":"))
    return kst(2026, 8, 16, hour, minute)


def forecast_hours(**overrides):
    """h3~h75 를 3시간마다 채운다 (값은 시간 % 12, overrides 로 일부를 바꿈)."""
    return {f"h{n}": overrides.get(f"h{n}", str(n % 12)) for n in range(3, 76, 3)}


# ── 조건 (Given) ─────────────────────────────────────────────────────────────
@given(parsers.parse('자외선지수 API 가 현재 지수 "{h0}"인 정상 응답을 준다'))
@given(parsers.parse('자외선지수 API 가 현재 지수 "{h0}"만 준다'))
def api_ok(world, h0):
    world.api._fetch = AsyncMock(return_value=ok_response(h0=h0))


@given(parsers.parse('자외선지수 API 가 현재 지수 "{h0}"이고 3시간 뒤부터 75시간 뒤까지 3시간마다 예측을 준다'))
def api_with_forecast(world, h0):
    world.api._fetch = AsyncMock(return_value=ok_response(h0=h0, **forecast_hours()))


@given(parsers.parse('자외선지수 API 가 3시간마다 예측을 주지만 {hours:d}시간 뒤 값은 "-"이다'))
def api_with_missing_value(world, hours):
    world.api._fetch = AsyncMock(
        return_value=ok_response(h0="7", **forecast_hours(**{f"h{hours}": "-"})))


@given("자외선지수 API 는 승인된 것으로 표시되어 있다")
def api_marked_approved(world):
    world.api._approved_apis.add("uv")


@given(parsers.parse('자외선지수 API 가 "{kind}" 응답을 준다'))
def api_special_response(world, kind):
    if kind == "네트워크 예외":
        world.api._fetch = AsyncMock(side_effect=Exception("network boom"))
    else:
        world.api._fetch = AsyncMock(return_value=RESPONSES[kind])


# ── 만일 (When) ──────────────────────────────────────────────────────────────
@when(parsers.parse('{hhmm}에 "{area_name}"의 자외선지수를 조회한다'))
def query(world, hhmm, area_name):
    world.result = run(world.api._get_uv_index(at(hhmm), AREA, area_name))


@when(parsers.parse("{hhmm}에 지역코드 없이 자외선지수를 조회한다"))
def query_without_area(world, hhmm):
    world.result = run(world.api._get_uv_index(at(hhmm), "", ""))


@when(parsers.parse('{hhmm}에 지역코드 "{area}"의 자외선지수를 조회한다'))
def query_with_area(world, hhmm, area):
    world.result = run(world.api._get_uv_index(at(hhmm), area, "청운효자동"))


# ── 그러면 (Then) ────────────────────────────────────────────────────────────
@then(parsers.parse('값은 "{value}"이고 등급은 "{grade}"이다'))
def value_and_grade(world, value, grade):
    assert (world.result["value"], world.result["grade"]) == (value, grade)


@then(parsers.parse('지역은 "{name}"이다'))
def area_name(world, name):
    assert world.result["area_name"] == name


@then(parsers.parse('발표 시각에는 "{text}"이 들어 있다'))
def announcement_contains(world, text):
    assert text in world.result["announcement"]


@then(parsers.parse("시간대별 값은 {count:d}개이다"))
def hourly_count(world, count):
    assert len(world.result["hourly"]) == count


@then(parsers.parse('시간대별 "{key}"는 {value:g}이다'))
def hourly_value(world, key, value):
    assert world.result["hourly"][key] == value


@then(parsers.parse('시간대별 "{key}"는 없다'))
def hourly_missing(world, key):
    assert key not in world.result["hourly"]


@then("결과는 없다")
def result_none(world):
    assert world.result is None


@then("결과는 빈 값이다")
def result_empty(world):
    assert world.result == {}


@then("API 는 호출되지 않았다")
def api_not_called(world):
    world.api._fetch.assert_not_called()


@then("자외선지수 API 는 승인된 것으로 표시된다")
def marked_approved(world):
    assert "uv" in world.api._approved_apis


@then("자외선지수 API 는 승인되지 않은 것으로 표시된다")
def marked_unapproved(world):
    assert "uv" not in world.api._approved_apis


@then(parsers.parse('요청한 발표 시각은 "{base_time}"이다'))
def requested_base_time(world, base_time):
    assert world.api._fetch.call_args.args[1]["time"] == base_time


@then(parsers.parse('요청한 지역코드는 "{area}"이다'))
def requested_area(world, area):
    assert world.api._fetch.call_args.args[1]["areaNo"] == area
