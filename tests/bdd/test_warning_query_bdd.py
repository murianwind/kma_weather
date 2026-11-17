"""BDD: 기상특보 조회(_get_warning) — features/warning_query.feature
항목 해석 규칙(발표/연장/해제/경보 수준)은 tests/data_driven/test_api_data.py 의 warning_items.yaml 표가 다룬다."""
import logging
from unittest.mock import AsyncMock

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from testkit.aio import run
from testkit.factories import make_api
from testkit.keywords import World

scenarios("features/warning_query.feature")

DRY_WARNING = {"command": "1", "cancel": "0", "endTime": "0", "warnVar": "4", "warnStress": "0"}


def response(items):
    return {"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": items}}}}


@pytest.fixture
def world(caplog):
    api = make_api()
    api._fetch_page_warnings_for_area = AsyncMock(return_value={})
    return World(api=api, caplog=caplog)


# ── 조건 (Given) ─────────────────────────────────────────────────────────────
@given("기상특보 API 가 건조주의보를 알려 준다")
def api_dry_warning(world):
    world.api._fetch = AsyncMock(return_value=response([DRY_WARNING]))


@given("기상특보 API 가 결과 코드 없이 빈 항목을 돌려준다")
def api_without_result_code(world):
    world.api._fetch = AsyncMock(return_value={"response": {"body": {"items": {"item": []}}}})


@given("기상특보 API 가 응답하지 못한다")
def api_no_response(world):
    world.api._fetch = AsyncMock(return_value=None)


@given("기상특보 API 가 미신청(resultCode 30) 응답을 준다")
def api_unsubscribed(world):
    world.api._approved_apis.add("warning")
    world.api._fetch = AsyncMock(return_value={"response": {"header": {"resultCode": "30"}}})


@given(parsers.parse('기상청 특보 현황 페이지에는 "{name}"(warnVar {warn_var})도 발효 중으로 나온다'))
@given(parsers.parse('기상청 특보 현황 페이지에는 "{name}"(warnVar {warn_var})가 발효 중으로 나온다'))
def page_has_warning(world, name, warn_var):
    world.api._fetch_page_warnings_for_area = AsyncMock(return_value={warn_var: name})


@given("기상청 특보 현황 페이지 조회가 실패한다")
def page_fails(world):
    world.api._fetch_page_warnings_for_area = AsyncMock(side_effect=Exception("page down"))


@given("기상특보 API 조회 중 예외가 발생한다")
def api_raises(world):
    world.api._fetch = AsyncMock(side_effect=Exception("boom"))


# ── 만일 (When) ──────────────────────────────────────────────────────────────
@when(parsers.parse('특보구역 "{area}"의 기상특보를 조회한다'))
def query(world, area):
    with world.caplog.at_level(logging.DEBUG):
        world.result = run(world.api._get_warning(area))


@when("지역코드 없이 기상특보를 조회한다")
def query_without_area(world):
    world.result = run(world.api._get_warning(None))


# ── 그러면 (Then) ────────────────────────────────────────────────────────────
@then("결과는 없다")
def result_none(world):
    assert world.result is None


@then(parsers.parse('결과는 "{text}"이다'))
def result_text(world, text):
    assert world.result == text


@then("기상특보 API 는 호출되지 않았다")
def api_not_called(world):
    world.api._fetch.assert_not_called()


@then("기상특보 API 는 승인된 것으로 표시된다")
def approved(world):
    assert "warning" in world.api._approved_apis


@then("기상특보 API 는 승인되지 않은 것으로 표시된다")
def not_approved(world):
    assert "warning" not in world.api._approved_apis


@then("ERROR 로그가 한 건 남는다")
def one_error_log(world):
    assert len([r for r in world.caplog.records if r.levelno == logging.ERROR]) == 1


@then(parsers.parse('기상특보 API 는 "{url}" 로 호출되었다'))
def called_with_url(world, url):
    assert world.api._fetch.call_args.args[0] == url


@then("기상청 특보 현황 페이지는 조회되지 않았다")
def page_not_queried(world):
    world.api._fetch_page_warnings_for_area.assert_not_called()
