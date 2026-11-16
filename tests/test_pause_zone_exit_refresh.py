"""
test_pause_zone_exit_refresh.py
pause_zones 이탈 시 갱신 BDD 테스트

규칙:
  - 존 안 → 밖 전환을 감지하면 5분 대기 (위치 흔들림 방지)
  - 대기 후에도 존 밖이면, 그 시각의 분(minute)을 본다
      · 0~14분: 이벤트 갱신 없이 곧 올 :15 정기 업데이트에 맡긴다
      · 15~59분: 즉시 한 번 갱신한다
  - 대기 중 재진입 / :15 정기 업데이트 진행·완료 / 이탈 이후 이미 성공한 갱신이 있으면 건너뛴다
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from custom_components.kma_weather import coordinator as coord_module
from test_pause_zones import make_coordinator, make_zone_state

KST = ZoneInfo("Asia/Seoul")
HOME = (37.56, 126.98)
OUTSIDE = (37.61, 126.98)  # 약 5km 밖


def at(hour, minute):
    return datetime(2026, 10, 19, hour, minute, tzinfo=KST)


def make_exit_coordinator(location=HOME):
    zone = make_zone_state("zone.home", *HOME, radius=100)
    coord = make_coordinator(zone_map={"zone.home": zone}, pause_zones=["zone.home"])
    coord._resolve_location = MagicMock(return_value=location)
    coord.async_refresh = AsyncMock()
    return coord


def move_to(coord, location):
    """위치 센서의 상태 변화 이벤트를 흉내낸다."""
    coord._resolve_location.return_value = location
    coord._handle_location_change(MagicMock())


# ─────────────────────────────────────────────────────────────────────────────
# A. 이탈 감지 → 5분 대기 예약
# ─────────────────────────────────────────────────────────────────────────────

class TestExitDetection:

    @pytest.mark.asyncio
    async def test_exit_from_zone_schedules_five_minute_wait(self):
        """
        [Given] 존 안에 있던 모바일 기기
        [When]  위치가 존 밖으로 바뀜
        [Then]  5분 뒤 판정하도록 예약됨
        """
        coord = make_exit_coordinator()
        coord._in_pause_zone_state = True
        with patch.object(coord_module, "async_call_later") as call_later:
            move_to(coord, OUTSIDE)

        assert call_later.call_count == 1
        assert call_later.call_args.args[1] == timedelta(minutes=5)

    @pytest.mark.asyncio
    async def test_still_inside_zone_schedules_nothing(self):
        """
        [Given] 존 안에 있는 기기
        [When]  존 안에서 위치만 바뀜
        [Then]  아무것도 예약되지 않음
        """
        coord = make_exit_coordinator()
        coord._in_pause_zone_state = True
        with patch.object(coord_module, "async_call_later") as call_later:
            move_to(coord, (37.56001, 126.98))

        call_later.assert_not_called()

    @pytest.mark.asyncio
    async def test_already_outside_schedules_nothing(self):
        """
        [Given] 이미 존 밖에서 이동 중인 기기 (기존 동작)
        [When]  위치가 바뀜
        [Then]  이벤트 갱신을 예약하지 않음 (기존과 동일하게 :15 정기 업데이트만)
        """
        coord = make_exit_coordinator(location=OUTSIDE)
        coord._in_pause_zone_state = False
        with patch.object(coord_module, "async_call_later") as call_later:
            move_to(coord, (37.62, 126.99))

        call_later.assert_not_called()

    @pytest.mark.asyncio
    async def test_reentering_zone_during_wait_cancels_pending_check(self):
        """
        [Given] 존 이탈 후 5분 대기 중
        [When]  다시 존 안으로 들어옴
        [Then]  대기 예약이 취소됨
        """
        coord = make_exit_coordinator()
        coord._in_pause_zone_state = True
        cancel = MagicMock()
        with patch.object(coord_module, "async_call_later", return_value=cancel):
            move_to(coord, OUTSIDE)
            move_to(coord, HOME)

        cancel.assert_called_once()
        assert coord._in_pause_zone_state is True

    @pytest.mark.asyncio
    async def test_flapping_exit_keeps_single_pending_check(self):
        """
        [Given] 존 경계에서 위치가 흔들려 이탈·재진입·이탈이 반복됨
        [When]  각 전환을 처리
        [Then]  이전 대기는 취소되고 마지막 이탈 기준 대기 하나만 남음
        """
        coord = make_exit_coordinator()
        coord._in_pause_zone_state = True
        cancels = [MagicMock(), MagicMock()]
        with patch.object(coord_module, "async_call_later", side_effect=cancels) as call_later:
            move_to(coord, OUTSIDE)
            move_to(coord, HOME)
            move_to(coord, OUTSIDE)

        assert call_later.call_count == 2
        cancels[0].assert_called_once()
        cancels[1].assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# B. 5분 대기 후 판정
# ─────────────────────────────────────────────────────────────────────────────

class TestDecisionAfterWait:

    def _exited(self, coord, exit_at):
        coord._in_pause_zone_state = False
        coord._exit_detected_at = exit_at
        coord._resolve_location.return_value = OUTSIDE

    @pytest.mark.asyncio
    async def test_exit_at_25_refreshes_once_after_wait(self):
        """
        [Given] 10:25 이탈, 5분 뒤 10:30에도 존 밖
        [When]  대기 후 판정
        [Then]  즉시 한 번 갱신 (다음 :15까지 45분 오래된 데이터를 보지 않도록)
        """
        coord = make_exit_coordinator()
        self._exited(coord, at(10, 25))
        coord._now = lambda: at(10, 30)

        await coord._async_check_after_exit(None)

        coord.async_refresh.assert_awaited_once()
        assert coord._update_reason == "존 이탈"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("hour,minute", [(11, 0), (11, 1), (11, 14)])
    async def test_decision_in_0_to_14_minutes_waits_for_scheduled_update(self, hour, minute):
        """
        [Given] 10:58 이탈 → 5분 뒤 11:03처럼 판정 시각이 0~14분
        [When]  대기 후 판정
        [Then]  이벤트 갱신 없이 :15 정기 업데이트에 맡김
        """
        coord = make_exit_coordinator()
        self._exited(coord, at(10, 58))
        coord._now = lambda: at(hour, minute)

        await coord._async_check_after_exit(None)

        coord.async_refresh.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_decision_at_minute_15_refreshes(self):
        """
        [Given] 판정 시각이 정확히 :15 (정기 업데이트가 아직 시작되지 않음)
        [When]  대기 후 판정
        [Then]  경계값 15분은 갱신 대상
        """
        coord = make_exit_coordinator()
        self._exited(coord, at(10, 10))
        coord._now = lambda: at(10, 15)

        await coord._async_check_after_exit(None)

        coord.async_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_back_inside_zone_at_decision_skips_refresh(self):
        """
        [Given] 이탈 후 5분 안에 존으로 돌아와 판정 시점에는 존 안
        [When]  대기 후 판정
        [Then]  갱신하지 않음
        """
        coord = make_exit_coordinator()
        self._exited(coord, at(10, 25))
        coord._resolve_location.return_value = HOME
        coord._now = lambda: at(10, 30)

        await coord._async_check_after_exit(None)

        coord.async_refresh.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_scheduled_update_in_progress_skips_refresh(self):
        """
        [Given] :15 정기 업데이트가 이미 시작되어 진행 중 (지연 대기 포함)
        [When]  대기 후 판정이 정기 업데이트와 겹침
        [Then]  이벤트 갱신을 건너뜀 (정기 업데이트가 같은 일을 함)
        """
        coord = make_exit_coordinator()
        self._exited(coord, at(10, 11))
        coord._scheduled_pending = True
        coord._now = lambda: at(10, 16)

        await coord._async_check_after_exit(None)

        coord.async_refresh.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_already_succeeded_after_exit_skips_refresh(self):
        """
        [Given] 이탈 이후(10:11)에 정기 업데이트가 10:15에 성공해 끝남
        [When]  10:16에 대기 후 판정
        [Then]  중복 갱신하지 않음
        """
        coord = make_exit_coordinator()
        self._exited(coord, at(10, 11))
        coord._last_update_ok_at = at(10, 15)
        coord._now = lambda: at(10, 16)

        await coord._async_check_after_exit(None)

        coord.async_refresh.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_scheduled_update_failed_after_exit_still_refreshes(self):
        """
        [Given] 이탈 후 :15 정기 업데이트가 실패해 성공 기록은 이탈 이전 것뿐
        [When]  10:16에 대기 후 판정
        [Then]  갱신을 다시 시도 (오래된 데이터를 방치하지 않음)
        """
        coord = make_exit_coordinator()
        self._exited(coord, at(10, 11))
        coord._last_update_ok_at = at(10, 5)
        coord._now = lambda: at(10, 16)

        await coord._async_check_after_exit(None)

        coord.async_refresh.assert_awaited_once()


# ─────────────────────────────────────────────────────────────────────────────
# C. 정기 업데이트 / 성공 기록
# ─────────────────────────────────────────────────────────────────────────────

class TestScheduledUpdateBookkeeping:

    @pytest.mark.asyncio
    async def test_scheduled_update_marks_pending_while_running(self):
        """
        [Given] :15 정기 업데이트 콜백
        [When]  실행 중과 종료 후를 관찰
        [Then]  실행 중에는 pending, 종료 후(예외 시에도) 해제
        """
        coord = make_exit_coordinator()
        seen = []

        async def refresh():
            seen.append(coord._scheduled_pending)

        coord.async_refresh = AsyncMock(side_effect=refresh)

        await coord._async_scheduled_update(None)

        assert seen == [True]
        assert coord._scheduled_pending is False

    @pytest.mark.asyncio
    async def test_successful_fetch_records_time(self):
        """
        [Given] 존 밖에서 API 호출이 성공
        [When]  _async_update_data 호출
        [Then]  마지막 성공 시각이 기록됨
        """
        coord = make_exit_coordinator(location=OUTSIDE)
        coord._now = lambda: at(10, 30)

        await coord._async_update_data()

        assert coord._last_update_ok_at == at(10, 30)

    @pytest.mark.asyncio
    async def test_failed_fetch_does_not_record_time(self):
        """
        [Given] 존 밖에서 API 호출이 실패(None)
        [When]  _async_update_data 호출
        [Then]  성공 시각은 기록되지 않음
        """
        coord = make_exit_coordinator(location=OUTSIDE)
        coord.api.fetch_data = AsyncMock(return_value=None)

        await coord._async_update_data()

        assert coord._last_update_ok_at is None

    @pytest.mark.asyncio
    async def test_paused_update_keeps_in_zone_state_true(self):
        """
        [Given] 존 안에서 :15 업데이트가 일시정지로 건너뜀
        [When]  _async_update_data 호출
        [Then]  존 안 상태가 유지되고 성공 시각은 기록되지 않음
        """
        coord = make_exit_coordinator(location=HOME)

        await coord._async_update_data()

        assert coord._in_pause_zone_state is True
        assert coord._last_update_ok_at is None

    @pytest.mark.asyncio
    async def test_scheduled_update_outside_zone_clears_in_zone_state(self):
        """
        [Given] 상태 변화 이벤트 없이 :15 업데이트가 존 밖을 처음 발견
        [When]  _async_update_data 호출
        [Then]  존 안 상태가 해제됨 (이후 이탈 이벤트가 중복 판정되지 않음)
        """
        coord = make_exit_coordinator(location=OUTSIDE)
        coord._in_pause_zone_state = True

        await coord._async_update_data()

        assert coord._in_pause_zone_state is False


# ─────────────────────────────────────────────────────────────────────────────
# D. 구독 조건 / 해제
# ─────────────────────────────────────────────────────────────────────────────

class TestSetupAndTeardown:

    @pytest.mark.asyncio
    async def test_mobile_with_pause_zones_subscribes_to_location_entity(self):
        """
        [Given] device_tracker + pause_zones 설정
        [When]  async_setup
        [Then]  위치 센서 상태 변화를 구독하고, 시작 시점의 존 안/밖 상태를 기록
        """
        coord = make_exit_coordinator(location=HOME)
        with patch.object(coord_module, "async_track_state_change_event") as track, \
             patch.object(coord_module, "async_track_time_change"):
            await coord.async_setup()

        track.assert_called_once()
        assert track.call_args.args[1] == ["device_tracker.phone"]
        assert coord._in_pause_zone_state is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize("location_entity,pause_zones", [
        ("zone.home", ["zone.home"]),
        ("device_tracker.phone", []),
        ("", ["zone.home"]),
    ])
    async def test_no_subscription_when_not_applicable(self, location_entity, pause_zones):
        """
        [Given] zone 기기, pause_zones 비어 있음, 위치 엔티티 없음 중 하나
        [When]  async_setup
        [Then]  위치 구독을 만들지 않음 (기존 동작 그대로)
        """
        zone = make_zone_state("zone.home", *HOME, radius=100)
        coord = make_coordinator(zone_map={"zone.home": zone},
                                 location_entity=location_entity,
                                 pause_zones=pause_zones)
        with patch.object(coord_module, "async_track_state_change_event") as track, \
             patch.object(coord_module, "async_track_time_change"):
            await coord.async_setup()

        track.assert_not_called()

    @pytest.mark.asyncio
    async def test_teardown_cancels_listener_and_pending_check(self):
        """
        [Given] 위치 구독과 5분 대기가 걸려 있음
        [When]  async_teardown
        [Then]  둘 다 해제됨
        """
        coord = make_exit_coordinator()
        unsub_loc, unsub_wait, unsub_timer = MagicMock(), MagicMock(), MagicMock()
        coord._unsub_location = unsub_loc
        coord._unsub_exit_wait = unsub_wait
        coord._unsub_timer = unsub_timer

        coord.async_teardown()

        unsub_loc.assert_called_once()
        unsub_wait.assert_called_once()
        unsub_timer.assert_called_once()
