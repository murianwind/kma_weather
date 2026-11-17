"""BDD: 현재 예상 강수량 센서의 오늘 하루 시간대별 속성 — features/precip_hourly.feature"""
import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from testkit.factories import kst, make_api, short_forecast
from testkit.keywords import World

scenarios("features/precip_hourly.feature")

TODAY = kst(2026, 10, 19, 0)


@pytest.fixture
def world():
    return World(pcp_today={}, pcp_tomorrow={})


def _hour(token):
    """'15시' → 15"""
    return int(token.removesuffix("시"))


def _value(text):
    """따옴표 안의 값: 숫자면 수로, 아니면 문자열 그대로."""
    try:
        return float(text)
    except ValueError:
        return text


# ── 조건 (Given) ─────────────────────────────────────────────────────────────
@given("오늘과 내일의 단기예보가 있다")
def baseline_forecast(world):
    pass  # 별도 값이 없으면 모든 시각이 '강수없음'인 이틀치 예보가 만들어진다


@given(parsers.parse('15시는 "{a}", 16시는 "{b}", 17시는 "{c}", 18시는 "{d}"으로 예보되어 있다'))
@given(parsers.parse('15시는 "{a}", 16시는 "{b}", 17시는 "{c}", 18시는 "{d}"로 예보되어 있다'))
def hourly_values(world, a, b, c, d):
    world.pcp_today = {15: a, 16: b, 17: c, 18: d}


@given(parsers.parse('내일 {hour}는 "{raw}"로 예보되어 있다'))
def tomorrow_value(world, hour, raw):
    world.pcp_tomorrow = {_hour(hour): raw}


# ── 만일 (When) ──────────────────────────────────────────────────────────────
@when(parsers.parse("{hhmm}에 센서를 갱신한다"))
def refresh(world, hhmm):
    hour, minute = map(int, hhmm.split(":"))
    now = kst(2026, 10, 19, hour, minute)
    response = short_forecast(TODAY, days=2, pcp_by_hour=world.pcp_today)
    for item in response["response"]["body"]["items"]["item"]:
        if item["fcstDate"] == "20261020" and item["category"] == "PCP":
            raw = world.pcp_tomorrow.get(int(item["fcstTime"][:2]))
            if raw:
                item["fcstValue"] = raw
    world.hourly = make_api()._merge_all(now, response, None, {})["weather"]["hourly_precipitation_mm"]
    world.now = now


# ── 그러면 (Then) ────────────────────────────────────────────────────────────
@then(parsers.parse('속성 키는 "00시"부터 "23시"까지 시간 순서로 24개이다'))
def keys_whole_day(world):
    assert list(world.hourly) == [f"{h:02d}시" for h in range(24)]


@then(parsers.parse('"{hour}"까지는 "-"이다'))
def dashes_until(world, hour):
    assert all(world.hourly[f"{h:02d}시"] == "-" for h in range(_hour(hour) + 1))


@then("그 다음 시간부터 예보 값이 보인다")
def values_after(world):
    first_future = world.now.hour + 1
    future = [world.hourly[f"{h:02d}시"] for h in range(first_future, 24)]
    assert all(value == 0 for value in future)  # 모든 시각이 '강수없음'(0)으로 예보됨


@then(parsers.parse('"{hour}"는 {value}이다'))
def hour_value(world, hour, value):
    assert world.hourly[hour] == _value(value.strip('"'))
