"""BDD: 일시정지 존 이탈 시 데이터 갱신 — 시나리오는 features/pause_zone_exit.feature 에 있다.

  시나리오 목록·결과 보기: pytest tests/bdd/test_pause_zone_exit_bdd.py --gherkin-terminal-reporter -v
"""
from datetime import timedelta

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from testkit.aio import run
from testkit.factories import FakeTimer, kst, make_coordinator, meters_north, zone_state
from testkit.keywords import World

scenarios("features/pause_zone_exit.feature")

HOME = (37.56, 126.98)
OUTSIDE = (meters_north(HOME[0], 5000), HOME[1])
FARTHER = (meters_north(HOME[0], 9000), HOME[1])
NEAR_HOME = (meters_north(HOME[0], 10), HOME[1])


def at(hhmm):
    hour, minute = map(int, hhmm.split(":"))
    return kst(2026, 10, 19, hour, minute)


def move_to(world, location):
    world.coord._resolve_location.return_value = location
    world.coord._handle_location_change(None)


@pytest.fixture
def world():
    world = World(now=at("10:00"))
    yield world
    world.timer.uninstall()


# ── 조건 (Given) ─────────────────────────────────────────────────────────────
@given('"우리집" 존이 일시정지 존으로 지정된 모바일 기기가 있다')
def device_with_pause_zone(world):
    zones = {"zone.home": zone_state("zone.home", *HOME, radius=100)}
    world.coord = make_coordinator(zones=zones, pause_zones=["zone.home"], location=HOME)
    world.coord._now = lambda: world.now
    world.timer = FakeTimer(lambda: world.now).install()


@given("기기가 존 안에 있다")
def device_inside(world):
    world.coord._resolve_location.return_value = HOME
    world.coord._in_pause_zone_state = True


@given("기기가 존 밖에 있다")
def device_outside(world):
    world.coord._resolve_location.return_value = OUTSIDE
    world.coord._in_pause_zone_state = False


@given("기기가 존 밖으로 이동해 5분 대기가 예약되어 있다")
@given(parsers.parse("기기가 {hhmm}에 존 밖으로 이동해 5분 대기가 예약되어 있다"))
def device_exited(world, hhmm="10:25"):
    world.now = at(hhmm)
    device_inside(world)
    move_to(world, OUTSIDE)
    assert world.timer.pending is not None


@given("그 사이 기기가 존 안으로 돌아와 있다")
def device_back_inside(world):
    world.coord._resolve_location.return_value = HOME


@given("그 사이 위치를 알 수 없게 되었다")
def location_lost_meanwhile(world):
    world.coord._resolve_location.return_value = (None, None)


@given(":15 정기 업데이트가 이미 시작되어 진행 중이다")
def scheduled_update_running(world):
    world.coord._scheduled_pending = True


@given(parsers.parse("{hhmm}에 정기 업데이트가 성공했다"))
def scheduled_update_succeeded(world, hhmm):
    world.coord._last_update_ok_at = at(hhmm)


# ── 만일 (When) ──────────────────────────────────────────────────────────────
@when("기기가 존 밖으로 이동한다")
def device_moves_out(world):
    move_to(world, OUTSIDE)


@when("기기가 존 안에서 조금 움직인다")
def device_moves_inside(world):
    move_to(world, NEAR_HOME)


@when("기기가 존 밖에서 더 멀리 이동한다")
def device_moves_farther(world):
    move_to(world, FARTHER)


@when("위치를 알 수 없는 상태로 위치 이벤트가 온다")
def location_unknown_event(world):
    move_to(world, (None, None))


@when("기기가 다시 존 안으로 들어온다")
def device_reenters(world):
    move_to(world, HOME)


@when(parsers.parse("{hhmm}에 대기가 끝나 판정한다"))
def wait_over(world, hhmm):
    world.now = at(hhmm)
    world.timer.pending = None
    run(world.coord._async_check_after_exit(None))


# ── 그러면 (Then) ────────────────────────────────────────────────────────────
@then("5분 뒤 판정하도록 예약된다")
def scheduled_in_five_minutes(world):
    assert world.timer.pending["delay"] == timedelta(minutes=5)


@then("예약된 것이 없다")
def nothing_scheduled(world):
    assert world.timer.pending is None


@then("기기는 여전히 존 안으로 기록되어 있다")
def still_recorded_inside(world):
    assert world.coord._in_pause_zone_state is True


@then(parsers.parse("갱신 횟수는 {count:d}번이다"))
def refresh_count(world, count):
    assert world.coord.api.fetch_data.await_count == count


@then(parsers.parse('갱신 사유는 "{reason}"이다'))
def refresh_reason(world, reason):
    assert world.coord.refresh_reasons == ([] if reason == "(없음)" else [reason])
