"""BDD: 단기·중기 예보의 연속성 — features/forecast_continuity.feature"""
import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from testkit.factories import kst
from testkit.forecasts import (
    daily_entry, empty_mid, make_api, mid_response, short_response, short_three_hourly)
from testkit.keywords import World

scenarios("features/forecast_continuity.feature")

NOW = kst(2026, 4, 11, 10, 0)


@pytest.fixture
def world():
    api = make_api()
    return World(api=api, now=NOW, mid=None, tm_fc=api._get_mid_base_dt(NOW))


# ── 조건 (Given) ─────────────────────────────────────────────────────────────
@given(parsers.parse("오전 10시에 받은 단기예보 {days:d}일치가 있다"))
def short_forecast(world, days):
    world.short = short_three_hourly(NOW, days=days)


@given("모든 항목이 비어 있는 중기예보가 있다")
def empty_mid_forecast(world):
    world.mid = empty_mid(world.tm_fc)


@given("정상 중기예보가 있다")
def normal_mid_forecast(world):
    world.mid = mid_response(world.tm_fc, start_idx=3, end_idx=10)


@given("5일 뒤부터만 있는 중기예보가 있다")
def mid_from_day_5(world):
    world.mid = mid_response(world.tm_fc, start_idx=5, end_idx=10)


@given("오후 3시(15시)에 받은 단기예보에서 15시 슬롯만 비가 오고 나머지 낮 시간은 맑다")
def rain_only_at_15(world):
    world.now = kst(2026, 4, 11, 15, 0)
    world.short = short_response(
        world.now, days=4, slots=range(24),
        values=lambda d, h: {"TMP": 20, "SKY": 1, "PTY": 1 if (d, h) == (0, 15) else 0,
                             "REH": 50, "WSD": 2.0, "POP": 10})


# ── 만일 (When) ──────────────────────────────────────────────────────────────
@when("예보를 병합한다")
@when("오후 3시에 예보를 병합한다")
def merge(world):
    world.result = world.api._merge_all(world.now, world.short, world.mid, {})


# ── 그러면 (Then) ────────────────────────────────────────────────────────────
@then(parsers.parse("일 예보 항목은 {count:d}개이다"))
def daily_count(world, count):
    assert len(world.result["weather"]["forecast_daily"]) == count


@then("일 예보의 일차 번호는 0부터 9까지이다")
def day_indices(world):
    assert [e["_day_index"] for e in world.result["weather"]["forecast_daily"]] == list(range(10))


@then("D+0부터 D+5까지 최고기온과 최저기온이 모두 채워져 있다")
def no_gap(world):
    for day in range(6):
        entry = daily_entry(world.result, day)
        assert entry["native_temperature"] is not None and entry["native_templow"] is not None


@then("D+4의 최고기온은 채워져 있다")
def day4_filled(world):
    assert daily_entry(world.result, 4)["native_temperature"] is not None


@then(parsers.parse('현재 날씨는 "{condition}"이다'))
def current_condition(world, condition):
    assert world.result["weather"]["current_condition_kor"] == condition


@then(parsers.parse('오늘 오후 요약 날씨는 "{condition}"가 아니다'))
@then(parsers.parse('오늘 오후 요약 날씨는 "{condition}"이 아니다'))
def afternoon_summary_differs(world, condition):
    assert world.result["weather"]["wf_pm_today"] != condition
