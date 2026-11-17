"""BDD: 일시정지 존 이탈 감지의 준비·기록·해제 — features/pause_zone_lifecycle.feature"""
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from custom_components.kma_weather import coordinator as coordinator_module
from testkit.aio import run
from testkit.factories import kst, make_coordinator, meters_north, zone_state
from testkit.keywords import World

scenarios("features/pause_zone_lifecycle.feature")

HOME = (37.56, 126.98)
OUTSIDE = (meters_north(HOME[0], 5000), HOME[1])


@pytest.fixture
def world():
    return World(now=kst(2026, 10, 19, 10, 0))


def _at(hhmm):
    hour, minute = map(int, hhmm.split(":"))
    return kst(2026, 10, 19, hour, minute)


# ── 조건 (Given) ─────────────────────────────────────────────────────────────
@given(parsers.parse('위치 엔티티가 "{entity}"이고 pause_zones 가 "{zones}"인 기기가 있다'))
def device(world, entity, zones):
    pause_zones = [] if zones == "(없음)" else [zones]
    entity = "" if entity == "(없음)" else entity
    world.coord = make_coordinator(
        zones={"zone.home": zone_state("zone.home", *HOME, radius=100)},
        location_entity=entity, pause_zones=pause_zones, location=HOME)
    world.coord._now = lambda: world.now


@given("기기가 존 안에 있다")
def inside(world):
    world.coord._resolve_location.return_value = HOME


@given("기기가 존 밖에 있다")
def outside(world):
    world.coord._resolve_location.return_value = OUTSIDE


@given("코디네이터는 아직 존 안으로 기억하고 있다")
def remembers_inside(world):
    world.coord._in_pause_zone_state = True


@given(parsers.parse("현재 시각은 {hhmm}이다"))
def clock(world, hhmm):
    world.now = _at(hhmm)


@given("위치 구독과 대기 예약과 정기 타이머가 걸려 있다")
def subscriptions(world):
    world.coord = make_coordinator()
    world.unsubs = {name: MagicMock() for name in ("location", "wait", "timer")}
    world.coord._unsub_location = world.unsubs["location"]
    world.coord._unsub_exit_wait = world.unsubs["wait"]
    world.coord._unsub_timer = world.unsubs["timer"]


# ── 만일 (When) ──────────────────────────────────────────────────────────────
@when("통합구성요소를 시작한다")
def setup(world):
    with patch.object(coordinator_module, "async_track_state_change_event") as track, \
            patch.object(coordinator_module, "async_track_time_change"):
        run(world.coord.async_setup())
    world.track = track


@when("통합구성요소를 해제한다")
def teardown(world):
    world.coord.async_teardown()


@when("정기 업데이트가 실행된다")
def scheduled_update(world):
    world.flag_during = None

    async def refresh():
        world.flag_during = world.coord._scheduled_pending
    world.coord.async_refresh = AsyncMock(side_effect=refresh)
    run(world.coord._async_scheduled_update(None))


@when("정기 업데이트가 실제 운영 환경에서 시작된다")
def scheduled_update_in_production(world):
    world.coord.async_refresh = AsyncMock()
    with patch.dict(sys.modules), \
            patch.object(coordinator_module.asyncio, "sleep", new=AsyncMock()) as sleep:
        sys.modules.pop("pytest")  # 코드는 pytest 가 없을 때(운영)만 지연 대기를 한다
        run(world.coord._async_scheduled_update(None))
    world.sleep = sleep


@when("업데이트가 성공한다")
def update_succeeds(world):
    run(world.coord._async_update_data())


@when("업데이트가 실패한다")
def update_fails(world):
    world.coord.api.fetch_data.return_value = None
    run(world.coord._async_update_data())


# ── 그러면 (Then) ────────────────────────────────────────────────────────────
@then(parsers.parse("위치 구독은 {result}"))
def subscription_result(world, result):
    assert (world.track.call_count == 1) == (result == "만들어진다")


@then("기기는 존 안으로 기록된다")
def recorded_inside(world):
    assert world.coord._in_pause_zone_state is True


@then("기기는 존 밖으로 기록된다")
def recorded_outside(world):
    assert world.coord._in_pause_zone_state is False


@then("세 가지가 모두 해제된다")
def all_released(world):
    for unsub in world.unsubs.values():
        unsub.assert_called_once()


@then("실행 중에는 진행 표시가 켜져 있었다")
def flag_on_during(world):
    assert world.flag_during is True


@then("끝난 뒤에는 진행 표시가 꺼진다")
def flag_off_after(world):
    assert world.coord._scheduled_pending is False


@then("시작 전에 10초 이상 30초 이하 대기한다")
def waits_before_start(world):
    (delay,), _ = world.sleep.await_args
    assert 10 <= delay <= 30


@then(parsers.parse("마지막 성공 시각은 {hhmm}이다"))
def last_success_at(world, hhmm):
    assert world.coord._last_update_ok_at == _at(hhmm)


@then("마지막 성공 시각은 기록되지 않는다")
def last_success_none(world):
    assert world.coord._last_update_ok_at is None
