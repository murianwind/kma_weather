"""BDD: 일일 최고·최저 기온 누적 — features/daily_temperature.feature"""
import re
from datetime import date, datetime

import pytest
from freezegun import freeze_time
from pytest_bdd import given, parsers, scenarios, then, when

from testkit.factories import KST, make_coordinator
from testkit.keywords import World

scenarios("features/daily_temperature.feature")


@pytest.fixture
def world():
    freezer = freeze_time("2026-04-08 15:00:00")  # 한국 시각으로 2026-04-09 00:00
    freezer.start()
    world = World(coord=make_coordinator(),
                  today=datetime.now(KST).strftime("%Y%m%d"))
    world.coord._daily_date = world.coord._daily_max_temp = world.coord._daily_min_temp = None
    yield world
    freezer.stop()


def forecast_map(world, text):
    """'09:00 10도, 12:00 20도' → {오늘: {'0900': {'TMP': '10'}, '1200': {'TMP': '20'}}}"""
    slots = {}
    for part in text.split(","):
        hour, minute, temp = re.fullmatch(r"\s*(\d+):(\d+) (-?\d+)도\s*", part).groups()
        slots[f"{hour}{minute}"] = {"TMP": temp}
    return {world.today: slots}


# ── 조건 (Given) ─────────────────────────────────────────────────────────────
@given("오늘의 기온 기록이 비어 있다")
def empty_record(world):
    assert world.coord._daily_max_temp is None


@given(parsers.parse('오늘 예보로 "{text}"를 받았다'))
@when(parsers.parse('오늘 예보로 "{text}"를 받는다'))
@when(parsers.parse('다른 지점의 오늘 예보로 "{text}"를 받는다'))
def receive_forecast(world, text):
    world.coord._update_daily_temperatures(forecast_map(world, text))


@given(parsers.parse("{day}에 최고 {high:d}도, 최저 {low:d}도가 기록되어 있다"))
def old_record(world, day, high, low):
    world.coord._daily_date = date.fromisoformat(day)
    world.coord._daily_max_temp, world.coord._daily_min_temp = float(high), float(low)


# ── 그러면 (Then) ────────────────────────────────────────────────────────────
@then(parsers.parse("최고 기온은 {high:d}도이고 최저 기온은 {low:d}도이다"))
def high_and_low(world, high, low):
    assert (world.coord._daily_max_temp, world.coord._daily_min_temp) == (float(high), float(low))


@then("기록 날짜는 오늘이다")
def record_date_is_today(world):
    assert world.coord._daily_date == datetime.now(KST).date()
