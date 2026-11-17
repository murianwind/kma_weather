"""BDD: 코디네이터의 위치·API·캐시 조합별 갱신 결과 — features/coordinator_resilience.feature"""
from unittest.mock import AsyncMock

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from testkit.aio import run
from testkit.factories import make_coordinator
from testkit.keywords import World

scenarios("features/coordinator_resilience.feature")

SEOUL = (37.56, 126.98)
NEW = {"weather": {"TMP": 25}, "air": {"station": "중구"}, "pollen": None, "raw_forecast": {}}
CACHE = {"weather": {"TMP": 21}, "air": {"pm10Value": 30}}


@pytest.fixture
def world():
    return World()


# ── 조건 (Given) ─────────────────────────────────────────────────────────────
@given(parsers.parse('위치는 "{location}"이고 API 는 "{api}"이며 이전 캐시는 "{cache}"이다'))
def setup(world, location, api, cache):
    coord = make_coordinator(location=SEOUL if location == "있음" else (None, None))
    coord._cached_data = None
    if cache == "있음":
        coord._cached_data = {"weather": {"TMP": 18 if location == "없음" else 21}, "air": {"pm10Value": 30}}
    coord.api.fetch_data = AsyncMock(return_value=None if api == "실패" else dict(NEW))
    world.coord = coord


@given(parsers.parse('API 응답의 대기질 측정소는 "{station}"이다'))
def api_station(world, station):
    world.coord.api.fetch_data = AsyncMock(return_value={**NEW, "air": {"station": station}})


# ── 만일 (When) ──────────────────────────────────────────────────────────────
@when("업데이트가 실행된다")
def update(world):
    world.result = run(world.coord._async_update_data())


# ── 그러면 (Then) ────────────────────────────────────────────────────────────
@then(parsers.parse('결과의 기온은 "{expected}"이다'))
def temperature(world, expected):
    if expected == "없음":
        assert world.result is None
    elif expected == "빈 값":
        assert world.result == {"weather": {}, "air": {}}
    else:
        assert world.result["weather"]["TMP"] == int(expected.split("(")[1].rstrip(")"))


@then(parsers.parse('API 는 "{called}"'))
def api_called(world, called):
    assert (world.coord.api.fetch_data.await_count == 1) == (called == "호출되었다")


@then(parsers.parse('결과의 대기질 측정소는 "{station}"이다'))
def air_station(world, station):
    assert world.result["air"]["station"] == station
