"""BDD: 미신청 API 처리 — features/api_unsubscribed.feature
resultCode 별 미신청 판정 경계는 tests/test_api_data.py 의 unsubscribed_codes.csv 표가 다룬다."""
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from custom_components.kma_weather.api_kma import KMAWeatherAPI
from testkit.aio import run
from testkit.factories import kst
from testkit.keywords import World

scenarios("features/api_unsubscribed.feature")

NOW = kst(2026, 4, 11, 10, 0)


def unsubscribed_response(code="33"):
    return {"response": {"header": {"resultCode": code, "resultMsg": "서비스 신청하지 않음"}, "body": {}}}


@pytest.fixture
def world(caplog):
    api = KMAWeatherAPI(MagicMock(), "key", hass=MagicMock())
    api.nx, api.ny = 60, 127
    return World(api=api, caplog=caplog)


def notifications(world):
    return world.api.hass.components.persistent_notification.async_create


# ── 조건 (Given) ─────────────────────────────────────────────────────────────
@given("API 서비스가 미신청 응답(resultCode 33)을 준다")
def service_unsubscribed(world):
    world.api._fetch = AsyncMock(return_value=unsubscribed_response("33"))


@given("알림을 보낼 수 있는 환경이다")
def with_hass(world):
    world.api.hass = MagicMock()


@given("알림을 보낼 수 없는 환경이다")
def without_hass(world):
    world.api.hass = None


@given(parsers.parse('"{key}" 서비스는 승인된 상태이다'))
def approved(world, key):
    world.api._approved_apis.add(key)


# ── 만일 (When) ──────────────────────────────────────────────────────────────
CALLS = {
    "단기예보": lambda api: api._get_short_term(NOW),
    "중기예보": lambda api: api._get_mid_term(NOW, "11B10101", "11B00000"),
    "측정소정보": lambda api: api._get_air_quality(37.56, 126.98),
    "기상특보": lambda api: api._get_warning("L1100200"),
}


@when(parsers.parse('"{service}"를 조회한다'))
def query(world, service):
    world.result = run(CALLS[service](world.api))


@when(parsers.parse('"{service}"를 {count:d}번 조회한다'))
def query_repeatedly(world, service, count):
    for _ in range(count):
        run(CALLS[service](world.api))


@when("단기예보, 중기예보, 대기질 서비스가 각각 미신청으로 판정된다")
def three_services(world):
    for key in ("short", "mid", "air"):
        world.api._check_unsubscribed(key, "33")


@when(parsers.parse('"{key}" 서비스가 미신청(resultCode {code})으로 판정된다'))
def judged_unsubscribed(world, key, code):
    world.judged = world.api._check_unsubscribed(key, code)


@when(parsers.parse('"{key}" 서비스가 미신청(resultCode {code})으로 두 번 판정된다'))
def judged_twice(world, key, code):
    with world.caplog.at_level(logging.WARNING, logger="custom_components.kma_weather.api_kma"):
        world.api._check_unsubscribed(key, code)
        world.api._check_unsubscribed(key, code)


# ── 그러면 (Then) ────────────────────────────────────────────────────────────
@then(parsers.parse('조회 결과는 "{expected}"이다'))
def result_is(world, expected):
    if expected == "UNSUBSCRIBED":
        assert world.result == "UNSUBSCRIBED"
    elif expected.startswith("("):  # 중기예보: (신호, 육상 None, 발표 시각)
        signal, land, announced = world.result
        assert (signal, land) == ("UNSUBSCRIBED", None) and announced is not None
    elif expected == "{}":
        assert world.result == {}
    else:
        assert world.result is None


@then(parsers.parse("신청 안내 알림은 {count:d}번 보냈다"))
def notification_count(world, count):
    assert notifications(world).call_count == count


@then(parsers.parse("알린 서비스는 {count:d}개이다"))
def notified_services(world, count):
    assert len(world.api._notified_unsubscribed) == count


@then(parsers.parse('알림 메시지에 "{name}"와 "{url_part}"가 들어 있다'))
def message_contains(world, name, url_part):
    message = notifications(world).call_args.kwargs.get("message", "")
    assert name in message and url_part in message


@then(parsers.parse('알림 번호에 "{key}"이 들어 있다'))
@then(parsers.parse('알림 번호에 "{key}"가 들어 있다'))
def notification_id_contains(world, key):
    assert key in notifications(world).call_args.kwargs.get("notification_id", "")


@then("판정 결과는 미신청이다")
def judged_true(world):
    assert world.judged is True


@then(parsers.parse("미신청 경고 로그는 {count:d}건 이상이다"))
def warning_logs(world, count):
    logs = [r for r in world.caplog.records if r.levelname == "WARNING" and "미신청" in r.message]
    assert len(logs) >= count


@then(parsers.parse('"{key}" 서비스는 승인 목록에 없다'))
def not_in_approved(world, key):
    assert key not in world.api._approved_apis


@then(parsers.parse('"{key}" 서비스는 신청 대기 목록에 있다'))
def in_pending(world, key):
    assert key in world.api._pending_apis
