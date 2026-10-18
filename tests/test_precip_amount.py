"""
test_precip_amount.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"현재 예상 강수량" 센서(precip_amount) 검증

검증 대상:
  - api_kma.py::_merge_all() 의 precip_amount 계산
  - api_kma.py::_merge_all() 의 hourly_precipitation_mm 계산
  - sensor.py::KMACustomSensor 의 precip_amount 노출(state/attributes)
"""
import pytest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import MagicMock

from custom_components.kma_weather.api_kma import KMAWeatherAPI

TZ = ZoneInfo("Asia/Seoul")


def make_api():
    return KMAWeatherAPI(MagicMock(), "TEST_KEY")


def make_short_res(base_date, hourly_pcp: dict[int, str], pty_by_hour: dict[int, str] | None = None, days=2):
    """
    hourly_pcp: {시(0~23): PCP 원본 문자열} — 지정 안 한 시각은 '강수없음'
    pty_by_hour: {시: PTY 코드 문자열} — 지정 안 하면 '0'(없음)
    """
    pty_by_hour = pty_by_hour or {}
    items = []
    for d in range(days):
        day = base_date + timedelta(days=d)
        d_str = day.strftime("%Y%m%d")
        for h in range(24):
            t_str = f"{h:02d}00"
            items.append({"fcstDate": d_str, "fcstTime": t_str, "category": "TMP", "fcstValue": "20"})
            items.append({"fcstDate": d_str, "fcstTime": t_str, "category": "SKY", "fcstValue": "1"})
            pty = pty_by_hour.get(h, "0")
            items.append({"fcstDate": d_str, "fcstTime": t_str, "category": "PTY", "fcstValue": pty})
            pcp = hourly_pcp.get(h, "강수없음")
            if pty == "3":
                items.append({"fcstDate": d_str, "fcstTime": t_str, "category": "SNO", "fcstValue": pcp})
            else:
                items.append({"fcstDate": d_str, "fcstTime": t_str, "category": "PCP", "fcstValue": pcp})
    return {"response": {"body": {"items": {"item": items}}}}


# ─────────────────────────────────────────────────────────────────────────────
# 1. 현재 예상 강수량 (precip_amount) 계산
# ─────────────────────────────────────────────────────────────────────────────

class TestCurrentPrecipAmount:
    """현재 시간대(정시 기준)의 예상 강수량이 올바르게 계산되는지 검증"""

    def test_returns_current_hour_precip_as_number(self):
        """
        [Given] 14시 슬롯의 PCP가 "5.0mm"인 단기예보 응답
        [When]  14시 30분에 _merge_all 호출
        [Then]  precip_amount가 5.0 (float)으로 반환됨
        """
        api = make_api()
        now = datetime(2026, 7, 7, 14, 30, tzinfo=TZ)
        short_res = make_short_res(now, {14: "5.0mm"})

        result = api._merge_all(now, short_res, None, {})

        assert result["weather"]["precip_amount"] == 5.0

    def test_no_rain_returns_zero(self):
        """
        [Given] 현재 시간대 PCP가 "강수없음"
        [When]  _merge_all 호출
        [Then]  precip_amount는 0.0
        """
        api = make_api()
        now = datetime(2026, 7, 7, 10, 0, tzinfo=TZ)
        short_res = make_short_res(now, {})  # 전부 강수없음

        result = api._merge_all(now, short_res, None, {})

        assert result["weather"]["precip_amount"] == 0.0

    def test_less_than_1mm_returns_half(self):
        """
        [Given] 현재 시간대 PCP가 "1mm 미만"
        [When]  _merge_all 호출
        [Then]  precip_amount는 관례상 0.5로 처리됨 (숫자로 명시 안 된 경우의 근사치)
        """
        api = make_api()
        now = datetime(2026, 7, 7, 9, 0, tzinfo=TZ)
        short_res = make_short_res(now, {9: "1mm 미만"})

        result = api._merge_all(now, short_res, None, {})

        assert result["weather"]["precip_amount"] == 0.5

    def test_snow_uses_sno_field_when_pty_is_snow(self):
        """
        [Given] 현재 시간대 PTY=3(눈) + SNO="3.0cm"
        [When]  _merge_all 호출
        [Then]  PCP 대신 SNO 값이 precip_amount로 사용됨
        """
        api = make_api()
        now = datetime(2026, 1, 15, 8, 0, tzinfo=TZ)
        short_res = make_short_res(now, {8: "3.0cm"}, pty_by_hour={8: "3"})

        result = api._merge_all(now, short_res, None, {})

        assert result["weather"]["precip_amount"] == 3.0

    def test_hour_rounds_down_ignoring_minutes(self):
        """
        [Given] 14시 슬롯 PCP="2.0mm", 15시 슬롯 PCP="9.0mm"
        [When]  14시 59분(정시 기준 14시)에 _merge_all 호출
        [Then]  precip_amount는 다음 시각(15시)이 아니라 현재 시각(14시) 값
        """
        api = make_api()
        now = datetime(2026, 7, 7, 14, 59, tzinfo=TZ)
        short_res = make_short_res(now, {14: "2.0mm", 15: "9.0mm"})

        result = api._merge_all(now, short_res, None, {})

        assert result["weather"]["precip_amount"] == 2.0


# ─────────────────────────────────────────────────────────────────────────────
# 2. 시간대별 강수량 속성 (hourly_precipitation_mm)
# ─────────────────────────────────────────────────────────────────────────────

class TestHourlyPrecipitationAttribute:
    """precip_amount 센서의 속성으로 들어갈 다음 24시간 시간대별 강수량 검증"""

    def test_contains_exactly_24_hours(self):
        """
        [Given] 이틀치 단기예보 데이터
        [When]  _merge_all 호출
        [Then]  hourly_precipitation_mm에 정확히 24개 시간대가 담김
        """
        api = make_api()
        now = datetime(2026, 7, 7, 14, 30, tzinfo=TZ)
        short_res = make_short_res(now, {})

        result = api._merge_all(now, short_res, None, {})

        assert len(result["weather"]["hourly_precipitation_mm"]) == 24

    def test_starts_from_next_hour_not_current(self):
        """
        [Given] 14시 30분 현재 시각
        [When]  _merge_all 호출
        [Then]  hourly_precipitation_mm의 첫 항목은 "15시"부터 시작 (현재 시간대는 제외)
        """
        api = make_api()
        now = datetime(2026, 7, 7, 14, 30, tzinfo=TZ)
        short_res = make_short_res(now, {})

        result = api._merge_all(now, short_res, None, {})

        keys = list(result["weather"]["hourly_precipitation_mm"].keys())
        assert keys[0] == "15시"

    def test_window_follows_kst_clock_after_release_hour_update(self):
        """
        [Given] 05시 발표(06시부터 시작하는) 단기예보, 06:16 KST 자동 업데이트
        [When]  _merge_all 호출
        [Then]  속성은 "07시"~다음날 "06시" 24개 (UTC 기준 "22시"로 밀리지 않음)
        """
        api = make_api()
        now = datetime(2026, 10, 19, 6, 16, tzinfo=TZ)
        items = []
        slot = datetime(2026, 10, 19, 6, tzinfo=TZ)
        while slot <= datetime(2026, 10, 22, 0, tzinfo=TZ):
            for cat, val in (("TMP", "20"), ("SKY", "1"), ("PTY", "0"), ("PCP", "강수없음")):
                items.append({"fcstDate": slot.strftime("%Y%m%d"), "fcstTime": slot.strftime("%H%M"),
                              "category": cat, "fcstValue": val})
            slot += timedelta(hours=1)
        short_res = {"response": {"body": {"items": {"item": items}}}}

        result = api._merge_all(now, short_res, None, {})

        keys = list(result["weather"]["hourly_precipitation_mm"].keys())
        assert keys[0] == "07시"
        assert keys[-1] == "06시"
        assert len(keys) == 24

    def test_no_duplicate_hour_keys_across_midnight(self):
        """
        [Given] 다음 24시간이 자정을 넘어 다음날로 이어지는 상황
        [When]  _merge_all 호출
        [Then]  "00시"~"23시" 키가 중복 없이 정확히 한 번씩만 존재
        """
        api = make_api()
        now = datetime(2026, 7, 7, 14, 30, tzinfo=TZ)
        short_res = make_short_res(now, {})

        result = api._merge_all(now, short_res, None, {})

        keys = list(result["weather"]["hourly_precipitation_mm"].keys())
        assert len(keys) == len(set(keys)), "시간대 키 중복 발생"

    def test_hour_key_format_is_zero_padded(self):
        """
        [Given] 임의의 단기예보 데이터
        [When]  _merge_all 호출
        [Then]  시간 키는 "00시"~"09시"처럼 두 자리로 0-padding 됨
        """
        api = make_api()
        now = datetime(2026, 7, 7, 22, 0, tzinfo=TZ)
        short_res = make_short_res(now, {})

        result = api._merge_all(now, short_res, None, {})

        keys = list(result["weather"]["hourly_precipitation_mm"].keys())
        assert "00시" in keys
        assert "0시" not in keys

    def test_values_match_source_pcp_per_hour(self):
        """
        [Given] 15시=1.0mm, 16시=강수없음, 17시=3.0mm로 지정한 단기예보
        [When]  14시 정각에 _merge_all 호출
        [Then]  hourly_precipitation_mm의 각 시각 값이 지정한 PCP와 일치
        """
        api = make_api()
        now = datetime(2026, 7, 7, 14, 0, tzinfo=TZ)
        short_res = make_short_res(now, {15: "1.0mm", 16: "강수없음", 17: "3.0mm"})

        result = api._merge_all(now, short_res, None, {})
        hourly = result["weather"]["hourly_precipitation_mm"]

        assert hourly["15시"] == 1.0
        assert hourly["16시"] == 0.0
        assert hourly["17시"] == 3.0

    def test_updates_correctly_on_next_hourly_refresh(self):
        """
        [Given] 14시 30분 기준 계산 결과와 15시 30분 기준 계산 결과
        [When]  각각 _merge_all 호출 (매시 자동 업데이트를 흉내)
        [Then]  시간이 지나면 현재값(precip_amount)과 속성 시작 시각이
                한 시간씩 앞으로 이동함 (업데이트가 정상적으로 반영됨)
        """
        api = make_api()

        now_1 = datetime(2026, 7, 7, 14, 30, tzinfo=TZ)
        short_res_1 = make_short_res(now_1, {14: "1.0mm", 15: "2.0mm"})
        result_1 = api._merge_all(now_1, short_res_1, None, {})

        now_2 = datetime(2026, 7, 7, 15, 30, tzinfo=TZ)
        short_res_2 = make_short_res(now_2, {14: "1.0mm", 15: "2.0mm"})
        result_2 = api._merge_all(now_2, short_res_2, None, {})

        # 1시간 경과 후 현재값이 14시→15시 값으로 갱신됨
        assert result_1["weather"]["precip_amount"] == 1.0
        assert result_2["weather"]["precip_amount"] == 2.0

        # 속성의 시작 시각도 한 시간 앞으로 이동
        keys_1 = list(result_1["weather"]["hourly_precipitation_mm"].keys())
        keys_2 = list(result_2["weather"]["hourly_precipitation_mm"].keys())
        assert keys_1[0] == "15시"
        assert keys_2[0] == "16시"


# ─────────────────────────────────────────────────────────────────────────────
# 3. sensor.py: precip_amount 센서 state / attributes 노출
# ─────────────────────────────────────────────────────────────────────────────

class TestPrecipAmountSensorExposure:
    """KMACustomSensor가 precip_amount를 state/attributes로 올바르게 노출하는지 검증"""

    def _make_sensor(self, coordinator_data):
        from custom_components.kma_weather.sensor import KMACustomSensor
        coordinator = MagicMock()
        coordinator.data = coordinator_data
        entry = MagicMock()
        entry.entry_id = "test_entry"
        sensor = KMACustomSensor.__new__(KMACustomSensor)
        sensor.coordinator = coordinator
        sensor._type = "precip_amount"
        sensor._entry = entry
        sensor._attr_native_unit_of_measurement = "mm"
        return sensor

    def test_native_value_returns_precip_amount(self):
        """
        [Given] coordinator.data에 weather.precip_amount = 4.0
        [When]  native_value 프로퍼티 접근
        [Then]  4.0 반환
        """
        sensor = self._make_sensor({"weather": {"precip_amount": 4.0}, "air": {}})
        assert sensor.native_value == 4.0

    def test_extra_state_attributes_returns_hours_as_flat_keys(self):
        """
        [Given] coordinator.data에 hourly_precipitation_mm 딕셔너리 존재
        [When]  extra_state_attributes 프로퍼티 접근
        [Then]  "hourly_precipitation_mm" 키로 감싸지 않고
                "15시", "16시" 등이 바로 최상위 속성 키로 노출됨
        """
        hourly = {"15시": 1.0, "16시": 0.0}
        sensor = self._make_sensor({
            "weather": {"precip_amount": 1.0, "hourly_precipitation_mm": hourly},
            "air": {},
        })
        attrs = sensor.extra_state_attributes
        assert attrs == {"15시": 1.0, "16시": 0.0}
        assert "hourly_precipitation_mm" not in attrs

    def test_extra_state_attributes_none_when_hourly_missing(self):
        """
        [Given] hourly_precipitation_mm 키 자체가 없는 상황(예: 데이터 수신 실패 캐시)
        [When]  extra_state_attributes 프로퍼티 접근
        [Then]  None 반환 (크래시 없이 안전하게 처리)
        """
        sensor = self._make_sensor({"weather": {"precip_amount": 0.0}, "air": {}})
        assert sensor.extra_state_attributes is None
