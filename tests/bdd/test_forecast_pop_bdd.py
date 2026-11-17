"""BDD: 예보의 강수확률 — features/forecast_pop.feature"""
import re

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from testkit.factories import kst
from testkit.forecasts import (
    daily_entry, make_api, mid_response, short_all_hours, twice_daily_entry)
from testkit.keywords import World

scenarios("features/forecast_pop.feature")

NOW = kst(2026, 7, 7, 6, 0)
DAY_OFFSETS = {"오늘": 0, "내일": 1}


def day_index(label):
    return DAY_OFFSETS[label] if label in DAY_OFFSETS else int(label.removesuffix("일 뒤"))


def pop_by_hour(text):
    """'00~11시 20, 12~23시 70' → {0: 20, ..., 23: 70}"""
    pops = {}
    for part in text.split(","):
        first, last, value = re.fullmatch(r"\s*(\d+)~(\d+)시 (\d+)\s*", part).groups()
        pops.update({hour: int(value) for hour in range(int(first), int(last) + 1)})
    return pops


@pytest.fixture
def world():
    return World(api=make_api(), mid=None)


# ── 조건 (Given) ─────────────────────────────────────────────────────────────
@given(parsers.parse('06시에 받은 단기예보 4일치가 있고 시각별 강수확률은 "{ranges}"이다'))
def short_forecast(world, ranges):
    world.short = short_all_hours(NOW, days=4, pop_by_hour=pop_by_hour(ranges))


@given(parsers.parse("4일 뒤 중기예보에 오전 강수확률 {am:d}, 오후 강수확률 {pm:d}이 있다"))
def mid_with_rain(world, am, pm):
    world.mid = mid_response(NOW, start_idx=4, end_idx=4, rn_am=am, rn_pm=pm)


@given("4일 뒤 중기예보에 강수확률 필드가 없다")
def mid_without_rain(world):
    world.mid = mid_response(NOW, start_idx=4, end_idx=4)


# ── 만일 (When) ──────────────────────────────────────────────────────────────
@when("예보를 병합한다")
def merge(world):
    world.result = world.api._merge_all(NOW, world.short, world.mid, {})


# ── 그러면 (Then) ────────────────────────────────────────────────────────────
@then(parsers.re(r"(?P<day>오늘|내일|\d+일 뒤) (?P<half>오전|오후) 강수확률은 (?P<value>\d+)이다"))
def half_day_probability(world, day, half, value):
    entry = twice_daily_entry(world.result, day_index(day), half == "오전")
    assert entry["precipitation_probability"] == int(value)


@then(parsers.re(r"(?P<day>오늘|내일|\d+일 뒤) 하루 요약의 강수확률은 (?P<value>\d+)이다"))
def daily_probability(world, day, value):
    assert daily_entry(world.result, day_index(day))["precipitation_probability"] == int(value)


@then(parsers.re(r"(?P<day>오늘|내일|\d+일 뒤) 하루 요약의 강수확률은 비어 있다"))
def daily_probability_empty(world, day):
    assert daily_entry(world.result, day_index(day))["precipitation_probability"] is None


@then("하루 요약과 하루 두 번 예보 항목에 강수량, 풍속, 습도 키가 없다")
def excluded_keys_absent(world):
    entries = [world.result["weather"]["forecast_daily"][0], world.result["weather"]["forecast_twice_daily"][0]]
    for entry in entries:
        assert not {"native_precipitation", "native_wind_speed", "humidity"} & set(entry)
