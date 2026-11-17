"""테스트 데이터 생성기: 단기예보 응답 / 존 / 코디네이터."""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from custom_components.kma_weather import coordinator as coordinator_module
from custom_components.kma_weather.api_kma import KMAWeatherAPI
from custom_components.kma_weather.coordinator import KMAWeatherUpdateCoordinator

KST = ZoneInfo("Asia/Seoul")
METERS_PER_DEG_LAT = 111_195  # 위도 1도 ≈ 111.195km (haversine 지구 반경 6371km 기준)


def kst(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=KST)


def make_api():
    return KMAWeatherAPI(MagicMock(), "TEST_KEY")


def short_forecast(base_date, *, days=2, pcp_by_hour=None, pty_by_hour=None,
                   first_slot_hour=0):
    """단기예보 응답 생성.

    pcp_by_hour : {시: 원본 문자열} — 지정 안 한 시각은 '강수없음'(눈이면 '적설없음')
    pty_by_hour : {시: PTY 코드} — 지정 안 하면 '0'
    first_slot_hour : 첫째 날의 첫 슬롯 시각 (예: 05시 발표본은 6)
    """
    pcp_by_hour, pty_by_hour = pcp_by_hour or {}, pty_by_hour or {}
    items = []
    for offset in range(days):
        day = base_date + timedelta(days=offset)
        for hour in range(first_slot_hour if offset == 0 else 0, 24):
            slot = {"fcstDate": day.strftime("%Y%m%d"), "fcstTime": f"{hour:02d}00"}
            pty = pty_by_hour.get(hour, "0")
            snow = pty == "3"
            default = "적설없음" if snow else "강수없음"
            values = {"TMP": "20", "SKY": "1", "PTY": pty,
                      "SNO" if snow else "PCP": pcp_by_hour.get(hour, default)}
            items += [{**slot, "category": c, "fcstValue": v} for c, v in values.items()]
    return {"response": {"body": {"items": {"item": items}}}}


def zone_state(entity_id, lat, lon, radius=100):
    state = MagicMock()
    state.entity_id = entity_id
    state.attributes = {"latitude": lat, "longitude": lon, "radius": radius}
    return state


def meters_north(lat, meters):
    """기준 위도에서 정북쪽으로 meters 만큼 떨어진 위도."""
    return lat + meters / METERS_PER_DEG_LAT


def _make_hass(zones):
    hass = MagicMock()
    hass.config.latitude, hass.config.longitude = 37.56, 126.98
    hass.config.config_dir = "/tmp/test_kma"
    hass.states.get = MagicMock(side_effect=lambda entity_id: (zones or {}).get(entity_id))
    hass.data = {}
    # skyfield 초기화 코루틴은 실행하지 않고 닫아서 'never awaited' 경고를 막는다
    hass.async_create_task = MagicMock(side_effect=lambda coro, *a, **k: coro.close())
    hass.async_add_executor_job = AsyncMock(return_value=None)
    return hass


def make_coordinator(*, zones=None, location_entity="device_tracker.phone",
                     pause_zones=(), location=(37.56, 126.98)):
    """MagicMock hass로 만든 코디네이터. API 호출은 가짜(fetch_data)로 대체된다."""
    entry = MagicMock()
    entry.data = {"api_key": "key", "location_entity": location_entity}
    # pause_zones=None 은 옵션 키 자체가 없는 기존(마이그레이션 전) 사용자
    entry.options = {} if pause_zones is None else {"pause_zones": list(pause_zones)}
    entry.entry_id = "testkit"
    with patch.object(coordinator_module, "async_get_clientsession", return_value=MagicMock()):
        coord = KMAWeatherUpdateCoordinator(_make_hass(zones), entry)
    coord._store_loaded = True
    coord._cached_data = {"weather": {"TMP": 20}, "air": {}}
    coord._update_reason = "자동 업데이트"
    coord.api.fetch_data = AsyncMock(return_value={
        "weather": {"TMP": 25}, "air": {}, "pollen": None, "raw_forecast": {}})
    coord._resolve_location = MagicMock(return_value=location)
    # 이벤트/정기 갱신 모두 실제 _async_update_data 를 거치게 하여 API 호출 횟수를 셀 수 있다.
    # 갱신 시점의 갱신 사유(_update_reason)는 실행 중에 초기화되므로 호출 때 따로 기록해 둔다.
    coord.refresh_reasons = []

    async def refresh():
        coord.refresh_reasons.append(coord._update_reason)
        return await coord._async_update_data()

    coord.async_refresh = AsyncMock(side_effect=refresh)
    return coord


class FakeTimer:
    """coordinator 의 async_call_later 를 대체해 '5분 대기' 예약을 기록한다.

    now: 현재 가상 시각을 돌려주는 함수.  pending: 대기 중인 예약 {delay, due, callback} 또는 None.
    """

    def __init__(self, now):
        self._now = now
        self.pending = None
        self._patcher = None

    def __call__(self, _hass, delay, callback):
        self.pending = {"delay": delay, "due": self._now() + delay, "callback": callback}

        def cancel():
            self.pending = None
        return cancel

    def install(self):
        self._patcher = patch.object(coordinator_module, "async_call_later", side_effect=self)
        self._patcher.start()
        return self

    def uninstall(self):
        if self._patcher:
            self._patcher.stop()
            self._patcher = None
