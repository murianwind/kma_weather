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
    """precip_amount 센서 속성: 오늘 하루(00시~23시) 시간대별 강수량 검증.
    HA UI가 속성 키를 이름순으로 정렬하므로 키를 오늘 00시~23시로 고정한다.
    이미 지난 시간(현재 시각 포함)은 값이 없어 "-"로 표시한다."""

    @staticmethod
    def _hourly(now, hourly_pcp=None, **kw):
        api = make_api()
        short_res = make_short_res(now, hourly_pcp or {}, **kw)
        return api._merge_all(now, short_res, None, {})["weather"]["hourly_precipitation_mm"]

    def test_keys_are_today_00_to_23_in_order(self):
        """
        [Given] 이틀치 단기예보
        [When]  _merge_all 호출
        [Then]  키는 항상 "00시"~"23시" 24개, 시간 순서
        """
        hourly = self._hourly(datetime(2026, 7, 7, 14, 30, tzinfo=TZ))

        assert list(hourly.keys()) == [f"{h:02d}시" for h in range(24)]

    def test_past_and_current_hours_are_dash_and_future_hours_have_values(self):
        """
        [Given] 10시 19분(10시 15분 업데이트), 11시=2.0mm
        [When]  _merge_all 호출
        [Then]  00시~10시는 "-", 11시부터 예보 값
        """
        hourly = self._hourly(datetime(2026, 7, 7, 10, 19, tzinfo=TZ), {11: "2.0mm"})

        assert all(hourly[f"{h:02d}시"] == "-" for h in range(0, 11))
        assert hourly["11시"] == 2.0
        assert hourly["12시"] == 0
        assert hourly["23시"] == 0

    def test_tomorrow_slots_are_not_included(self):
        """
        [Given] 오늘 23시=0, 내일 05시=9.0mm인 이틀치 예보 (시각 키는 오늘 것만)
        [When]  _merge_all 호출
        [Then]  "05시"는 오늘 예보 값(내일 값 9.0이 덮어쓰지 않음)
        """
        now = datetime(2026, 7, 7, 1, 0, tzinfo=TZ)
        api = make_api()
        short_res = make_short_res(now, {})
        for it in short_res["response"]["body"]["items"]["item"]:
            if it["fcstDate"] == "20260708" and it["fcstTime"] == "0500" and it["category"] == "PCP":
                it["fcstValue"] = "9.0mm"

        hourly = api._merge_all(now, short_res, None, {})["weather"]["hourly_precipitation_mm"]

        assert hourly["05시"] == 0

    def test_window_follows_kst_clock_after_release_hour_update(self):
        """
        [Given] 05시 발표(06시부터 시작하는) 단기예보, 06:16 KST 자동 업데이트
        [When]  _merge_all 호출
        [Then]  00시~06시 "-", 07시부터 값
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

        hourly = api._merge_all(now, short_res, None, {})["weather"]["hourly_precipitation_mm"]

        assert hourly["06시"] == "-"
        assert hourly["07시"] == 0
        assert hourly["23시"] == 0

    def test_hour_key_format_is_zero_padded(self):
        """
        [Given] 임의의 단기예보 데이터
        [When]  _merge_all 호출
        [Then]  시간 키는 "00시"~"09시"처럼 두 자리로 0-padding 됨
        """
        keys = list(self._hourly(datetime(2026, 7, 7, 22, 0, tzinfo=TZ)).keys())

        assert "00시" in keys
        assert "0시" not in keys

    def test_values_match_source_pcp_per_hour(self):
        """
        [Given] 15시=1.0mm, 16시=강수없음, 17시=3.0mm, 18시=1mm 미만으로 지정한 단기예보
        [When]  14시 정각에 _merge_all 호출
        [Then]  각 시각 값이 PCP와 일치 ("1mm 미만"은 "~1")
        """
        hourly = self._hourly(datetime(2026, 7, 7, 14, 0, tzinfo=TZ),
                              {15: "1.0mm", 16: "강수없음", 17: "3.0mm", 18: "1mm 미만"})

        assert hourly["15시"] == 1.0
        assert hourly["16시"] == 0
        assert hourly["17시"] == 3.0
        assert hourly["18시"] == "~1"

    def test_hour_turns_dash_on_next_hourly_refresh(self):
        """
        [Given] 10시 30분과 11시 30분 기준 계산 결과
        [When]  각각 _merge_all 호출 (매시 자동 업데이트를 흉내)
        [Then]  11시 값이 10시 30분에는 값, 11시 30분에는 "-"
        """
        before = self._hourly(datetime(2026, 7, 7, 10, 30, tzinfo=TZ), {11: "2.0mm"})
        after = self._hourly(datetime(2026, 7, 7, 11, 30, tzinfo=TZ), {11: "2.0mm"})

        assert before["11시"] == 2.0
        assert after["11시"] == "-"


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
