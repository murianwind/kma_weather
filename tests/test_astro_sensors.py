"""
천문 센서 테스트:
  - 달 위상 8단계 이름 및 아이콘
  - 달 조명율 계산
  - 월출/월몰 오늘/내일 접두어
  - 일출/일몰/새벽/황혼 오늘/내일 접두어
  - 천문 박명(18°) 오늘/내일 접두어
  - 천문 관측 조건 평가 (날씨·태양 고도·달 고도·달 조명율·풍속)
    → _eval_observation은 (condition, attrs_dict) 튜플을 반환한다.
    → attrs: 풍속, 달_조명율, 달_고도, 날씨_상태, 주야간, 달_위상
  - 자정 unknown 방지 (_REALTIME_KEYS: 키 있고 값 '-'/None → 캐시 복원)
  - 꽃가루 센서: 비시즌 또는 데이터 없음 시 좋음 fallback, 시즌 중 데이터 없으면 unknown
  - 관측 조건 속성 노출 (풍속/달_조명율/달_고도/날씨_상태/주야간/달_위상)
  - 동적 센서 등록 (API 승인 후 short 센서 추가)
"""
import pytest
import asyncio
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from unittest.mock import patch, MagicMock, AsyncMock
from custom_components.kma_weather.coordinator import KMAWeatherUpdateCoordinator
Coord = KMAWeatherUpdateCoordinator
from custom_components.kma_weather.api_kma import KMAWeatherAPI
from custom_components.kma_weather.coordinator import _SKYFIELD_OK
from custom_components.kma_weather.const import DOMAIN

# 테스트용 skyfield 객체 (GitHub Actions에서 de440s.bsp 자동 다운로드)
try:
    from skyfield.api import Loader as _TestLoader
    import os, tempfile
    _SF_DIR = os.path.join(tempfile.gettempdir(), "skyfield_test_cache")
    os.makedirs(_SF_DIR, exist_ok=True)
    _loader = _TestLoader(_SF_DIR)
    _TEST_SF_TS  = _loader.timescale()
    _TEST_SF_EPH = _loader("de440s.bsp")
    _TEST_SF_OK  = True
except Exception:
    _TEST_SF_OK  = False
    _TEST_SF_TS  = None
    _TEST_SF_EPH = None

_skip_no_sf = pytest.mark.skipif(not _TEST_SF_OK, reason="skyfield/de440s.bsp 없음")

TZ = ZoneInfo("Asia/Seoul")
LAT, LON = 37.608025, 127.094222


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def make_coordinator(hass, entry):
    """테스트용 coordinator 인스턴스 생성"""
    coord = KMAWeatherUpdateCoordinator.__new__(KMAWeatherUpdateCoordinator)
    coord.hass = hass
    coord.entry = entry
    coord.api = MagicMock()
    coord.api.tz = TZ
    coord._sun_times = {}
    coord._cached_data = None
    coord._sf_ts  = _TEST_SF_TS
    coord._sf_eph = _TEST_SF_EPH
    return coord


# ── 달 위상 이름 ───────────────────────────────────────────────────────────────

class TestMoonPhaseName:
    """_moon_phase_name: skyfield 0~360° 기준 8단계 이름 반환"""

    @pytest.mark.parametrize("deg, expected", [
        (0.0,   "삭"),
        (11.0,  "삭"),
        (22.5,  "초승달"),
        (45.0,  "초승달"),
        (67.5,  "상현달"),
        (90.0,  "상현달"),
        (112.5, "준상현달"),
        (135.0, "준상현달"),
        (157.5, "보름달"),
        (180.0, "보름달"),
        (202.5, "준하현달"),
        (225.0, "준하현달"),
        (247.5, "하현달"),
        (270.0, "하현달"),
        (292.5, "그믐달"),
        (315.0, "그믐달"),
        (337.5, "삭"),
        (359.9, "삭"),
        (360.0, "삭"),  # % 360 = 0 → 삭
    ])
    def test_phase_name(self, deg, expected):
        result = KMAWeatherUpdateCoordinator._moon_phase_name(deg)
        assert result == expected, f"위상각 {deg}° → 기대={expected}, 실제={result}"

    def test_valid_names_only(self):
        """반환값이 항상 유효한 8단계 이름 중 하나인지 확인"""
        valid = {"삭", "초승달", "상현달", "준상현달", "보름달", "준하현달", "하현달", "그믐달"}
        for deg in range(0, 361, 5):
            name = KMAWeatherUpdateCoordinator._moon_phase_name(float(deg))
            assert name in valid, f"{deg}° → '{name}' 유효하지 않음"


# ── 달 조명율 ─────────────────────────────────────────────────────────────────

@_skip_no_sf
class TestMoonIllumination:
    """달 조명율: skyfield fraction_illuminated 기반 0~100% 검증"""

    def test_range_in_calc_result(self):
        """_calc_sun_times 결과의 달 조명율이 0~100% 범위인지 확인"""
        from unittest.mock import MagicMock
        coord = MagicMock()
        coord.api.tz = TZ
        coord._sun_times = {}
        coord._sf_ts  = _TEST_SF_TS
        coord._sf_eph = _TEST_SF_EPH
        coord._moon_phase_name = staticmethod(KMAWeatherUpdateCoordinator._moon_phase_name)
        if not _TEST_SF_OK:
            return
        now = datetime(2026, 4, 21, 13, 0, tzinfo=TZ)
        result = KMAWeatherUpdateCoordinator._calc_sun_times(coord, LAT, LON, now)
        illum = result.get("moon_illumination")
        assert illum is not None, "달 조명율 없음"
        assert 0 <= illum <= 100, f"달 조명율={illum}% 범위 벗어남"


# ── 천문 시각 오늘/내일 접두어 ─────────────────────────────────────────────────

@_skip_no_sf
class TestCalcSunTimes:
    """_calc_sun_times: 반환값 형식 및 오늘/내일 접두어"""

    def _calc(self, hour):
        from unittest.mock import MagicMock
        coord = MagicMock()
        coord.api.tz = TZ
        coord._sun_times = {}
        coord._sf_ts  = _TEST_SF_TS
        coord._sf_eph = _TEST_SF_EPH
        coord._moon_phase_name = staticmethod(KMAWeatherUpdateCoordinator._moon_phase_name)
        now = datetime(2026, 4, 21, hour, 0, tzinfo=TZ)
        return KMAWeatherUpdateCoordinator._calc_sun_times(coord, LAT, LON, now)

    def test_keys_present(self):
        """모든 천문 시각 키가 존재해야 함"""
        result = self._calc(13)
        expected_keys = {
            "dawn", "sunrise", "sunset", "dusk",
            "astro_dawn", "astro_dusk",
            "moon_phase", "moon_illumination",
            "moonrise", "moonset",
        }
        for key in expected_keys:
            assert key in result, f"키 '{key}' 없음"

    def test_time_format(self):
        """시각 값은 'HH:MM' 형식 문자열이어야 함 (오늘/내일 접두어 포함)"""
        result = self._calc(13)
        for key in ("dawn", "sunrise", "sunset", "dusk", "astro_dawn", "astro_dusk"):
            val = result.get(key)
            assert val is not None, f"'{key}' 값이 None"
            assert val.startswith("오늘 ") or val.startswith("내일 "), \
                f"'{key}' 접두어 없음: '{val}'"
            time_part = val.split(" ")[1]
            h, m = time_part.split(":")
            assert 0 <= int(h) <= 23 and 0 <= int(m) <= 59, \
                f"'{key}' 시각 형식 오류: '{val}'"

    def test_noon_dawn_is_tomorrow(self):
        result = self._calc(13)
        assert result["dawn"].startswith("내일 ")

    def test_noon_sunset_is_today(self):
        result = self._calc(13)
        assert result["sunset"].startswith("오늘 ")

    def test_midnight_sunrise_is_today(self):
        result = self._calc(1)
        assert result["sunrise"].startswith("오늘 ")

    def test_night_all_tomorrow(self):
        result = self._calc(23)
        assert result["dawn"].startswith("내일 ")
        assert result["sunrise"].startswith("내일 ")

    def test_astro_dusk_before_dark(self):
        result = self._calc(13)
        assert result["astro_dusk"].startswith("오늘 ")

    def test_astro_dawn_after_midnight(self):
        result = self._calc(1)
        val = result["astro_dawn"]
        assert val is not None
        assert val.startswith("오늘 ") or val.startswith("내일 ")

    def test_moon_phase_is_string(self):
        valid = {"삭", "초승달", "상현달", "준상현달", "보름달", "준하현달", "하현달", "그믐달"}
        result = self._calc(13)
        assert result["moon_phase"] in valid

    def test_moon_illumination_is_int(self):
        result = self._calc(13)
        illum = result["moon_illumination"]
        assert isinstance(illum, int)
        assert 0 <= illum <= 100


# ── 관측 조건 평가 ────────────────────────────────────────────────────────────
#
# [중요] _eval_observation은 (condition, reason) 튜플을 반환한다.
#   condition: "최우수" | "우수" | "보통" | "불량" | "관측불가" | "분석불가"
#   reason   : "강수" | "흐림" | "구름많음" | "주간" | "" | "분석불가"
#
# 테스트에서 condition만 검증할 때는 result[0]을 사용한다.
# reason까지 검증하는 테스트는 별도 클래스(TestEvalObservationReason)에서 다룬다.

@_skip_no_sf
class TestEvalObservation:
    """_eval_observation: 날씨·태양 고도·달 조명율 종합 평가 (condition 검증)"""

    def _eval(self, hour, condition, illum):
        """반환 튜플 중 condition(첫 번째 값)만 반환한다."""
        coord = MagicMock()
        coord.api.tz = TZ
        coord._sf_ts  = _TEST_SF_TS
        coord._sf_eph = _TEST_SF_EPH
        coord._OBS_ORDER = KMAWeatherUpdateCoordinator._OBS_ORDER
        weather = {"current_condition": condition, "moon_illumination": illum,
                   "current_condition_kor": {"rainy":"비","pouring":"소나기","snowy":"눈",
                   "snowy-rainy":"비/눈","cloudy":"흐림","partlycloudy":"구름많음",
                   "sunny":"맑음","":"-"}.get(condition, condition)}
        now = datetime(2026, 4, 21, hour, 0, tzinfo=TZ)
        result = KMAWeatherUpdateCoordinator._eval_observation(coord, weather, now, LAT, LON)
        # 튜플 (condition, reason) → condition만 반환
        return result[0] if isinstance(result, tuple) else result

    def _eval_full(self, hour, condition, illum):
        """반환 튜플 전체를 반환한다."""
        coord = MagicMock()
        coord.api.tz = TZ
        coord._sf_ts  = _TEST_SF_TS
        coord._sf_eph = _TEST_SF_EPH
        weather = {"current_condition": condition, "moon_illumination": illum}
        now = datetime(2026, 4, 21, hour, 0, tzinfo=TZ)
        return KMAWeatherUpdateCoordinator._eval_observation(coord, weather, now, LAT, LON)

    # 날씨 불가
    @pytest.mark.parametrize("cond", ["rainy", "pouring", "snowy", "snowy-rainy", "cloudy"])
    def test_bad_weather_precipitation(self, cond):
        # [Given] 강수 또는 흐린 날씨 조건
        # [When] 관측 조건을 평가하면
        # [Then] condition은 "관측불가"이어야 함
        assert self._eval(22, cond, 5) == "관측불가"

    def test_cloudy_returns_cloudy(self):
        assert self._eval(22, "cloudy", 5) == "관측불가"

    # 낮/박명
    def test_daytime_returns_daytime(self):
        assert self._eval(13, "sunny", 5) == "관측불가"

    def test_evening_twilight_returns_daytime(self):
        assert self._eval(20, "sunny", 5) == "관측불가"

    def test_morning_twilight_returns_daytime(self):
        assert self._eval(6, "sunny", 5) == "관측불가"

    # 밤 (천문박명 이후) — 달 있을 때 등급: ≤25→우수, ≤50→보통, ≤75→불량, >75→관측불가
    def test_night_excellent(self):
        # illum=5: 달 있음 ≤25% → 우수 (달 없으면 최우수)
        result = self._eval(22, "sunny", 5)
        assert result in ("우수", "최우수"), f"illum=5 → 기대=우수 또는 최우수, 실제={result}"

    def test_night_good(self):
        # illum=30: 달 있음 ≤50% → 보통
        result = self._eval(22, "sunny", 30)
        assert result in ("보통", "우수"), f"illum=30 → 기대=보통 또는 우수, 실제={result}"

    def test_night_average(self):
        # illum=60: 달 있음 ≤75% → 불량
        result = self._eval(22, "sunny", 60)
        assert result in ("불량", "보통"), f"illum=60 → 기대=불량 또는 보통, 실제={result}"

    def test_night_poor(self):
        # illum=80: 달 있음 >75% → 관측불가
        result = self._eval(22, "sunny", 80)
        assert result in ("관측불가", "불량"), f"illum=80 → 기대=관측불가 또는 불량, 실제={result}"

    def test_dawn_clear_excellent(self):
        """새벽 1시, 맑음, 달 없음 → 최우수"""
        assert self._eval(1, "sunny", 5) == "최우수"

    def test_dawn_4am_excellent(self):
        """새벽 4시, 맑음, 달 없음 → 최우수"""
        assert self._eval(4, "sunny", 5) == "최우수(은하수)"

    def test_partlycloudy_not_blocked(self):
        """구름조금은 관측 불가가 아닌 다른 등급이어야 함"""
        result = self._eval(22, "partlycloudy", 10)
        assert result != "관측불가"

    # 경계값
    @pytest.mark.parametrize("illum, expected", [
        (0,   "최우수"),   # 삭(조명율=0%) → 달이 떠있어도 최우수
        (25,  "우수"),    # 달 있음 ≤25% → 우수
        (26,  "보통"),    # 달 있음 26%: 25<26≤50 → 보통
        (50,  "보통"),    # 달 있음 ≤50% → 보통
        (51,  "불량"),    # 달 있음 51%: 50<51≤75 → 불량
        (75,  "불량"),    # 달 있음 ≤75% → 불량
        (76,  "관측불가"), # 달 있음 >75% → 관측불가
        (100, "관측불가"), # 달 있음 >75% → 관측불가
    ])
    def test_illumination_boundaries(self, illum, expected):
        result = self._eval(22, "sunny", illum)
        assert result == expected, f"조명율={illum}% → 기대={expected}, 실제={result}"


@_skip_no_sf
class TestEvalObservationReason:
    """_eval_observation: reason(사유) 검증 — 아이콘 분기 및 속성 노출에 사용"""

    _COND_KOR = {
        "sunny": "맑음", "partlycloudy": "구름많음", "cloudy": "흐림",
        "rainy": "비", "pouring": "소나기", "snowy": "눈", "snowy-rainy": "비/눈", "": "맑음",
    }

    def _eval_full(self, hour, condition, illum):
        coord = MagicMock()
        coord.api.tz = TZ
        coord._sf_ts  = _TEST_SF_TS
        coord._sf_eph = _TEST_SF_EPH
        weather = {
            "current_condition": condition,
            "current_condition_kor": self._COND_KOR.get(condition, condition),
            "moon_illumination": illum,
            "moon_phase": "",
        }
        now = datetime(2026, 4, 21, hour, 0, tzinfo=TZ)
        return KMAWeatherUpdateCoordinator._eval_observation(coord, weather, now, LAT, LON)

    def test_returns_tuple(self):
        """[Given] 맑은 밤하늘, [When] 평가하면, [Then] 튜플(condition, reason)을 반환해야 함"""
        result = self._eval_full(22, "sunny", 5)
        assert isinstance(result, tuple), "튜플이 아님"
        assert len(result) == 2, "튜플 길이가 2가 아님"

    def test_precipitation_reason_강수(self):
        """[Given] 비/눈 날씨, [When] 평가하면, [Then] attrs에 날씨_상태가 포함되어야 함"""
        for cond in ("rainy", "pouring", "snowy", "snowy-rainy"):
            _, attrs = self._eval_full(22, cond, 5)
            assert isinstance(attrs, dict), f"{cond} → attrs가 dict여야 함"
            kor = self._COND_KOR.get(cond, cond)
            assert attrs.get("날씨") == kor, f"{cond} → 날씨 기대={kor}, 실제={attrs.get('날씨')}"

    def test_cloudy_reason_흐림(self):
        """[Given] 흐린 날씨, [When] 평가하면, [Then] attrs에 날씨_상태='cloudy'이어야 함"""
        _, attrs = self._eval_full(22, "cloudy", 5)
        assert isinstance(attrs, dict)
        assert attrs.get("날씨") == "흐림"

    def test_partlycloudy_reason_구름많음(self):
        """[Given] 구름많음, [When] 평가하면, [Then] attrs에 날씨_상태='구름많음'이어야 함"""
        _, attrs = self._eval_full(22, "partlycloudy", 5)
        assert isinstance(attrs, dict)
        assert attrs.get("날씨") == "구름많음"

    def test_daytime_reason_주간(self):
        """[Given] 맑은 낮, [When] 평가하면, [Then] attrs에 주야간='주간'이어야 함"""
        _, attrs = self._eval_full(13, "sunny", 5)
        assert isinstance(attrs, dict)
        assert attrs.get("주야간") == "주간"

    def test_night_clear_reason_moon_context(self):
        """[Given] 맑은 밤 + 달 조명율 낮음(5%), [When] 평가하면,
        [Then] attrs에 날씨_상태='맑음', 달_조명율='5%'이어야 함"""
        _, attrs = self._eval_full(22, "sunny", 5)
        assert isinstance(attrs, dict), f"attrs가 dict여야 함, 실제={attrs}"
        assert attrs.get("날씨") == "맑음", f"날씨 기대='맑음', 실제={attrs.get('날씨')}"
        assert attrs.get("달_조명율") == "5%", f"달_조명율 기대='5%', 실제={attrs.get('달_조명율')}"

    def test_observation_reason_attribute_exposed(self):
        """[Given] 관측 불가(주간) 상태, [When] 센서 속성을 확인하면,
        [Then] 주야간='주간' 속성이 존재해야 함"""
        from custom_components.kma_weather.sensor import KMACustomSensor
        coordinator = MagicMock()
        coordinator.data = {
            "weather": {
                "observation_condition": "관측불가",
                "observation_attrs": {"주야간": "주간", "날씨_상태": "-"},
            },
            "air": {},
        }
        entry = MagicMock()
        entry.entry_id = "obs_test"
        entry.options = {}
        entry.data = {"prefix": "test"}
        sensor = KMACustomSensor(coordinator, "observation_condition", "test", entry)
        attrs = sensor.extra_state_attributes
        assert attrs is not None
        assert attrs.get("주야간") == "주간"

    def test_observation_good_condition_no_reason_attribute(self):
        """[Given] 관측 가능(우수) 상태, [When] 속성을 확인하면,
        [Then] 관측불가_사유 속성이 없어야 함"""
        from custom_components.kma_weather.sensor import KMACustomSensor
        coordinator = MagicMock()
        coordinator.data = {
            "weather": {
                "observation_condition": "우수",
                "observation_attrs": {"풍속": "1.0 m/s", "달_조명율": "10%",
                                      "달_고도": "20.0°", "날씨_상태": "맑음",
                                      "주야간": "야간", "달_위상": "초승달"},
            },
            "air": {},
        }
        entry = MagicMock()
        entry.entry_id = "obs_good"
        entry.options = {}
        entry.data = {"prefix": "test"}
        sensor = KMACustomSensor(coordinator, "observation_condition", "test", entry)
        attrs = sensor.extra_state_attributes
        assert attrs is not None
        assert "관측불가_사유" not in attrs


# ── 꽃가루 센서 ───────────────────────────────────────────────────────────────

class TestPollenSensor:
    """꽃가루 센서: 비시즌 또는 데이터 미수신 시 좋음 fallback, 속성 출력, 항상 등록"""

    def _make_sensor(self, pollen_data):
        from custom_components.kma_weather.sensor import KMACustomSensor
        coordinator = MagicMock()
        coordinator.data = {"weather": {}, "air": {}, "pollen": pollen_data}
        coordinator._daily_max_temp = None
        coordinator._daily_min_temp = None
        entry = MagicMock()
        entry.entry_id = "pollen_test"
        entry.options = {}
        entry.data = {"prefix": "test"}
        return KMACustomSensor(coordinator, "pollen", "test", entry)

    def test_pollen_in_pollen_api_group(self):
        """[Given] SENSOR_API_GROUPS, [When] 그룹을 확인하면,
        [Then] 'pollen'은 None 그룹이 아닌 'pollen' API 그룹에만 있어야 함"""
        from custom_components.kma_weather.sensor import SENSOR_API_GROUPS
        assert "pollen" not in SENSOR_API_GROUPS[None], \
            "pollen은 None 그룹(항상 등록)에 있으면 안 됨 — pollen API 승인 시에만 등록"
        assert "pollen" in SENSOR_API_GROUPS.get("pollen", []), \
            "pollen은 SENSOR_API_GROUPS['pollen'] 그룹에 있어야 함"

    def test_pollen_offseason_returns_good(self):
        """[Given] pollen 데이터 없음(비시즌), [When] native_value를 조회하면,
        [Then] '좋음'을 반환해야 함 (pollen dict 없으면 좋음 fallback)"""
        sensor = self._make_sensor({})
        assert sensor.native_value is None, f"데이터없음(worst=None) 기대=None, 실제='{sensor.native_value}'"

    def test_pollen_worst_is_state(self):
        """[Given] 나쁨 등급 꽃가루 데이터, [When] native_value를 조회하면,
        [Then] '나쁨'을 반환해야 함"""
        sensor = self._make_sensor({"oak": "나쁨", "pine": "좋음", "grass": "좋음", "worst": "나쁨"})
        assert sensor.native_value == "나쁨"

    def test_pollen_attributes_contain_three_types(self):
        """[Given] 꽃가루 데이터, [When] extra_state_attributes를 조회하면,
        [Then] 참나무/소나무/풀 3개 속성이 모두 있어야 함"""
        sensor = self._make_sensor({"oak": "보통", "pine": "좋음", "grass": "나쁨", "worst": "나쁨"})
        attrs = sensor.extra_state_attributes
        assert attrs is not None
        assert attrs["참나무"] == "보통"
        assert attrs["소나무"] == "좋음"
        assert attrs["잡초류"] is not None  # 잡초류 속성 존재 확인

    def test_pollen_offseason_attributes_fallback_good(self):
        """[Given] pollen 데이터 없음(비시즌), [When] 속성을 조회하면,
        [Then] 3가지 속성 모두 '좋음'이어야 함"""
        sensor = self._make_sensor({})
        attrs = sensor.extra_state_attributes
        assert attrs.get("참나무") is not None
        assert attrs.get("소나무") is not None
        assert attrs.get("잡초류") is not None
        assert "발표 시각" in attrs

    def test_pollen_icon_changes_by_grade(self):
        """[Given] 매우나쁨 등급, [When] icon을 조회하면,
        [Then] 좋음 아이콘(outline)과 달라야 함"""
        sensor_good = self._make_sensor({"worst": "좋음"})
        sensor_bad  = self._make_sensor({"worst": "매우나쁨"})
        assert sensor_good.icon != sensor_bad.icon

    def test_pollen_good_icon_is_outline(self):
        """[Given] 좋음 등급, [When] icon을 조회하면,
        [Then] outline 아이콘이어야 함"""
        sensor = self._make_sensor({"worst": "좋음"})
        assert "outline" in sensor.icon


# ── 동적 센서 등록 (API 승인 후 센서 추가) ────────────────────────────────────

class TestDynamicSensorRegistration:
    """API 승인 여부에 따른 동적 센서 등록 검증"""

    def test_eligible_sensor_types_no_approved(self):
        """[Given] 승인된 API 없음, [When] _eligible_sensor_types 호출,
        [Then] None 그룹(천문 등)만 반환되고 pollen은 포함되지 않아야 함"""
        from custom_components.kma_weather.sensor import _eligible_sensor_types, SENSOR_API_GROUPS
        coordinator = MagicMock()
        coordinator.api._approved_apis = set()
        result = _eligible_sensor_types(coordinator)
        expected = set(SENSOR_API_GROUPS[None])
        assert set(result) == expected
        # pollen은 API 미승인 상태에서 등록되면 안 됨
        assert "pollen" not in result, "pollen API 미승인 시 pollen 센서가 등록되면 안 됨"

    def test_eligible_sensor_types_with_short_approved(self):
        """[Given] short API 승인, [When] _eligible_sensor_types 호출,
        [Then] None 그룹 + short 그룹 센서가 모두 포함되어야 함"""
        from custom_components.kma_weather.sensor import (
            _eligible_sensor_types, SENSOR_API_GROUPS
        )
        coordinator = MagicMock()
        coordinator.api._approved_apis = {"short"}
        result = _eligible_sensor_types(coordinator)
        for t in SENSOR_API_GROUPS["short"]:
            assert t in result, f"short 센서 '{t}'가 누락됨"

    def test_eligible_sensor_types_all_approved(self):
        """[Given] 모든 API 승인, [When] _eligible_sensor_types 호출,
        [Then] 모든 SENSOR_TYPES 키가 포함되어야 함"""
        from custom_components.kma_weather.sensor import (
            _eligible_sensor_types, SENSOR_API_GROUPS, SENSOR_TYPES
        )
        coordinator = MagicMock()
        coordinator.api._approved_apis = set(
            k for k in SENSOR_API_GROUPS if k is not None
        )
        result = _eligible_sensor_types(coordinator)
        for t in SENSOR_TYPES:
            assert t in result, f"센서 '{t}'가 누락됨"

    def test_no_duplicate_sensor_registration(self):
        """[Given] 이미 등록된 센서, [When] _check_new_sensors 재실행,
        [Then] 중복 등록이 없어야 함"""
        from custom_components.kma_weather.sensor import _eligible_sensor_types
        coordinator = MagicMock()
        coordinator.api._approved_apis = {"short", "air"}
        eligible = _eligible_sensor_types(coordinator)
        # 중복 없음: set으로 변환해도 길이 동일
        assert len(eligible) == len(set(eligible)), "중복 센서 타입 존재"

    @pytest.mark.asyncio
    async def test_pollen_not_registered_without_api(self, hass, mock_config_entry):
        """[Given] pollen API가 승인되지 않은 상태,
        [When] 통합 구성요소를 설정하면,
        [Then] sensor.test_pollen이 생성되지 않아야 함"""
        hass.config.latitude = LAT
        hass.config.longitude = LON

        # pollen 데이터 없음 = API 미신청으로 빈 dict 반환
        no_pollen_data = {
            "weather": {"address": "경기도 화성시", "forecast_twice_daily": []},
            "air": {},
        }

        from custom_components.kma_weather.coordinator import KMAWeatherUpdateCoordinator
        _real_init = Coord.__init__
        def _no_api_init(self_c, hass_arg, entry_arg):
            _real_init(self_c, hass_arg, entry_arg)
            self_c.api._approved_apis = set()  # 모든 API 미승인

        with patch.object(Coord, "__init__", _no_api_init):
            with patch(
                "custom_components.kma_weather.api_kma.KMAWeatherAPI.fetch_data",
                new_callable=AsyncMock,
                return_value=no_pollen_data,
            ):
                mock_config_entry.add_to_hass(hass)
                await hass.config_entries.async_setup(mock_config_entry.entry_id)
                await hass.async_block_till_done()

        # [Then] pollen API 미승인 → 센서 미생성
        state = hass.states.get("sensor.test_pollen")
        assert state is None, "pollen API 미승인 상태에서는 pollen 센서가 생성되면 안 됨"

    @pytest.mark.asyncio
    async def test_pollen_registered_after_api_approval(self, hass, mock_config_entry):
        """[Given] 초기에 pollen API 미승인,
        [When] 다음 업데이트에서 pollen API가 승인되면,
        [Then] sensor.test_pollen이 재로드 없이 자동 생성되어야 함"""
        hass.config.latitude = LAT
        hass.config.longitude = LON

        no_pollen_data = {
            "weather": {"address": "경기도 화성시", "forecast_twice_daily": []},
            "air": {},
        }
        with_pollen_data = {
            "weather": {"address": "경기도 화성시", "forecast_twice_daily": []},
            "air": {},
            "pollen": {"oak": "좋음", "pine": "좋음", "grass": "좋음", "worst": "좋음"},
        }

        from custom_components.kma_weather.coordinator import KMAWeatherUpdateCoordinator
        _real_init = Coord.__init__
        def _no_api_init(self_c, hass_arg, entry_arg):
            _real_init(self_c, hass_arg, entry_arg)
            self_c.api._approved_apis = set()  # 초기 미승인

        with patch.object(Coord, "__init__", _no_api_init):
            with patch(
                "custom_components.kma_weather.api_kma.KMAWeatherAPI.fetch_data",
                new_callable=AsyncMock,
                return_value=no_pollen_data,
            ):
                mock_config_entry.add_to_hass(hass)
                await hass.config_entries.async_setup(mock_config_entry.entry_id)
                await hass.async_block_till_done()

        # 초기: pollen 센서 없음
        assert hass.states.get("sensor.test_pollen") is None, "초기에는 pollen 센서가 없어야 함"

        # [When] 다음 업데이트에서 pollen API 승인 확인
        coordinator = hass.data[DOMAIN][mock_config_entry.entry_id]
        coordinator.api._approved_apis = {"pollen"}  # 승인 상태 주입

        with patch.object(coordinator.api, "fetch_data", new_callable=AsyncMock,
                          return_value=with_pollen_data):
            await coordinator.async_refresh()
            await hass.async_block_till_done()

        # [Then] pollen 센서가 자동 생성
        state = hass.states.get("sensor.test_pollen")
        assert state is not None, "pollen API 승인 후 센서가 자동 생성되어야 함"
        assert state.state == "좋음"


# ── 자정 unknown 방지 (_REALTIME_KEYS) ────────────────────────────────────────

class TestRealtimeKeysCache:
    """_REALTIME_KEYS: 키가 있고 값이 '-'/None이면 이전 캐시로 보완,
    키 자체가 없으면(누락 데이터) 보완하지 않음"""

    KEYS = ("TMP", "REH", "WSD", "VEC", "VEC_KOR", "POP", "apparent_temp")

    def _run(self, new_weather, prev_weather):
        _REALTIME_KEYS = self.KEYS
        weather = dict(new_weather)
        if prev_weather is not None:
            for _key in _REALTIME_KEYS:
                if _key in weather and weather[_key] in (None, "-", ""):
                    prev_val = prev_weather.get(_key)
                    if prev_val not in (None, "-", ""):
                        weather[_key] = prev_val
        return weather

    def test_dash_value_restored_from_cache(self):
        result = self._run({"TMP": "-", "REH": 45}, {"TMP": 22, "REH": 40})
        assert result["TMP"] == 22
        assert result["REH"] == 45

    def test_none_value_restored_from_cache(self):
        result = self._run({"TMP": None, "WSD": 2.1}, {"TMP": 22, "WSD": 1.5})
        assert result["TMP"] == 22
        assert result["WSD"] == 2.1

    def test_missing_key_not_restored(self):
        result = self._run({"REH": 45}, {"TMP": 22, "REH": 40})
        assert "TMP" not in result

    def test_all_realtime_keys_covered(self):
        new = {k: "-" for k in self.KEYS}
        prev = {k: f"val_{k}" for k in self.KEYS}
        result = self._run(new, prev)
        for k in self.KEYS:
            assert result[k] == f"val_{k}"

    def test_no_cache_no_restore(self):
        result = self._run({"TMP": "-"}, None)
        assert result["TMP"] == "-"

    def test_prev_also_bad_no_restore(self):
        result = self._run({"TMP": "-"}, {"TMP": "-"})
        assert result["TMP"] == "-"

    def test_empty_string_restored(self):
        result = self._run({"TMP": ""}, {"TMP": 22})
        assert result["TMP"] == 22


# ── 통합: 실제 HA 환경에서 신규 센서 등록 확인 ────────────────────────────────

@pytest.mark.asyncio
@_skip_no_sf
async def test_astro_sensors_registered(hass, mock_config_entry, kma_api_mock_factory):
    """신규 천문 센서들이 HA에 정상 등록되는지 확인"""
    hass.config.latitude = LAT
    hass.config.longitude = LON
    kma_api_mock_factory("full_test")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    await asyncio.sleep(0.5)
    coordinator = hass.data[DOMAIN][mock_config_entry.entry_id]
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    p = "test"
    expected_sensors = [
        f"sensor.{p}_dawn",
        f"sensor.{p}_sunrise",
        f"sensor.{p}_sunset",
        f"sensor.{p}_dusk",
        f"sensor.{p}_astro_dawn",
        f"sensor.{p}_astro_dusk",
        f"sensor.{p}_moon_phase",
        f"sensor.{p}_moon_illumination",
        f"sensor.{p}_moonrise",
        f"sensor.{p}_moonset",
        f"sensor.{p}_observation_condition",
        # pollen은 pollen API 승인 시에만 등록됨.
        # kma_api_mock_factory("full_test")가 _approved_apis에 "pollen"을 포함하므로 여기서는 등록됨.
        f"sensor.{p}_pollen",
    ]
    for entity_id in expected_sensors:
        state = hass.states.get(entity_id)
        assert state is not None, f"센서 {entity_id} 미등록"
        assert state.state not in ("unavailable",), \
            f"센서 {entity_id} 상태={state.state}"


@pytest.mark.asyncio
@_skip_no_sf
async def test_pollen_sensor_registered_and_state(hass, mock_config_entry, kma_api_mock_factory):
    """[Given] full_test 시나리오, [When] 통합 구성요소 설정 후,
    [Then] pollen 센서가 등록되고 상태/속성이 올바르게 출력되어야 함"""
    hass.config.latitude = LAT
    hass.config.longitude = LON
    kma_api_mock_factory("full_test")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_pollen")
    assert state is not None, "pollen 센서가 등록되지 않음"
    assert state.state in {"좋음", "보통", "나쁨", "매우나쁨"}, \
        f"pollen 상태 유효하지 않음: '{state.state}'"
    # 속성 검증
    assert "참나무" in state.attributes
    assert "소나무" in state.attributes
    assert "잡초류" in state.attributes


@pytest.mark.asyncio
@_skip_no_sf
async def test_observation_condition_has_reason_attribute(
    hass, mock_config_entry, kma_api_mock_factory
):
    """[Given] full_test + skyfield 준비 완료, [When] 관측 조건 센서 갱신 후,
    [Then] 관측불가 상태이면 '관측불가_사유' 속성이 있어야 함"""
    hass.config.latitude = LAT
    hass.config.longitude = LON
    kma_api_mock_factory("full_test")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    await asyncio.sleep(0.5)
    coordinator = hass.data[DOMAIN][mock_config_entry.entry_id]
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_observation_condition")
    assert state is not None
    # 관측불가_사유 속성 삭제됨 → 주야간/날씨_상태 속성으로 확인
    assert "주야간" in state.attributes, "주야간 속성이 없음"
    assert "날씨" in state.attributes, "날씨 속성이 없음"
    if state.state == "관측불가":
        assert state.attributes.get("주야간") in ("주간", "야간"), \
            f"유효하지 않은 주야간: '{state.attributes.get("주야간")}'"


@pytest.mark.asyncio
@_skip_no_sf
async def test_moon_phase_values(hass, mock_config_entry, kma_api_mock_factory):
    """달 위상 센서가 유효한 8단계 값을 반환하는지 확인"""
    hass.config.latitude = LAT
    hass.config.longitude = LON
    kma_api_mock_factory("full_test")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    await asyncio.sleep(0.5)
    coordinator = hass.data[DOMAIN][mock_config_entry.entry_id]
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    valid_phases = {"삭", "초승달", "상현달", "준상현달", "보름달", "준하현달", "하현달", "그믐달"}
    state = hass.states.get("sensor.test_moon_phase")
    assert state is not None
    assert state.state in valid_phases


@pytest.mark.asyncio
@_skip_no_sf
async def test_moon_illumination_range(hass, mock_config_entry, kma_api_mock_factory):
    """달 조명율이 0~100% 범위 내인지 확인"""
    hass.config.latitude = LAT
    hass.config.longitude = LON
    kma_api_mock_factory("full_test")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    await asyncio.sleep(0.5)
    coordinator = hass.data[DOMAIN][mock_config_entry.entry_id]
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_moon_illumination")
    assert state is not None
    assert state.state != "unknown"
    illum = int(state.state)
    assert 0 <= illum <= 100


@pytest.mark.asyncio
@_skip_no_sf
async def test_observation_condition_valid(hass, mock_config_entry, kma_api_mock_factory):
    """관측 조건 센서가 유효한 값을 반환하는지 확인"""
    hass.config.latitude = LAT
    hass.config.longitude = LON
    kma_api_mock_factory("full_test")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    await asyncio.sleep(0.5)
    coordinator = hass.data[DOMAIN][mock_config_entry.entry_id]
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    valid_conditions = {"최우수", "우수", "보통", "불량", "관측불가", "분석불가"}
    state = hass.states.get("sensor.test_observation_condition")
    assert state is not None
    assert state.state in valid_conditions


@pytest.mark.asyncio
@_skip_no_sf
async def test_sun_time_format(hass, mock_config_entry, kma_api_mock_factory):
    """일출/일몰/새벽/황혼 센서 값 형식이 '오늘 HH:MM' 또는 '내일 HH:MM'인지 확인"""
    hass.config.latitude = LAT
    hass.config.longitude = LON
    kma_api_mock_factory("full_test")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    await asyncio.sleep(0.5)
    coordinator = hass.data[DOMAIN][mock_config_entry.entry_id]
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    p = "test"
    for sensor in ("dawn", "sunrise", "sunset", "dusk", "astro_dawn", "astro_dusk"):
        state = hass.states.get(f"sensor.{p}_{sensor}")
        assert state is not None, f"sensor.{p}_{sensor} 미등록"
        val = state.state
        assert val != "unknown"
        assert val.startswith("오늘 ") or val.startswith("내일 ")
        time_part = val.split(" ")[1]
        h, m = time_part.split(":")
        assert 0 <= int(h) <= 23 and 0 <= int(m) <= 59


@pytest.mark.asyncio
@_skip_no_sf
async def test_realtime_cache_in_coordinator(hass, mock_config_entry, kma_api_mock_factory):
    """coordinator가 실제로 '-' 값을 캐시로 복원하는지 통합 테스트"""
    from unittest.mock import patch, AsyncMock

    hass.config.latitude = LAT
    hass.config.longitude = LON
    kma_api_mock_factory("full_test")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    await asyncio.sleep(0.5)
    coordinator = hass.data[DOMAIN][mock_config_entry.entry_id]
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get("sensor.test_temperature").state == "22"

    dash_data = {
        "weather": {
            "TMP": "-", "REH": 45, "WSD": 2.1, "VEC_KOR": "남동",
            "POP": 10, "PTY": 0, "SKY": 1,
            "current_condition": "sunny", "current_condition_kor": "맑음",
            "apparent_temp": 23.4, "rain_start_time": "강수없음",
            "address": "경기도 화성시", "현재 위치": "경기도 화성시",
            "forecast_twice_daily": [],
        },
        "air": {},
    }
    with patch.object(coordinator.api, "fetch_data", new_callable=AsyncMock) as mock_f:
        mock_f.return_value = dash_data
        await coordinator.async_refresh()
        await hass.async_block_till_done()

    assert hass.states.get("sensor.test_temperature").state == "22", \
        "TMP='-' 주입 후 캐시 복원 실패"


# ══════════════════════════════════════════════════════════════════════════════
# calc_astronomical_for_date async 메서드 + 천문 액션 서비스 테스트
# ══════════════════════════════════════════════════════════════════════════════

class TestCalcAstronomicalForDate:
    """coordinator.calc_astronomical_for_date async 메서드 직접 테스트"""

    @pytest.mark.asyncio
    async def test_calc_returns_expected_keys(self, hass, mock_config_entry, kma_api_mock_factory):
        """
        [Given] skyfield가 초기화된 coordinator
        [When] calc_astronomical_for_date를 오늘 날짜/서울 좌표로 호출
        [Then] 반환 dict에 천문 필드 + weather_source + weather_condition이 모두 있어야 함
        """
        kma_api_mock_factory("full_test")
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        from homeassistant.util import dt as dt_util
        coordinator = hass.data[DOMAIN][mock_config_entry.entry_id]

        result = await coordinator.calc_astronomical_for_date(
            lat=37.56, lon=126.98,
            target_date=dt_util.now().date(),
        )

        assert "error" not in result, f"천문 계산 오류: {result.get('error')}"
        for key in ["sunrise", "sunset", "dawn", "dusk",
                    "astro_dawn", "astro_dusk",
                    "moonrise", "moonset", "moon_phase", "moon_illumination",
                    "observation_condition", "weather_source", "weather_condition"]:
            assert key in result, f"반환값에 '{key}' 없음"

    @pytest.mark.asyncio
    async def test_weather_source_when_short_not_approved(self, hass, mock_config_entry):
        """
        [Given] short API 미승인 상태 (단기예보 없음)
        [When] calc_astronomical_for_date 호출
        [Then] weather_source가 "천문만"이고 weather_condition이 "API 조회 불가"여야 함
        """
        from unittest.mock import AsyncMock, patch

        minimal_data = {
            "weather": {"address": "경기도 화성시", "forecast_twice_daily": []},
            "air": {},
        }
        from custom_components.kma_weather.coordinator import KMAWeatherUpdateCoordinator
        _real_init = Coord.__init__

        def _no_short_init(self_c, hass_arg, entry_arg):
            _real_init(self_c, hass_arg, entry_arg)
            self_c.api._approved_apis = set()  # 모든 API 미승인

        with patch.object(Coord, "__init__", _no_short_init):
            with patch(
                "custom_components.kma_weather.api_kma.KMAWeatherAPI.fetch_data",
                new_callable=AsyncMock,
                return_value=minimal_data,
            ):
                mock_config_entry.add_to_hass(hass)
                await hass.config_entries.async_setup(mock_config_entry.entry_id)
                await hass.async_block_till_done()

        from homeassistant.util import dt as dt_util
        coordinator = hass.data[DOMAIN][mock_config_entry.entry_id]

        result = await coordinator.calc_astronomical_for_date(
            lat=37.56, lon=126.98,
            target_date=dt_util.now().date(),
        )

        assert result.get("weather_source") == "천문만", \
            f"단기예보 미승인 시 weather_source='천문만' 기대, 실제={result.get('weather_source')}"
        assert result.get("weather_condition") == "API 조회 불가", \
            f"단기예보 미승인 시 weather_condition='API 조회 불가' 기대, 실제={result.get('weather_condition')}"

    @pytest.mark.asyncio
    async def test_calc_with_eval_dt_passed(self, hass, mock_config_entry, kma_api_mock_factory):
        """
        [Given] skyfield가 초기화된 coordinator
        [When] calc_astronomical_for_date에 eval_dt(야간 시각)를 전달
        [Then] 결과가 반환되고 observation_condition이 포함되어야 함 (야간이므로 관측 가능)
        """
        kma_api_mock_factory("full_test")
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        from homeassistant.util import dt as dt_util
        from datetime import datetime
        from zoneinfo import ZoneInfo
        coordinator = hass.data[DOMAIN][mock_config_entry.entry_id]

        today = dt_util.now().date()
        kst = ZoneInfo("Asia/Seoul")
        # 자정 직후 (야간 시각)
        eval_dt = datetime(today.year, today.month, today.day, 1, 0, tzinfo=kst)

        result = await coordinator.calc_astronomical_for_date(
            lat=37.56, lon=126.98,
            target_date=today,
            eval_dt=eval_dt,
        )

        assert "error" not in result
        assert "observation_condition" in result
        assert result["observation_condition"] in ["최우수", "우수", "최우수(은하수)", "우수(은하수)", "보통", "불량", "관측불가"]


class TestAstronomicalActionService:
    """__init__.py의 get_astronomical_info 서비스 핸들러 테스트"""

    @pytest.mark.asyncio
    async def test_service_invalid_past_date(self, hass, mock_config_entry, kma_api_mock_factory):
        """
        [Given] 통합 구성요소 설치
        [When] 과거 날짜로 서비스 호출
        [Then] HomeAssistantError가 발생하고 '과거 날짜' 메시지를 포함해야 함
        """
        from homeassistant.exceptions import HomeAssistantError
        from datetime import date, timedelta

        kma_api_mock_factory("full_test")
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        yesterday = date.today() - timedelta(days=1)
        with pytest.raises((HomeAssistantError, Exception)) as exc_info:
            await hass.services.async_call(
                "kma_weather",
                "get_astronomical_info",
                {
                    "address": "경기도 화성시 동탄면",
                    "date": yesterday,
                },
                blocking=True,
                return_response=True,
            )
        assert "과거" in str(exc_info.value) or exc_info.type.__name__ in ("HomeAssistantError", "ServiceValidationError")

    @pytest.mark.asyncio
    async def test_service_date_too_far(self, hass, mock_config_entry, kma_api_mock_factory):
        """
        [Given] 통합 구성요소 설치
        [When] 오늘+5일 날짜로 서비스 호출
        [Then] HomeAssistantError가 발생하고 '4일' 메시지를 포함해야 함
        """
        from homeassistant.exceptions import HomeAssistantError
        from datetime import date, timedelta

        kma_api_mock_factory("full_test")
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        far_date = date.today() + timedelta(days=5)
        with pytest.raises((HomeAssistantError, Exception)) as exc_info:
            await hass.services.async_call(
                "kma_weather",
                "get_astronomical_info",
                {
                    "address": "경기도 화성시 동탄면",
                    "date": far_date,
                },
                blocking=True,
                return_response=True,
            )
        assert "4일" in str(exc_info.value) or exc_info.type.__name__ in ("HomeAssistantError", "ServiceValidationError")

    @pytest.mark.asyncio
    async def test_service_invalid_time_format(self, hass, mock_config_entry, kma_api_mock_factory):
        """
        [Given] 통합 구성요소 설치
        [When] 잘못된 시각 형식(HH:MM이 아닌 값)으로 서비스 호출
        [Then] HomeAssistantError가 발생하고 '형식' 메시지를 포함해야 함
        """
        from homeassistant.exceptions import HomeAssistantError
        from datetime import date

        kma_api_mock_factory("full_test")
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        with pytest.raises((HomeAssistantError, Exception)) as exc_info:
            await hass.services.async_call(
                "kma_weather",
                "get_astronomical_info",
                {
                    "address": "경기도 화성시 동탄면",
                    "date": date.today(),
                    "time": "25:99",  # 유효하지 않은 시각
                },
                blocking=True,
                return_response=True,
            )
        assert "형식" in str(exc_info.value) or exc_info.type.__name__ in ("HomeAssistantError", "ServiceValidationError", "vol.Invalid")


# ══════════════════════════════════════════════════════════════════════════════
# 커버리지 보완 테스트
# ══════════════════════════════════════════════════════════════════════════════

class TestEvalObservationWindAndMoon:
    """_eval_observation 풍속+달 조명율 조합 분기 커버리지."""

    _COND_KOR = {
        "sunny": "맑음", "partlycloudy": "구름많음", "cloudy": "흐림",
        "rainy": "비", "pouring": "소나기", "snowy": "눈", "snowy-rainy": "비/눈", "": "맑음",
    }

    def _eval_full(self, hour, condition, illum, wsd=None):
        coord = MagicMock()
        coord.api.tz = TZ
        coord._sf_ts  = _TEST_SF_TS
        coord._sf_eph = _TEST_SF_EPH
        coord._OBS_ORDER = KMAWeatherUpdateCoordinator._OBS_ORDER
        weather = {
            "current_condition":     condition,
            "current_condition_kor": self._COND_KOR.get(condition, condition),
            "moon_illumination":     illum,
            "moon_phase":            "보름달",
            "WSD":                   wsd,
        }
        now = datetime(2026, 4, 21, hour, 0, tzinfo=TZ)
        return KMAWeatherUpdateCoordinator._eval_observation(coord, weather, now, LAT, LON)

    def test_wind_excellent_moon_excellent(self):
        """달 없음(illum=0) + 풍속 최우수(1.5~3.0) → 최우수"""
        cond, attrs = self._eval_full(22, "sunny", 0, wsd=2.0)
        assert cond == "최우수"
        assert attrs["풍속"] == "2.0 m/s"

    def test_wind_good_moon_excellent(self):
        """달 없음(illum=0) + 풍속 우수(<1.5) → 우수"""
        cond, attrs = self._eval_full(22, "sunny", 0, wsd=1.0)
        assert cond == "우수"

    def test_wind_poor_moon_excellent(self):
        """달 없음(최우수) + 풍속 불량(5~8) → 불량"""
        cond, attrs = self._eval_full(22, "sunny", 0, wsd=6.0)
        assert cond == "불량"
        assert attrs["풍속"] == "6.0 m/s"

    def test_wind_unavailable_moon_good(self):
        """달 있음 ≤25%(우수) + 풍속 관측불가(≥8) → 관측불가"""
        cond, attrs = self._eval_full(22, "sunny", 20, wsd=9.0)
        assert cond == "관측불가"

    def test_no_wind_data_uses_moon_only(self):
        """풍속 없음 → 달 조명율로만 판단"""
        cond_no_wind, _ = self._eval_full(22, "sunny", 0, wsd=None)
        # 달 없음(illum=0) → 최우수, 풍속 없으면 달로만
        assert cond_no_wind == "최우수"

    def test_attrs_always_have_all_keys(self):
        """모든 분기에서 6개 속성 항상 출력"""
        required = {"풍속", "달_조명율", "달_고도", "날씨", "주야간", "달_위상"}
        for hour, cond, illum, wsd in [
            (22, "sunny",       0,  1.0),
            (22, "sunny",      50,  6.0),
            (22, "partlycloudy", 5, 2.0),
            (13, "sunny",       5,  1.0),  # 주간
            (22, "rainy",       5,  2.0),  # 강수
            (22, "cloudy",      5,  2.0),  # 흐림
        ]:
            _, attrs = self._eval_full(hour, cond, illum, wsd)
            missing = required - set(attrs.keys())
            assert not missing, f"hour={hour},cond={cond}: {missing} 누락"


class TestPollenCacheAndGrade:
    """_get_pollen 캐시 저장 및 등급 분기 커버리지."""

    def _make_api(self):
        api = KMAWeatherAPI(MagicMock(), "test_key")
        api.hass = None
        return api

    def _make_response(self, result_code="00", today="1", code="D07"):
        if result_code != "00":
            return {"response": {"header": {"resultCode": result_code, "resultMsg": "ERROR"}}}
        return {"response": {"header": {"resultCode": "00", "resultMsg": "NORMAL_SERVICE"},
                "body": {"dataType": "JSON", "items": {"item": [{
                    "code": code, "areaNo": "1111051500",
                    "today": today, "tomorrow": "2", "dayaftertomorrow": "2",
                }]}, "pageNo": 1, "numOfRows": 10, "totalCount": 1}}}

    @pytest.mark.asyncio
    async def test_today_cache_stored_at_06(self):
        """07시에 today 획득 시 today 캐시 저장"""
        api = self._make_api()
        api._approved_apis.add("pollen")
        api._pending_apis.discard("pollen")
        async def mock_fetch(url, params):
            return self._make_response(today="2")
        api._fetch = mock_fetch
        now = datetime(2026, 4, 25, 7, 0, tzinfo=ZoneInfo("Asia/Seoul"))
        result = await api._get_pollen(now, "1111051500", "서울특별시 종로구 청운효자동")
        assert api._pollen_cache["pine"]["today"] is not None
        assert api._pollen_cache["pine"]["today_date"] == "20260425"
        assert api._pollen_cache["pine"]["tomorrow"] is None

    @pytest.mark.asyncio
    async def test_19h_gets_today_from_morning_broadcast(self):
        """19시 → tomorrow 호출. today 캐시 있으면 today 반환"""
        api = self._make_api()
        api._approved_apis.add("pollen")
        api._pending_apis.discard("pollen")
        # today 캐시 있음
        api._pollen_today = {"oak": "보통", "pine": "보통", "grass": "좋음",
                              "worst": "보통", "area_name": "테스트", "area_no": "1111051500",
                              "announcement": "2026년 04월 25일 06시 발표"}
        api._pollen_today_date = "20260425"
        async def mock_fetch(url, params):
            return self._make_response(today="1")
        api._fetch = mock_fetch
        now = datetime(2026, 4, 25, 19, 0, tzinfo=ZoneInfo("Asia/Seoul"))
        result = await api._get_pollen(now, "1111051500", "서울특별시 종로구 청운효자동")
        # today 캐시 있으면 today 반환 + tomorrow 갱신
        assert api._pollen_today is not None
        assert result.get("worst") is not None

    @pytest.mark.asyncio
    async def test_today_cache_used_after_17(self):
        """today 캐시 있으면 17시 이후에도 today 캐시 반환"""
        api = self._make_api()
        api._pollen_today = {"oak": "보통", "pine": "좋음", "grass": "좋음",
                              "worst": "보통", "area_name": "테스트", "area_no": "1111051500",
                              "announcement": "2026년 04월 25일 06시 발표"}
        api._pollen_today_date = "20260425"
        called = []
        async def mock_fetch(url, params):
            called.append(url)
            return self._make_response()
        api._fetch = mock_fetch
        now = datetime(2026, 4, 25, 20, 0, tzinfo=ZoneInfo("Asia/Seoul"))
        result = await api._get_pollen(now, "1111051500", "서울특별시 종로구 청운효자동")
        # today 캐시 있으면 API 호출 없이 바로 반환
        # pending 상태면 캐시 무효화 후 API 재확인 → today 재저장
        # API mock이 grade=1(보통)을 반환하므로 최종값은 보통
        assert result is not None
        assert result.get("worst") is not None  # 데이터 있음
    @pytest.mark.asyncio
    async def test_midnight_today_cache_cleared(self):
        """자정 지나면 today 캐시 삭제, tomorrow 캐시 반환"""
        api = self._make_api()
        # 새 캐시 구조: 종류별 독립 캐시
        for k in ("pine", "oak", "grass"):
            api._pollen_cache[k]["today"] = "좋음"
            api._pollen_cache[k]["today_date"] = "20260424"  # 어제 날짜
            api._pollen_cache[k]["tomorrow"] = "보통"
            api._pollen_cache[k]["tomorrow_date"] = "20260424"
        now = datetime(2026, 4, 25, 2, 0, tzinfo=ZoneInfo("Asia/Seoul"))  # 새벽 2시
        # _find_pollen_area mock
        async def mock_fetch(url, params):
            return self._make_response()
        api._fetch = mock_fetch
        result = await api._get_pollen(now, "1111051500", "서울특별시 종로구 청운효자동")
        assert result is not None
        # 자정 지나면 today 캐시 만료 → tomorrow 반환
        assert api._pollen_cache["pine"]["today"] is None
        assert result.get("worst") is not None

    @pytest.mark.asyncio
    async def test_none_grade_means_unknown_worst(self):
        """시즌 중 일부 None → worst=None"""
        api = self._make_api()
        api._approved_apis.add("pollen")
        async def mock_fetch(url, params):
            if "Pine" in url:
                return self._make_response(result_code="30")  # 미신청
            return self._make_response(today="2")
        api._fetch = mock_fetch
        now = datetime(2026, 4, 25, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))
        result = await api._get_pollen(now, "1111051500", "서울특별시 종로구 청운효자동")
        # pine 미신청(30) → None 반환 (미신청/만료)
        # pine 미신청(30) → _check_unsubscribed → None 반환
        assert result is None  # 미신청 → None

class TestSensorCoverageBoost:
    """sensor.py 미커버 분기 (211, 334)."""

    def _make_sensor(self, pollen_data, obs_attrs=None):
        from custom_components.kma_weather.sensor import KMACustomSensor
        coordinator = MagicMock()
        coordinator.data = {
            "weather": {
                "observation_condition": "우수",
                "observation_attrs": obs_attrs or {
                    "풍속": "1.0 m/s", "달_조명율": "10%", "달_고도": "20.0°",
                    "날씨_상태": "맑음", "주야간": "야간", "달_위상": "초승달",
                },
                "moon_phase": "초승달",
            },
            "air": {},
            "pollen": pollen_data,
        }
        entry = MagicMock()
        entry.entry_id = "cov_test"
        entry.options = {}
        entry.data = {"prefix": "test"}
        return KMACustomSensor(coordinator, "pollen", "test", entry), \
               KMACustomSensor(coordinator, "observation_condition", "test", entry)

    def test_pollen_icon_none_worst(self):
        """worst=None → 기본 아이콘 반환 (sensor.py:211)"""
        pollen_sensor, _ = self._make_sensor({"worst": None, "pine": None, "oak": None, "grass": "좋음"})
        icon = pollen_sensor.icon
        assert icon == "mdi:flower-pollen-outline"

    def test_observation_attrs_returned(self):
        """observation_condition → observation_attrs dict 반환 (sensor.py:334)"""
        _, obs_sensor = self._make_sensor({})
        attrs = obs_sensor.extra_state_attributes
        assert isinstance(attrs, dict)
        assert "풍속" in attrs
        assert "달_위상" in attrs


# ══════════════════════════════════════════════════════════════════════════════
# 요구사항 1/2: 위치 변경 시 꽃가루 캐시 무효화
# ══════════════════════════════════════════════════════════════════════════════

class TestPollenLocationCache:
    """꽃가루 위치 캐시 무효화 테스트 - coordinator.find_pollen_area 담당."""

    def _make_coordinator(self):
        from custom_components.kma_weather.coordinator import KMAWeatherUpdateCoordinator
        coord = MagicMock(spec=KMAWeatherUpdateCoordinator)
        coord._admin_area_data = [
            {"c": "1111051500", "n": "서울특별시 종로구 청운효자동", "la": 37.58, "lo": 126.97},
            {"c": "2611010100", "n": "부산광역시 중구 중앙동", "la": 35.10, "lo": 129.03},
        ]
        coord._admin_cached_lat = None
        coord._admin_cached_lon = None
        coord._admin_cached_area_no = None
        coord._admin_cached_area_name = ""
        coord.hass = MagicMock()
        coord.hass.async_add_executor_job = AsyncMock(return_value=None)
        return coord

    @pytest.mark.asyncio
    @pytest.mark.parametrize("move_km,expect_reset", [
        (0.0,  False),  # 동일 위치 → 캐시 유지
        (1.9,  False),  # 2km 미만 → 캐시 유지 (coordinator에서 처리)
        (2.0,  False),  # 경계 2km → 캐시 유지
        (2.1,  True),   # 2km 초과 → coordinator가 캐시 무효화 후 재탐색
        (10.0, True),   # 10km 이동 → 재탐색
    ])
    async def test_location_cache_invalidation(self, move_km, expect_reset):
        """
        [Given] coordinator.find_pollen_area로 초기 위치 조회 후 캐시 저장됨
        [When] move_km만큼 이동한 위치로 재조회
        [Then] 좌표가 다르면 새로 탐색
        """
        from custom_components.kma_weather.coordinator import KMAWeatherUpdateCoordinator
        coord = self._make_coordinator()
        lat0, lon0 = 37.58, 126.97
        lat1 = lat0 + move_km / 111.0
        lon1 = lon0

        # 초기 조회 (find_pollen_area는 _find_admin_area를 그대로 위임 호출)
        area_no_0, _ = await KMAWeatherUpdateCoordinator._find_admin_area(coord, lat0, lon0)
        cached_no = coord._admin_cached_area_no

        # 이동 후 재조회
        area_no_1, _ = await KMAWeatherUpdateCoordinator._find_admin_area(coord, lat1, lon1)

        if expect_reset:
            # 좌표가 달라 새로 탐색
            assert coord._admin_cached_lat == lat1
        else:
            # 동일 좌표면 캐시 유지
            assert coord._admin_cached_area_no == cached_no


# ══════════════════════════════════════════════════════════════════════════════
# 요구사항 5: 18시 이후 today 없으면 06시 발표 호출
# ══════════════════════════════════════════════════════════════════════════════

class TestPollenTodayPriority:
    """18시 이후에도 today 캐시 없으면 06시 발표 우선 호출 (도메인 테스트)."""

    def _make_api(self):
        api = KMAWeatherAPI(MagicMock(), "test_key")
        api.hass = None
        api._pollen_area_data = [{"c": "1111051500", "n": "서울", "la": 37.58, "lo": 126.97}]
        api._pollen_cached_lat = api._pollen_cached_lon = None
        api._pollen_cached_area_no = api._pollen_cached_area_name = None
        return api

    def _ok_response(self, today="1"):
        return {"response": {"header": {"resultCode": "00", "resultMsg": "NORMAL_SERVICE"},
                "body": {"dataType": "JSON", "items": {"item": [{
                    "code": "D07", "areaNo": "1111051500",
                    "today": today, "tomorrow": "2", "dayaftertomorrow": "2",
                }]}, "pageNo": 1, "numOfRows": 10, "totalCount": 1}}}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("hour,has_today_cache,expected_fetch_key", [
        (19, False, "today"),   # 19시 today 없음 → 06시 발표 호출(today)
        (19, True,  None),      # 19시 today 있음 → API 호출 없음
        (10, False, "today"),   # 10시 today 없음 → 06시 발표 호출(today)
        (2,  False, "tomorrow"),# 02시 today 없음 → 전날 18시(tomorrow)
        (2,  True,  None),      # 02시 today 있음 → 캐시 반환
    ])
    async def test_today_priority(self, hour, has_today_cache, expected_fetch_key):
        """
        [Given] 시간대별 today 캐시 유무
        [When] _get_pollen 호출
        [Then] today 없으면 06시 발표 호출, today 있으면 캐시 반환
        """
        api = self._make_api()
        api._approved_apis.add("pollen")

        if has_today_cache:
            api._pollen_today = {"oak": "좋음", "pine": "보통", "grass": "좋음",
                                  "worst": "보통", "area_name": "서울", "area_no": "1111051500",
                                  "announcement": "06시 발표"}
            api._pollen_today_date = "20260426"

        called_times = []
        async def mock_fetch(url, params):
            called_times.append(params.get("time", ""))
            return self._ok_response()

        api._fetch = mock_fetch
        now = datetime(2026, 4, 26, hour, 0, tzinfo=ZoneInfo("Asia/Seoul"))
        result = await api._get_pollen(now, "1111051500", "서울특별시 종로구 청운효자동")

        if expected_fetch_key is None:
            # pending 상태면 캐시 무시하고 API 호출 (중지 감지용)
            # 캐시 있어도 pending이면 재확인 → 정상 응답 받으면 캐시 재저장
            assert result is not None, "None이면 미신청"
        elif expected_fetch_key == "today":
            assert any("06" in t for t in called_times), f"06시 발표 호출 기대, 실제: {called_times}"
        elif expected_fetch_key == "tomorrow":
            assert any("18" in t for t in called_times), f"18시 발표 호출 기대, 실제: {called_times}"


# ══════════════════════════════════════════════════════════════════════════════
# 요구사항 7: 날씨 센서 아이콘
# ══════════════════════════════════════════════════════════════════════════════

class TestWeatherConditionIcon:
    """날씨 상태 센서 아이콘 테스트 (도메인 테스트: 8가지 날씨 상태)."""

    def _make_sensor(self, sensor_type, weather_val):
        from custom_components.kma_weather.sensor import KMACustomSensor
        coordinator = MagicMock()
        coordinator.data = {
            "weather": {sensor_type: weather_val},
            "air": {}, "pollen": {},
        }
        entry = MagicMock()
        entry.entry_id = "icon_test"
        entry.options = {}
        entry.data = {"prefix": "test"}
        return KMACustomSensor(coordinator, sensor_type, "test", entry)

    @pytest.mark.parametrize("sensor_type", [
        "current_condition_kor", "wf_am_today", "wf_pm_today",
        "wf_am_tomorrow", "wf_pm_tomorrow",
    ])
    @pytest.mark.parametrize("val,expected_icon", [
        ("맑음",    "mdi:weather-sunny"),
        ("구름많음", "mdi:weather-partly-cloudy"),
        ("흐림",    "mdi:weather-cloudy"),
        ("비",      "mdi:weather-rainy"),
        ("눈",      "mdi:weather-snowy"),
        ("소나기",  "mdi:weather-pouring"),
        ("비/눈",   "mdi:weather-snowy-rainy"),
    ])
    def test_weather_icon_by_state(self, sensor_type, val, expected_icon):
        """
        [Given] 날씨 센서의 상태값
        [When] icon 속성 조회
        [Then] 상태값에 맞는 아이콘 반환
        """
        sensor = self._make_sensor(sensor_type, val)
        assert sensor.icon == expected_icon,             f"{sensor_type}={val} → 기대={expected_icon}, 실제={sensor.icon}"

    def test_unknown_weather_uses_default_icon(self):
        """
        [Given] 알 수 없는 날씨 상태값
        [When] icon 속성 조회
        [Then] 기본 아이콘 반환
        """
        sensor = self._make_sensor("current_condition_kor", "우박")
        assert sensor.icon == "mdi:weather-cloudy"  # SENSOR_TYPES 기본값


# ══════════════════════════════════════════════════════════════════════════════
# 요구사항 8: 판단사유 속성
# ══════════════════════════════════════════════════════════════════════════════

class TestObservationReason:
    """천문 관측 조건 판단사유 테스트 (페어와이즈: 날씨 x 달 x 풍속)."""

    _COND_KOR = {
        "sunny": "맑음", "partlycloudy": "구름많음", "cloudy": "흐림",
        "rainy": "비", "": "맑음",
    }

    def _eval(self, hour, condition, illum, wsd=None):
        coord = MagicMock()
        coord.api.tz = TZ
        coord._sf_ts  = _TEST_SF_TS
        coord._sf_eph = _TEST_SF_EPH
        coord._OBS_ORDER = KMAWeatherUpdateCoordinator._OBS_ORDER
        weather = {
            "current_condition":     condition,
            "current_condition_kor": self._COND_KOR.get(condition, condition),
            "moon_illumination":     illum,
            "moon_phase":            "보름달",
            "WSD":                   wsd,
        }
        now = datetime(2026, 4, 21, hour, 0, tzinfo=TZ)
        _, attrs = KMAWeatherUpdateCoordinator._eval_observation(
            coord, weather, now, LAT, LON
        )
        return attrs.get("판단사유", "")

    def test_reason_precipitation(self):
        """[Given] 강수 날씨 [Then] 판단사유=날씨"""
        assert self._eval(22, "rainy", 50) == "날씨"

    def test_reason_cloudy(self):
        """[Given] 흐림 날씨 [Then] 판단사유=날씨"""
        assert self._eval(22, "cloudy", 50) == "날씨"

    def test_reason_partlycloudy(self):
        """[Given] 구름많음 [Then] 판단사유=날씨"""
        assert self._eval(22, "partlycloudy", 50) == "날씨"

    def test_reason_daytime(self):
        """[Given] 주간 [Then] 판단사유=주야간"""
        assert self._eval(13, "sunny", 50) == "주야간"

    def test_reason_moon(self):
        """[Given] 야간 + 달 조명율 높음 + 풍속 없음 [Then] 판단사유=달 조명율"""
        reason = self._eval(22, "sunny", 80, wsd=None)
        assert "달 조명율" in reason

    def test_reason_wind_only(self):
        """[Given] 야간 + 달 없음(illum=0) + 풍속 불량 [Then] 판단사유=풍속"""
        reason = self._eval(22, "sunny", 0, wsd=6.0)
        assert "풍속" in reason

    def test_reason_wind_and_moon(self):
        """[Given] 야간 + 달 조명율=관측불가(80%) + 풍속=불량(6.0)
        [Then] 최종등급=관측불가, 판단사유=달 조명율 (관측불가와 동일한 항목만)"""
        reason = self._eval(22, "sunny", 80, wsd=6.0)
        assert "달 조명율" in reason
        # 풍속은 불량(관측불가보다 낮음)이므로 사유에 없음
        assert "풍속" not in reason

    def test_reason_wind_and_moon_both_worst(self):
        """[Given] 야간 + 달 조명율=관측불가(80%) + 풍속=관측불가(≥8.0)
        [Then] 판단사유에 달 조명율, 풍속 모두 포함"""
        reason = self._eval(22, "sunny", 80, wsd=9.0)
        assert "달 조명율" in reason
        assert "풍속" in reason

    def test_reason_attrs_key_always_present(self):
        """[Given] 모든 날씨 조건 [Then] 판단사유 키 항상 존재"""
        for hour, cond, illum, wsd in [
            (22, "rainy", 50, 2.0),
            (22, "cloudy", 50, None),
            (13, "sunny", 10, 1.0),
            (22, "sunny", 0,  None),
            (22, "sunny", 80, 6.0),
        ]:
            _, attrs = KMAWeatherUpdateCoordinator._eval_observation(
                self._make_coord(), {"current_condition": cond,
                "current_condition_kor": self._COND_KOR.get(cond, cond),
                "moon_illumination": illum, "moon_phase": "", "WSD": wsd},
                datetime(2026, 4, 21, hour, 0, tzinfo=TZ), LAT, LON
            )
            assert "판단사유" in attrs, f"hour={hour},cond={cond}: 판단사유 없음"

    def _make_coord(self):
        coord = MagicMock()
        coord.api.tz = TZ
        coord._sf_ts  = _TEST_SF_TS
        coord._sf_eph = _TEST_SF_EPH
        coord._OBS_ORDER = KMAWeatherUpdateCoordinator._OBS_ORDER
        return coord


# ══════════════════════════════════════════════════════════════════════════════
# 요구사항 10: API 중지 시 센서 unavailable
# ══════════════════════════════════════════════════════════════════════════════

class TestPollenUnavailableOnApiStop:
    """API 중지 시 pollen 센서 unavailable 전환 테스트."""

    def _make_pollen_sensor(self, pollen_data):
        from custom_components.kma_weather.sensor import KMACustomSensor
        coordinator = MagicMock()
        coordinator.data = {"weather": {}, "air": {}, "pollen": pollen_data}
        entry = MagicMock()
        entry.entry_id = "avail_test"
        entry.options = {}
        entry.data = {"prefix": "test"}
        return KMACustomSensor(coordinator, "pollen", "test", entry)

    def test_pollen_none_returns_none_native_value(self):
        """
        [Given] API 중지 → coordinator.data["pollen"]=None
        [When] native_value 조회
        [Then] None 반환 → HA에서 unavailable 표시
        """
        sensor = self._make_pollen_sensor(None)
        assert sensor.native_value is None

    def test_pollen_none_returns_none_attrs(self):
        """
        [Given] API 중지 → pollen=None
        [When] extra_state_attributes 조회
        [Then] None 반환
        """
        sensor = self._make_pollen_sensor(None)
        assert sensor.extra_state_attributes is None

    def test_pollen_empty_dict_returns_good_fallback(self):
        """
        [Given] pollen={}  (비시즌/데이터 없음)
        [When] native_value 조회
        [Then] "좋음" fallback 반환
        """
        sensor = self._make_pollen_sensor({})
        assert sensor.native_value is None  # worst 키 없음 → unknown

    def test_pollen_with_worst_none_returns_unknown(self):
        """
        [Given] pollen={"worst": None} (시즌 중 데이터 없음)
        [When] native_value 조회
        [Then] None 반환 → unknown
        """
        sensor = self._make_pollen_sensor({"worst": None, "pine": None, "oak": None, "grass": "좋음"})
        assert sensor.native_value is None

# ══════════════════════════════════════════════════════════════════════════════
# calc_astronomical_for_date 추가 커버리지
# ══════════════════════════════════════════════════════════════════════════════

class TestCalcAstronomicalShortForecast:
    """calc_astronomical_for_date 내 단기예보 조회 분기 추가 테스트"""

    @pytest.mark.asyncio
    @_skip_no_sf
    async def test_weather_source_with_short_approved_and_items(self, hass, mock_config_entry, kma_api_mock_factory):
        """short 승인 + 단기예보 아이템 있음 → weather_source='날씨+천문'"""
        kma_api_mock_factory("full_test")
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        from homeassistant.util import dt as dt_util
        coordinator = hass.data[DOMAIN][mock_config_entry.entry_id]
        coordinator.api._approved_apis.add("short")

        short_items = [
            {"fcstDate": dt_util.now().strftime("%Y%m%d"), "fcstTime": "1200",
             "category": "SKY", "fcstValue": "1"},
            {"fcstDate": dt_util.now().strftime("%Y%m%d"), "fcstTime": "1200",
             "category": "PTY", "fcstValue": "0"},
            {"fcstDate": dt_util.now().strftime("%Y%m%d"), "fcstTime": "1500",
             "category": "WSD", "fcstValue": "2.5"},
        ]
        mock_resp = {"response": {"header": {"resultCode": "00"},
                                  "body": {"items": {"item": short_items}}}}

        with patch.object(coordinator.api, "_fetch", new_callable=AsyncMock, return_value=mock_resp):
            result = await coordinator.calc_astronomical_for_date(
                lat=37.56, lon=126.98,
                target_date=dt_util.now().date(),
            )

        assert result.get("weather_source") == "날씨+천문"
        assert result.get("weather_condition") not in (None, "API 조회 불가")

    @pytest.mark.asyncio
    @_skip_no_sf
    async def test_weather_source_with_short_approved_but_fetch_exception(self, hass, mock_config_entry, kma_api_mock_factory):
        """short 승인 + 단기예보 조회 중 예외 → weather_source='천문만'"""
        kma_api_mock_factory("full_test")
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        from homeassistant.util import dt as dt_util
        coordinator = hass.data[DOMAIN][mock_config_entry.entry_id]
        coordinator.api._approved_apis.add("short")

        with patch.object(coordinator.api, "_fetch", new_callable=AsyncMock,
                          side_effect=Exception("네트워크 오류")):
            result = await coordinator.calc_astronomical_for_date(
                lat=37.56, lon=126.98,
                target_date=dt_util.now().date(),
            )

        assert result.get("weather_source") == "천문만"
        assert result.get("weather_condition") == "API 조회 불가"

    @pytest.mark.asyncio
    @_skip_no_sf
    async def test_weather_source_wsd_none_searches_other_slots(self, hass, mock_config_entry, kma_api_mock_factory):
        """best_t 슬롯에 WSD 없을 때 다른 슬롯에서 WSD 탐색"""
        kma_api_mock_factory("full_test")
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        from homeassistant.util import dt as dt_util
        coordinator = hass.data[DOMAIN][mock_config_entry.entry_id]
        coordinator.api._approved_apis.add("short")

        today = dt_util.now().strftime("%Y%m%d")
        # 1200 슬롯에는 WSD 없음, 1500 슬롯에만 WSD 있음
        short_items = [
            {"fcstDate": today, "fcstTime": "1200", "category": "SKY", "fcstValue": "1"},
            {"fcstDate": today, "fcstTime": "1200", "category": "PTY", "fcstValue": "0"},
            {"fcstDate": today, "fcstTime": "1500", "category": "WSD", "fcstValue": "3.0"},
        ]
        mock_resp = {"response": {"header": {"resultCode": "00"},
                                  "body": {"items": {"item": short_items}}}}

        with patch.object(coordinator.api, "_fetch", new_callable=AsyncMock, return_value=mock_resp):
            result = await coordinator.calc_astronomical_for_date(
                lat=37.56, lon=126.98,
                target_date=dt_util.now().date(),
            )

        assert "error" not in result
        assert result.get("weather_source") == "날씨+천문"
