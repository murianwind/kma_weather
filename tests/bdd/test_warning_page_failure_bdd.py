"""BDD: 특보 보완 페이지 조회 실패 알림 — features/warning_page_failure.feature
병합 규칙은 tests/data_driven/test_warning_page_data.py 의 warning_page_merge.csv 표가 다룬다."""
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from testkit.aio import run
from testkit.factories import make_api
from testkit.keywords import World

scenarios("features/warning_page_failure.feature")

HEATWAVE_ADVISORY = {"areaCode": "L1091320", "cancel": "0", "command": "1", "endTime": 0,
                     "tmFc": 202607191000, "warnVar": 12, "warnStress": 0}


class Page:
    def __init__(self, status=200, text="<table></table>"):
        self.status, self._text = status, text

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.fixture
def world(caplog):
    api = make_api()
    api.session = MagicMock()
    return World(api=api, caplog=caplog)


# ── 조건 (Given) ─────────────────────────────────────────────────────────────
@given("기상특보 API 는 제주시북부에 폭염주의보를 알려 준다")
def api_heatwave(world):
    world.api._fetch = AsyncMock(return_value={
        "response": {"header": {"resultCode": "00"}, "body": {"items": {"item": [HEATWAVE_ADVISORY]}}}})


@given("기상청 특보 현황 페이지 조회는 예외로 실패한다")
@given("기상청 특보 현황 페이지 조회는 다시 예외로 실패한다")
@given("기상청 특보 현황 페이지 조회는 예외로 실패한다")
def page_raises(world):
    world.api.session.get = MagicMock(side_effect=Exception("timeout"))


@given("기상청 특보 현황 페이지 조회는 503 으로 응답한다")
def page_503(world):
    world.api.session.get = lambda *args, **kwargs: Page(status=503)


@given("기상청 특보 현황 페이지가 정상으로 복구되었다")
def page_recovered(world):
    world.api.session.get = lambda *args, **kwargs: Page()


@given("특보 현황 페이지를 조회했다")
def page_queried_before(world):
    run(world.api._fetch_page_warnings_for_area("제주시북부"))


# ── 만일 (When) ──────────────────────────────────────────────────────────────
@when(parsers.parse('특보구역 "{area}" 의 기상특보를 조회한다'))
def query_warning(world, area):
    world.result = run(world.api._get_warning(area))


@when("특보 현황 페이지를 조회한다")
def query_page(world):
    with world.caplog.at_level(logging.WARNING):
        run(world.api._fetch_page_warnings_for_area("제주시북부"))


@when("특보 현황 페이지를 두 번 조회한다")
def query_page_twice(world):
    with world.caplog.at_level(logging.WARNING):
        run(world.api._fetch_page_warnings_for_area("제주시북부"))
        run(world.api._fetch_page_warnings_for_area("제주시북부"))


# ── 그러면 (Then) ────────────────────────────────────────────────────────────
@then(parsers.parse('결과는 "{text}" 이다'))
def result_is(world, text):
    assert world.result == text


def warnings_logged(world):
    return [r for r in world.caplog.records if r.levelno == logging.WARNING]


@then("WARNING 로그가 한 건 남는다")
def one_warning(world):
    assert len(warnings_logged(world)) == 1
    assert "weather.go.kr" in warnings_logged(world)[0].getMessage()


@then("WARNING 로그가 두 건 남는다")
def two_warnings(world):
    assert len(warnings_logged(world)) == 2
