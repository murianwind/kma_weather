"""BDD: 오늘 오전·오후 요약 날씨의 갱신 규칙 — features/daily_summary.feature"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from freezegun import freeze_time
from pytest_bdd import given, parsers, scenarios, then, when

from testkit.aio import run
from testkit.factories import KST, make_coordinator
from testkit.keywords import World

scenarios("features/daily_summary.feature")


@pytest.fixture
def world():
    world = World(freezer=None)
    yield world
    if world.freezer:
        world.freezer.stop()


# ── 조건 (Given) ─────────────────────────────────────────────────────────────
@given(parsers.parse("코디네이터가 있고 지금은 {hhmm}이다"))
def coordinator_at(world, hhmm):
    hour, minute = map(int, hhmm.split(":"))
    kst_now = datetime(2026, 4, 11, hour, minute, tzinfo=KST)
    world.freezer = freeze_time(kst_now.astimezone(timezone.utc))
    world.freezer.start()
    world.coord = make_coordinator(location_entity="zone.home", location=(37.5, 127.0))
    world.coord._daily_date = datetime.now(KST).date()  # 새로운 날이 아님
    # 이미 구역코드를 한 번 정해 둔 상태로 만든다 (처음 결정할 때는 요약을 비우는 별도 규칙이 있다)
    world.coord._resolve_area_codes(37.5, 127.0)
    world.api_summary = None


@given(parsers.parse('이전 요약은 오전 "{am}", 오후 "{pm}"이다'))
def previous_summary(world, am, pm):
    world.coord._wf_am_today, world.coord._wf_pm_today = am, pm


@given(parsers.parse('이전 요약은 오전 비어 있고 오후 "{pm}"이다'))
def previous_summary_no_am(world, pm):
    world.coord._wf_am_today, world.coord._wf_pm_today = None, pm


@given("이전 요약은 오전 비어 있고 오후 비어 있다")
def previous_summary_empty(world):
    world.coord._wf_am_today = world.coord._wf_pm_today = None


@given(parsers.parse('API 는 오전 "{am}", 오후 "{pm}"를 알려 준다'))
def api_summary(world, am, pm):
    world.api_summary = {"wf_am_today": am, "wf_pm_today": pm}


@given("API 는 요약을 알려 주지 않는다")
def api_no_summary(world):
    world.api_summary = {}


# ── 만일 (When) ──────────────────────────────────────────────────────────────
UPDATE_REASONS = {"정기": "자동 업데이트", "수동": "업데이트 액션", "재시작": "재시작"}


@when(parsers.parse("{kind} 업데이트가 실행된다"))
def update(world, kind):
    kind = kind.strip('"')
    world.coord.api.fetch_data = AsyncMock(return_value={
        "weather": {"TMP": 20, **world.api_summary}, "air": {}, "pollen": None, "raw_forecast": {}})
    world.coord._update_reason = UPDATE_REASONS[kind]
    world.result = run(world.coord._async_update_data())


# ── 그러면 (Then) ────────────────────────────────────────────────────────────
@then(parsers.parse('오늘 요약은 오전 "{am}", 오후 "{pm}"이다'))
def summary_is(world, am, pm):
    assert (world.result["weather"]["wf_am_today"], world.result["weather"]["wf_pm_today"]) == (am, pm)
