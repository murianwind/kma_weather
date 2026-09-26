"""
test_coverage_boost.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[변경 이력]
  - test_haversine_known_distance() 제거 → test_coordinator_validation.py 에 있음
  - TestLandCodeMapping 클래스 제거     → test_coordinator_validation.py 에 있음
"""
import pytest
import aiohttp
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from unittest.mock import AsyncMock, MagicMock

from custom_components.kma_weather.api_kma import KMAWeatherAPI, _safe_float

# autouse fixture(conftest.py)가 KMAWeatherAPI._discover_airkorea_station_code를
# 매 테스트마다 None 반환 mock으로 기본 차단하므로, 그 실제 동작 자체를
# 검증하는 테스트는 이 원본 참조로 복원해서 써야 한다.
_REAL_DISCOVER_AIRKOREA_STATION_CODE = KMAWeatherAPI._discover_airkorea_station_code

# ─────────────────────────────────────────────────────────────────────────────
# 1. _safe_float
# ─────────────────────────────────────────────────────────────────────────────
class TestSafeFloat:
    def test_none_returns_none(self): assert _safe_float(None) is None
    def test_empty_string_returns_none(self): assert _safe_float("") is None
    def test_dash_returns_none(self): assert _safe_float("-") is None
    def test_valid_int_string(self): assert _safe_float("22") == 22.0
    def test_valid_float_string(self): assert _safe_float("3.14") == pytest.approx(3.14)
    def test_invalid_string_returns_none(self): assert _safe_float("abc") is None

# ─────────────────────────────────────────────────────────────────────────────
# 2. _calculate_apparent_temp
# ─────────────────────────────────────────────────────────────────────────────
class TestApparentTemp:
    def _api(self):
        return KMAWeatherAPI(MagicMock(), "key")

    def test_wind_chill_branch(self):
        api = self._api()
        result = api._calculate_apparent_temp(temp=5, reh=60, wsd=3)
        assert result is not None
        assert isinstance(result, float)
        assert result < 5

    def test_heat_index_branch(self):
        api = self._api()
        result = api._calculate_apparent_temp(temp=30, reh=70, wsd=1)
        assert result is not None
        assert isinstance(result, float)

    def test_default_branch_returns_temp(self):
        api = self._api()
        result = api._calculate_apparent_temp(temp=20, reh=30, wsd=0.5)
        assert result == 20

    def test_none_temp_returns_none(self):
        api = self._api()
        assert api._calculate_apparent_temp(temp=None, reh=50, wsd=2) is None

    def test_string_temp_parsed(self):
        api = self._api()
        result = api._calculate_apparent_temp(temp="15", reh=50, wsd=0)
        assert result == 15

# ─────────────────────────────────────────────────────────────────────────────
# 3. _get_vec_kor
# ─────────────────────────────────────────────────────────────────────────────
class TestGetVecKor:
    def _api(self):
        return KMAWeatherAPI(MagicMock(), "key")

    @pytest.mark.parametrize("vec,expected", [
        (0, "북"), (22.5, "북동"), (67.5, "동"), (112.5, "남동"),
        (157.5, "남"), (202.5, "남서"), (247.5, "서"), (292.5, "북서"),
        (337.5, "북"), (360, "북"),
    ])
    def test_directions(self, vec, expected):
        api = self._api()
        assert api._get_vec_kor(vec) == expected

    def test_none_vec_returns_none(self):
        api = self._api()
        assert api._get_vec_kor(None) is None

# ─────────────────────────────────────────────────────────────────────────────
# 4. _translate_mid_condition
# ─────────────────────────────────────────────────────────────────────────────
class TestTranslateMidCondition:
    def _api(self):
        return KMAWeatherAPI(MagicMock(), "key")

    @pytest.mark.parametrize("wf,expected_kor", [
        ("맑음",       "맑음"),
        ("구름많음",   "구름많음"),
        ("흐림",       "흐림"),
        ("비",         "비"),
        ("눈",         "눈"),
        ("구름많고 비", "구름많고 비"),
        ("흐리고 눈",   "흐리고 눈"),
        ("예상외문장 비", "비"),
    ])
    def test_kor_mapping(self, wf, expected_kor):
        api = self._api()
        assert api._translate_mid_condition_kor(wf) == expected_kor

    def test_translate_mid_condition_wrapper(self):
        api = self._api()
        result = api._translate_mid_condition("맑음")
        assert result == "sunny"

    def test_get_condition_wrapper(self):
        api = self._api()
        assert api._get_condition("1", "0") == "sunny"
        assert api._get_condition("4", "0") == "cloudy"
        assert api._get_condition("1", "1") == "rainy"

# ─────────────────────────────────────────────────────────────────────────────
# 5. _wgs84_to_tm
# ─────────────────────────────────────────────────────────────────────────────
class TestWgs84ToTm:
    def test_seoul_tm_coords(self):
        api = KMAWeatherAPI(MagicMock(), "key")
        x, y = api._wgs84_to_tm(37.5665, 126.9780)
        assert 100_000 < x < 500_000
        assert 300_000 < y < 700_000

# ─────────────────────────────────────────────────────────────────────────────
# 6. _get_air_quality
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_air_quality_cache_hit():
    api = KMAWeatherAPI(MagicMock(), "key")
    api.lat, api.lon = 37.56, 126.98
    api._cached_station = "화성"
    api._cached_station_lat = 37.56
    api._cached_station_lon = 126.98

    air_json = {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL_SERVICE"},
            "body": {"items": [{
                "pm10Value": "40", "pm10Grade": "2",
                "pm25Value": "18", "pm25Grade": "2",
            }]}
        }
    }

    async def mock_fetch(url, params=None, **kwargs):
        assert "MsrstnInfoInqireSvc" not in url, "캐시 HIT인데 측정소 재조회 발생"
        return air_json

    api._fetch = mock_fetch
    result = await api._get_air_quality(37.56, 126.98)
    assert result["station"] == "화성"
    assert result["pm10Grade"] == "보통"

@pytest.mark.asyncio
async def test_air_quality_no_station_items():
    api = KMAWeatherAPI(MagicMock(), "key")
    api.lat, api.lon = 37.56, 126.98

    async def mock_fetch(url, params=None, **kwargs):
        if "MsrstnInfoInqireSvc" in url:
            return {"response": {"body": {"items": []}}}
        return {}

    api._fetch = mock_fetch
    result = await api._get_air_quality(37.56, 126.98)
    assert result == {}

@pytest.mark.asyncio
async def test_air_quality_no_air_data_items():
    api = KMAWeatherAPI(MagicMock(), "key")
    api.lat, api.lon = 37.56, 126.98

    async def mock_fetch(url, params=None, **kwargs):
        if "MsrstnInfoInqireSvc" in url:
            return {"response": {"body": {"items": [{"stationName": "중구"}]}}}
        return {"response": {"body": {"items": []}}}

    api._fetch = mock_fetch
    result = await api._get_air_quality(37.56, 126.98)
    assert result == {"station": "중구"}

@pytest.mark.asyncio
async def test_air_quality_station_lookup_ignores_missing_station_code_field():
    """
    [Given] 근접측정소 조회(getNearbyMsrstnList) 응답에 stationCode 필드가
            아예 없음(실측 확인된 실제 API 동작 — 문서엔 있다고 나오지만 없음)
    [When]  _get_air_quality 호출
    [Then]  stationCode는 애초에 안 쓰므로 영향 없이, 이름 기반으로 대기질
            데이터가 정상 조회된다.
    """
    api = KMAWeatherAPI(MagicMock(), "key")

    async def mock_fetch(url, params=None, **kwargs):
        if "getNearbyMsrstnList" in url:
            return {"response": {"header": {"resultCode": "00"}, "body": {"items": [
                {"tm": 1.9, "addr": "서울 노원구 화랑로 429", "stationName": "화랑로"},
            ]}}}  # 실제 API 그대로 — stationCode 필드 자체가 없음
        return {"response": {"header": {"resultCode": "00"}, "body": {"items": [
            {"pm10Value": "20", "pm10Grade": "1", "pm25Value": "10", "pm25Grade": "1"},
        ]}}}

    api._fetch = mock_fetch
    result = await api._get_air_quality(37.6, 127.09)

    assert result["pm10Value"] == "20"
    assert result["station"] == "화랑로"
    assert api._cached_station == "화랑로"


class TestAirkoreaStationCodeDiscovery:
    """
    측정소코드 확보(_discover_airkorea_station_code)는 공식 API가 안 주는
    코드를 airkorea.or.kr의 실시간조회 화면(realSearch)에서 별도로 구하는
    로직이다. 로그인/세션이 필요 없다는 것과, 응답 HTML의 첫 번째(가장
    가까운) 측정소 라디오버튼 값에서 코드/이름을 정확히 파싱하는지를
    검증한다. (실측 확인: 2026-08-18, 완전히 새 쿠키로도 정상 동작)
    """

    def _make_api(self, monkeypatch):
        api = KMAWeatherAPI(MagicMock(), "key")
        api.hass = None
        # conftest.py의 autouse fixture가 기본으로 None mock을 씌워두므로,
        # 실제 동작을 검증하는 이 클래스에서는 원본으로 되돌린다.
        monkeypatch.setattr(KMAWeatherAPI, "_discover_airkorea_station_code", _REAL_DISCOVER_AIRKOREA_STATION_CODE)
        return api

    def _fake_session_cm(self, html_text, status=200):
        class FakeResp:
            def __init__(self, text, status):
                self._text = text
                self.status = status
            async def text(self):
                return self._text
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False

        class FakeSession:
            def __init__(self, text, status):
                self._text = text
                self._status = status
            def post(self, url, data=None, headers=None, timeout=None):
                return FakeResp(self._text, self._status)
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False

        return FakeSession(html_text, status)

    @pytest.mark.asyncio
    async def test_parses_code_and_name_from_first_station(self, monkeypatch):
        """실측 응답과 동일한 형태의 HTML에서 가장 가까운 측정소의
        코드/이름을 정확히 파싱한다."""
        api = self._make_api(monkeypatch)
        html = (
            'var key = \'11fe5e35-7a3b-4915-89c2-32493f7afdb1\';'
            '<input type="radio" value="111312_화랑로_서울 노원구 화랑로 429 태능입구역 8번 출구_206564_457267_stationCode0" checked>'
            '<input type="radio" value="111151_중랑구_서울 중랑구 용마산로 369 건강가정지원센터_208072_453936_stationCode1">'
        )
        monkeypatch.setattr(aiohttp, "ClientSession", lambda: self._fake_session_cm(html))
        code = await api._discover_airkorea_station_code(37.608, 127.094, "서울특별시")
        assert code == "111312"

    @pytest.mark.asyncio
    async def test_http_error_returns_none(self, monkeypatch):
        api = self._make_api(monkeypatch)
        monkeypatch.setattr(aiohttp, "ClientSession", lambda: self._fake_session_cm("", status=500))
        code = await api._discover_airkorea_station_code(37.608, 127.094, "서울특별시")
        assert code is None

    @pytest.mark.asyncio
    async def test_no_station_list_in_html_returns_none(self, monkeypatch):
        api = self._make_api(monkeypatch)
        monkeypatch.setattr(aiohttp, "ClientSession", lambda: self._fake_session_cm("<html>측정소 없음</html>"))
        code = await api._discover_airkorea_station_code(37.608, 127.094, "서울특별시")
        assert code is None

    @pytest.mark.asyncio
    async def test_exception_returns_none(self, monkeypatch):
        api = self._make_api(monkeypatch)
        def boom():
            raise RuntimeError("network down")
        monkeypatch.setattr(aiohttp, "ClientSession", boom)
        code = await api._discover_airkorea_station_code(37.608, 127.094, "서울특별시")
        assert code is None


class TestAirkoreaPageFallbackWithCode:
    """
    _fetch_page_air_quality(station_code)는 realSearch로 key를 발급받고
    getRealChart로 PM10/PM2.5/오존을 한 번에 가져온다. 실측 확인된 실제
    응답 구조(VALUE_10007/10008/10003)를 그대로 재현해서 검증한다.
    """

    def _make_api(self):
        api = KMAWeatherAPI(MagicMock(), "key")
        api.hass = None
        return api

    def _make_session(self, key_html, chart_json, key_status=200, chart_status=200):
        import json as _json

        class FakeResp:
            def __init__(self, text, status):
                self._text = text
                self.status = status
            async def text(self):
                return self._text
            async def json(self, content_type=None):
                return _json.loads(self._text)
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False

        class FakeSession:
            def post(self, url, data=None, headers=None, timeout=None):
                if "realSearch" in url:
                    return FakeResp(key_html, key_status)
                return FakeResp(_json.dumps(chart_json), chart_status)
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False

        return FakeSession()

    @pytest.mark.asyncio
    async def test_no_station_code_returns_empty_without_network_call(self):
        api = self._make_api()
        result = await api._fetch_page_air_quality(None)
        assert result == {}

    @pytest.mark.asyncio
    async def test_success_extracts_pm10_pm25_o3_together(self, monkeypatch):
        """실측 응답(2026-08-18, 화랑로)과 동일한 형태로 검증 —
        PM10/PM2.5/오존이 한 번의 조회로 전부 채워져야 한다."""
        api = self._make_api()
        key_html = "var key = '546606c9-f586-4295-9f63-bc1124120114';"
        chart_json = {"charts": [
            {"VALUE_10007": "29", "VALUE_10008": "19", "VALUE_10003": "0.0095"},
        ]}
        monkeypatch.setattr(aiohttp, "ClientSession", lambda: self._make_session(key_html, chart_json))
        result = await api._fetch_page_air_quality("111312")
        assert result == {"pm10Value": "29", "pm25Value": "19", "o3Value": "0.0095"}

    @pytest.mark.asyncio
    async def test_dash_values_treated_as_missing(self, monkeypatch):
        api = self._make_api()
        key_html = "var key = 'abc';"
        chart_json = {"charts": [
            {"VALUE_10007": "-", "VALUE_10008": "19", "VALUE_10003": None},
            {"VALUE_10007": "29", "VALUE_10008": "-", "VALUE_10003": "0.01"},
        ]}
        monkeypatch.setattr(aiohttp, "ClientSession", lambda: self._make_session(key_html, chart_json))
        result = await api._fetch_page_air_quality("111312")
        assert result == {"pm10Value": "29", "pm25Value": "19", "o3Value": "0.01"}

    @pytest.mark.asyncio
    async def test_key_mint_failure_retries_once_then_gives_up(self, monkeypatch):
        api = self._make_api()
        call_count = {"n": 0}

        class FakeResp:
            def __init__(self, status): self.status = status
            async def text(self): return ""
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False

        class FakeSession:
            def post(self, url, data=None, headers=None, timeout=None):
                call_count["n"] += 1
                return FakeResp(500)
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False

        monkeypatch.setattr(aiohttp, "ClientSession", lambda: FakeSession())
        result = await api._fetch_page_air_quality("111312")
        assert result == {}
        assert call_count["n"] == 2, "1차 실패 후 정확히 한 번 재시도해야 함"

@pytest.mark.asyncio
async def test_air_quality_fetch_returns_none():
    api = KMAWeatherAPI(MagicMock(), "key")
    api.lat, api.lon = 37.56, 126.98

    async def mock_fetch(url, params=None, **kwargs):
        return None

    api._fetch = mock_fetch
    result = await api._get_air_quality(37.56, 126.98)
    assert result == {}

# ─────────────────────────────────────────────────────────────────────────────
# 7. coordinator: 데이터 복구 및 저장 검증
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_restore_daily_temps_success(hass):
    from custom_components.kma_weather.coordinator import KMAWeatherUpdateCoordinator
    entry = MagicMock(data={"api_key": "key", "location_entity": ""}, options={}, entry_id="restore_test")
    coord = KMAWeatherUpdateCoordinator(hass, entry)
    today_str = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d")
    coord._store.async_load = AsyncMock(return_value={
        "date": today_str, "max": 28.5, "min": 12.0, "wf_am": "맑음", "wf_pm": "구름많음",
    })
    await coord._restore_daily_temps()
    assert coord._daily_max_temp == 28.5
    assert coord._daily_min_temp == 12.0
    assert coord._wf_am_today == "맑음"
    assert coord._wf_pm_today == "구름많음"
    assert coord._store_loaded is True

@pytest.mark.asyncio
async def test_restore_daily_temps_date_mismatch(hass):
    from custom_components.kma_weather.coordinator import KMAWeatherUpdateCoordinator
    entry = MagicMock(entry_id="restore_mismatch", data={"api_key": "k", "location_entity": ""}, options={})
    coord = KMAWeatherUpdateCoordinator(hass, entry)
    coord._store.async_load = AsyncMock(return_value={"date": "20200101", "max": 99.0, "min": -99.0})
    await coord._restore_daily_temps()
    assert coord._daily_max_temp is None
    assert coord._daily_min_temp is None
    assert coord._store_loaded is True

@pytest.mark.asyncio
async def test_save_daily_temps(hass):
    from custom_components.kma_weather.coordinator import KMAWeatherUpdateCoordinator
    entry = MagicMock(entry_id="save_test", data={"api_key": "k", "location_entity": ""}, options={})
    coord = KMAWeatherUpdateCoordinator(hass, entry)
    coord._daily_date = date(2025, 6, 1)
    coord._daily_max_temp, coord._daily_min_temp = 30.0, 18.0
    coord._wf_am_today, coord._wf_pm_today = "맑음", "흐림"
    saved = {}
    coord._store.async_save = AsyncMock(side_effect=lambda data: saved.update(data))
    await coord._save_daily_temps()
    assert saved["date"] == "20250601"
    assert saved["max"] == 30.0
    assert saved["min"] == 18.0

# ─────────────────────────────────────────────────────────────────────────────
# 8. coordinator: 위치 해결
# ─────────────────────────────────────────────────────────────────────────────
def test_resolve_location_uses_cached_coords_when_entity_invalid():
    from custom_components.kma_weather.coordinator import KMAWeatherUpdateCoordinator
    entry = MagicMock(data={"api_key": "k", "location_entity": "zone.home"}, options={}, entry_id="cache_fallback")
    hass = MagicMock()
    state = MagicMock(attributes={"latitude": 0.0, "longitude": 0.0})
    hass.states.get.return_value = state
    coord = KMAWeatherUpdateCoordinator.__new__(KMAWeatherUpdateCoordinator)
    coord.hass, coord.entry, coord._last_lat, coord._last_lon = hass, entry, 35.1, 129.0
    lat, lon = coord._resolve_location()
    assert lat == 35.1
    assert lon == 129.0

# ─────────────────────────────────────────────────────────────────────────────
# 9. button & config_flow & sensor
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_button_press_cooldown(hass, kma_api_mock_factory):
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.kma_weather.const import DOMAIN
    from custom_components.kma_weather.button import KMAUpdateButton
    entry = MockConfigEntry(domain=DOMAIN, data={"api_key": "k", "prefix": "cool", "location_entity": ""}, entry_id="cool_test")
    kma_api_mock_factory("full_test")
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    coordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.async_request_refresh = AsyncMock()
    button = KMAUpdateButton(coordinator, entry)
    await button.async_press()
    button._last_press = datetime.now() - timedelta(seconds=3)
    await button.async_press()
    assert coordinator.async_request_refresh.call_count == 1

@pytest.mark.asyncio
async def test_options_flow(hass, mock_config_entry, kma_api_mock_factory):
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"location_entity": "zone.home", "expire_date": "2026-12-31", "apply_date": "2025-01-01"}
    )
    assert result2["type"] == "create_entry"

# ─────────────────────────────────────────────────────────────────────────────
# 10. 유틸리티 헬퍼
# [중복 제거] test_haversine_known_distance, TestLandCodeMapping
#             → test_coordinator_validation.py 에 있으므로 이 파일에서 삭제
# ─────────────────────────────────────────────────────────────────────────────

class TestGetAirGrade:
    def _api(self): return KMAWeatherAPI(MagicMock(), "key")

    @pytest.mark.parametrize("val,p_type,expected", [
        (15, "pm10", "좋음"), (50, "pm10", "보통"), (100, "pm10", "나쁨"), (200, "pm10", "매우나쁨"),
        (5, "pm25", "좋음"), (25, "pm25", "보통"), (50, "pm25", "나쁨"), (100, "pm25", "매우나쁨"),
        (None, "pm10", "정보없음"), ("-", "pm25", "정보없음")
    ])
    def test_all_grades(self, val, p_type, expected):
        assert self._api()._get_air_grade(val, p_type) == expected

# ══════════════════════════════════════════════════════════════════════════════
# _get_pollen 추가 커버리지
# ══════════════════════════════════════════════════════════════════════════════

class TestPollenAdditionalCoverage:
    """_get_pollen 미커버 분기 추가 테스트"""

    def _make_api(self):
        api = KMAWeatherAPI(MagicMock(), "test_key")
        api.hass = None
        api._approved_apis.add("pollen")
        api._pending_apis.discard("pollen")
        return api

    def _ok_response(self, today="1"):
        return {"response": {"header": {"resultCode": "00", "resultMsg": "NORMAL_SERVICE"},
                "body": {"dataType": "JSON", "items": {"item": [{
                    "today": today, "tomorrow": "2",
                }]}, "pageNo": 1, "numOfRows": 10, "totalCount": 1}}}

    def _99_response(self):
        return {"response": {"header": {"resultCode": "99", "resultMsg": "NO_DATA"},
                "body": {"items": {"item": []}}}}

    @pytest.mark.asyncio
    async def test_check_code_99_returns_none_for_season_kinds(self):
        """resultCode=99 → 시즌 항목 None, 비시즌 항목 좋음

        pollen이 이미 승인된 상태이므로(=_make_api 기본값) 소나무 사전 점검
        분기를 타지 않고, 각 항목(pine/oak/grass)을 실제로 개별 조회한다.
        조회 자체는 이루어졌으므로 announcement는 실제 조회 시각 형식으로
        채워지고("데이터없음" 플레이스홀더가 아님), 시즌 항목 값만 99로 인해
        None이 된다.
        """
        api = self._make_api()
        api._fetch = AsyncMock(return_value=self._99_response())
        now = datetime(2026, 5, 1, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))  # oak/pine 시즌
        result = await api._get_pollen(now, "1111051500", "서울")
        assert result is not None
        assert result.get("oak") is None    # 시즌 → unknown
        assert result.get("pine") is None   # 시즌 → unknown
        assert result.get("grass") == "좋음"  # 비시즌 → 좋음
        assert result.get("worst") is None
        assert result.get("announcement") == "2026년 05월 01일 06시 발표"

    @pytest.mark.asyncio
    async def test_never_approved_yet_and_rc99_still_marks_approved(self):
        """
        [Given] 꽃가루 API가 한 번도 승인된 적 없음(_pending 상태, _approved 비어있음)
                + 신청은 유효하지만 해당 지역에 데이터가 없어 resultCode=99 응답
        [When]  _get_pollen 최초 호출
        [Then]  "미신청"이 아니라 "구독은 유효함"으로 판단하여
                _approved_apis에 pollen이 추가됨 (센서가 생성될 수 있게 됨)
                _pending_apis에서는 제거됨
                반환값은 시즌 항목 unknown, 비시즌 항목 좋음으로 정상 처리됨
        """
        api = KMAWeatherAPI(MagicMock(), "test_key")
        api.hass = None
        # 승인 이력이 전혀 없는 최초 상태를 재현 (approved 비어있고 pending에만 존재)
        assert "pollen" not in api._approved_apis
        assert "pollen" in api._pending_apis

        api._fetch = AsyncMock(return_value=self._99_response())
        now = datetime(2026, 5, 1, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))  # oak/pine 시즌

        result = await api._get_pollen(now, "1111051500", "서울")

        assert "pollen" in api._approved_apis, \
            "resultCode=99여도 미신청이 아니므로 승인 처리되어야 함 (센서 생성 사각지대 방지)"
        assert "pollen" not in api._pending_apis
        assert result is not None
        assert result.get("oak") is None
        assert result.get("pine") is None
        assert result.get("grass") == "좋음"
        assert result.get("announcement") == "데이터없음"

    @pytest.mark.asyncio
    async def test_offseason_and_never_approved_still_calls_api_to_check(self):
        """
        [Given] 완전 비시즌(예: 1월)이지만 아직 한 번도 승인된 적 없음
        [When]  _get_pollen 호출
        [Then]  "비시즌이니 API 호출 없이 좋음 반환" 지름길은
                _approved_apis에 pollen이 있을 때만 적용되므로,
                아직 미승인 상태면 API를 호출해서 승인 여부를 확인하러 감
        """
        api = KMAWeatherAPI(MagicMock(), "test_key")
        api.hass = None
        assert "pollen" not in api._approved_apis

        api._fetch = AsyncMock(return_value=self._99_response())
        now = datetime(2026, 1, 15, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))  # 완전 비시즌

        await api._get_pollen(now, "1111051500", "서울")

        api._fetch.assert_called_once()
        assert "pollen" in api._approved_apis

    @pytest.mark.asyncio
    async def test_today_cache_exists_19h_tomorrow_g_none(self):
        """
        [Given] today 캐시 있음 + pollen 승인됨(_pending 없음) + 19시 이후
                tomorrow API가 빈 items 반환 → g=None
        [When]  _get_pollen 호출
        [Then]  today 캐시 반환 + tomorrow 캐시 초기화됨
        """
        api = self._make_api()
        # pine/oak 시즌(4~6월) 내로 날짜 고정 — datetime.now() 사용 시
        # 시즌 밖(예: 7월 이후) 실행되면 pine이 비시즌 처리되어 테스트가 깨짐
        now = datetime(2026, 4, 25, 19, 0, 0, tzinfo=ZoneInfo("Asia/Seoul"))
        today_str = now.strftime("%Y%m%d")

        # _pending에서 제거 + _approved에만 있어야 캐시를 신뢰함
        api._pending_apis.discard("pollen")
        api._approved_apis.add("pollen")

        for k in ("pine", "oak", "grass"):
            api._pollen_cache[k]["today"] = "좋음"
            api._pollen_cache[k]["today_date"] = today_str

        fetch_count = {"n": 0}

        async def mock_fetch(url, params):
            fetch_count["n"] += 1
            return {"response": {"header": {"resultCode": "00"},
                    "body": {"items": {"item": []}}}}

        api._fetch = mock_fetch
        result = await api._get_pollen(now, "1111051500", "서울")

        assert result is not None, "today 캐시 있을 때 None 반환됨"
        assert result.get("pine") == "좋음"
        # grass는 비시즌(8~10월)이라 tomorrow 갱신 대상 아님 → pine/oak만 검증
        for k in ("pine", "oak"):
            assert api._pollen_cache[k]["tomorrow"] is None
            assert api._pollen_cache[k]["tomorrow_date"] is None

    @pytest.mark.asyncio
    async def test_today_cache_exists_19h_tomorrow_updated(self):
        """
        [Given] today 캐시 있음 + pollen 승인됨(_pending 없음) + 19시 이후
        [When]  _get_pollen 호출
        [Then]  today 캐시 반환 + tomorrow 캐시 갱신됨
        """
        api = self._make_api()
        # pine/oak 시즌(4~6월) 내로 날짜 고정 — datetime.now() 사용 시
        # 시즌 밖(예: 7월 이후) 실행되면 pine이 비시즌 처리되어 테스트가 깨짐
        now = datetime(2026, 4, 25, 19, 0, 0, tzinfo=ZoneInfo("Asia/Seoul"))
        today_str = now.strftime("%Y%m%d")

        # _pending에서 제거 + _approved에만 있어야 캐시를 신뢰함
        # (_pending에 있으면 소스코드가 캐시를 즉시 초기화한다)
        api._pending_apis.discard("pollen")
        api._approved_apis.add("pollen")

        for k in ("pine", "oak", "grass"):
            api._pollen_cache[k]["today"] = "좋음"
            api._pollen_cache[k]["today_date"] = today_str

        api._fetch = AsyncMock(return_value=self._ok_response(today="2"))
        result = await api._get_pollen(now, "1111051500", "서울")

        assert result is not None, "today 캐시 있을 때 None 반환됨"
        assert result.get("pine") == "좋음", f"today 캐시 반환 실패: {result.get('pine')}"
        # grass는 8~10월만 시즌 → 6월 기준 비시즌이므로 tomorrow 갱신 대상 아님
        # pine/oak(4~6월 시즌)만 tomorrow 갱신 검증
        for k in ("pine", "oak"):
            assert api._pollen_cache[k]["tomorrow"] is not None, f"{k} tomorrow 캐시 갱신 안 됨"
            assert api._pollen_cache[k]["tomorrow_date"] == today_str


# ══════════════════════════════════════════════════════════════════════════════
# 에어코리아 측정소 캐시 영속화 검증
# ══════════════════════════════════════════════════════════════════════════════

class TestStationCachePersistence:
    """
    재시작 시 에어코리아 측정소 캐시가 유지되는지 검증.

    배경: _cached_station이 저장소(Store) 영속화 없이 API 인스턴스
    메모리에만 있어서, HA 재시작마다 getNearbyMsrstnList API를 다시
    호출하게 되어 '에어코리아_측정소' 호출 카운터가 실제 위치 이동 없이도
    계속 쌓이던 문제를 수정.
    """

    def _make_coordinator(self, hass):
        from custom_components.kma_weather.coordinator import KMAWeatherUpdateCoordinator
        entry = MagicMock()
        entry.data = {"api_key": "key", "location_entity": ""}
        entry.options = {}
        entry.entry_id = "station_cache_test"
        return KMAWeatherUpdateCoordinator(hass, entry)

    @pytest.mark.asyncio
    async def test_restore_station_cache_from_store(self, hass):
        """
        [Given] 저장소에 이전에 저장된 측정소 정보가 있음
        [When]  _restore_station_cache 호출
        [Then]  api._cached_station과 위경도가 저장소 값으로 복구됨
        """
        coord = self._make_coordinator(hass)
        coord._station_store.async_load = AsyncMock(return_value={
            "station": "서석동", "lat": 35.145, "lon": 126.918,
        })

        await coord._restore_station_cache()

        assert coord.api._cached_station == "서석동"
        assert coord.api._cached_station_lat == 35.145
        assert coord.api._cached_station_lon == 126.918

    @pytest.mark.asyncio
    async def test_restore_station_cache_no_stored_data(self, hass):
        """
        [Given] 저장소에 아무것도 없음(최초 설치 등)
        [When]  _restore_station_cache 호출
        [Then]  크래시 없이 api._cached_station은 None으로 유지됨
        """
        coord = self._make_coordinator(hass)
        coord._station_store.async_load = AsyncMock(return_value=None)

        await coord._restore_station_cache()

        assert coord.api._cached_station is None

    @pytest.mark.asyncio
    async def test_restore_station_cache_only_runs_once(self, hass):
        """
        [Given] _restore_station_cache를 두 번 연달아 호출
        [When]  두 번째 호출
        [Then]  저장소 조회(async_load)는 처음 한 번만 일어남
        """
        coord = self._make_coordinator(hass)
        coord._station_store.async_load = AsyncMock(return_value={
            "station": "서석동", "lat": 35.145, "lon": 126.918,
        })

        await coord._restore_station_cache()
        await coord._restore_station_cache()

        coord._station_store.async_load.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_station_cache_writes_current_values(self, hass):
        """
        [Given] api._cached_station에 값이 설정되어 있음
        [When]  _save_station_cache 호출
        [Then]  저장소에 station/station_code/lat/lon이 그대로 기록됨
        """
        coord = self._make_coordinator(hass)
        coord.api._cached_station = "구월동"
        coord.api._cached_station_code = "823661"
        coord.api._cached_station_lat = 37.447
        coord.api._cached_station_lon = 126.731

        saved = {}
        coord._station_store.async_save = AsyncMock(side_effect=lambda d: saved.update(d))

        await coord._save_station_cache()

        assert saved == {"station": "구월동", "station_code": "823661", "lat": 37.447, "lon": 126.731}

    @pytest.mark.asyncio
    async def test_save_station_cache_skips_when_no_station(self, hass):
        """
        [Given] api._cached_station이 아직 None(측정소 조회 전)
        [When]  _save_station_cache 호출
        [Then]  저장소 쓰기(async_save)가 호출되지 않음
        """
        coord = self._make_coordinator(hass)
        coord.api._cached_station = None
        coord._station_store.async_save = AsyncMock()

        await coord._save_station_cache()

        coord._station_store.async_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_restart_does_not_trigger_new_station_search_when_location_unchanged(self, hass):
        """
        [Given] 재시작 후 저장소에서 측정소 캐시가 복구된 상태
                (위치는 이전과 동일, 2km 이상 이동 없음)
        [When]  _get_air_quality 호출
        [Then]  getNearbyMsrstnList(측정소 검색) API는 호출되지 않고
                기존 캐시된 측정소로 바로 대기질 조회만 수행됨
        """
        coord = self._make_coordinator(hass)
        coord._station_store.async_load = AsyncMock(return_value={
            "station": "서석동", "lat": 35.145, "lon": 126.918,
        })
        await coord._restore_station_cache()

        station_search_called = {"n": 0}

        async def mock_fetch(url, params, **kwargs):
            if "MsrstnInfoInqireSvc" in url:
                station_search_called["n"] += 1
                return {"response": {"body": {"items": []}}}
            return {"response": {"body": {"items": [
                {"pm10Value": "30", "pm25Value": "15"}
            ]}}}

        coord.api._fetch = mock_fetch
        # 재시작 후 첫 위치가 캐시된 위치와 거의 동일(2km 이내)
        await coord.api._get_air_quality(35.145, 126.918)

        assert station_search_called["n"] == 0, \
            "재시작 후 위치가 안 바뀌었는데도 측정소를 재검색함"

    @pytest.mark.asyncio
    async def test_location_moved_over_2km_still_triggers_research(self, hass):
        """
        [Given] 캐시된 측정소 위치에서 2km 이상 떨어진 곳으로 이동
        [When]  _get_air_quality 호출
        [Then]  캐시가 무효화되고 측정소를 다시 검색함
                (이 동작 자체는 정상이며 영속화 수정과 무관하게 유지되어야 함)
        """
        coord = self._make_coordinator(hass)
        coord._station_store.async_load = AsyncMock(return_value={
            "station": "서석동", "lat": 35.145, "lon": 126.918,
        })
        await coord._restore_station_cache()

        station_search_called = {"n": 0}

        async def mock_fetch(url, params, **kwargs):
            if "getNearbyMsrstnList" in url:
                station_search_called["n"] += 1
                return {"response": {"body": {"items": [{"stationName": "신도시동"}]}}}
            return {"response": {"body": {"items": [
                {"pm10Value": "30", "pm25Value": "15"}
            ]}}}

        coord.api._fetch = mock_fetch
        # 약 30km 이상 떨어진 위치로 이동
        await coord.api._get_air_quality(35.40, 127.20)

        assert station_search_called["n"] == 1, \
            "2km 이상 이동했는데도 측정소 재검색이 일어나지 않음"


# ══════════════════════════════════════════════════════════════════════════════
# 여름철 체감온도 공식 정정 검증 (기상청 2022.6.2. 공식)
# ══════════════════════════════════════════════════════════════════════════════

class TestSummerApparentTempKMAFormula:
    """
    이전에 미국 NWS Rothfusz Heat Index를 잘못 적용해서
    실제 기상청 발표값보다 크게 높게(예: 30도인데 37.7도) 나오던 문제 수정.
    기상청이 2022.6.2.부터 실제로 쓰는 공식(Steadman 1979 한국형 변형식,
    Stull 습구온도 추정식 기반)으로 교체 후 검증.
    """

    def _api(self):
        return KMAWeatherAPI(MagicMock(), "key")

    def test_matches_kma_published_value_within_tolerance(self):
        """
        [Given] 2026-07-13 11시 기상청 날씨누리 실제 발표값
                (기온 29.7°C, 체감 30.8°C)
        [When]  습도 65~70% 범위로 _calculate_apparent_temp 호출
        [Then]  기상청 발표 체감온도(30.8°C)와 0.5°C 이내로 일치해야 함
        """
        api = self._api()
        result = api._calculate_apparent_temp(29.7, 68, 2.0)
        assert abs(result - 30.8) < 0.5, \
            f"기상청 실제 발표값(30.8)과 너무 차이남: {result}"

    def test_does_not_overestimate_like_old_rothfusz_formula(self):
        """
        [Given] 기온 30°C, 습도 65%
        [When]  _calculate_apparent_temp 호출
        [Then]  기존 잘못된 Rothfusz 공식이 냈던 37~38°C대가 아니라
                실제 기상청 공식대로 31°C 안팎으로 나와야 함
        """
        api = self._api()
        result = api._calculate_apparent_temp(30.0, 65, 2.0)
        assert result < 33.0, f"Rothfusz 방식으로 과대산출됨: {result}"
        assert result > 28.0

    def test_low_humidity_summer_apparent_temp_close_to_actual(self):
        """
        [Given] 기온 30°C, 습도 30%(건조)
        [When]  _calculate_apparent_temp 호출
        [Then]  건조하면 체감온도가 실제 기온보다 낮거나 비슷해야 함
                (Rothfusz 간이식과 달리 저습도에서 실제기온보다 내려갈 수 있음)
        """
        api = self._api()
        result = api._calculate_apparent_temp(30.0, 30, 1.0)
        assert result <= 30.5

    def test_higher_humidity_gives_higher_apparent_temp(self):
        """
        [Given] 같은 기온에서 습도만 다르게(50% vs 80%)
        [When]  각각 _calculate_apparent_temp 호출
        [Then]  습도가 높을수록 체감온도도 높아야 함(단조증가)
        """
        api = self._api()
        low_rh = api._calculate_apparent_temp(30.0, 50, 2.0)
        high_rh = api._calculate_apparent_temp(30.0, 80, 2.0)
        assert high_rh > low_rh

    def test_summer_formula_applies_without_humidity_threshold(self):
        """
        [Given] 기온 25°C, 습도 20%(예전 공식은 40% 미만이면 여름철 공식 자체를 안 씀)
        [When]  _calculate_apparent_temp 호출
        [Then]  습도 40% 문턱 없이도 여름철 공식이 적용됨
                (기온 그대로 반환하는 게 아니라 계산값이 나와야 함)
        """
        api = self._api()
        result = api._calculate_apparent_temp(25.0, 20, 1.0)
        assert result != 25.0

    def test_winter_wind_chill_unaffected_by_summer_formula_change(self):
        """
        [Given] 겨울철 조건(기온 5도 이하, 강풍)
        [When]  _calculate_apparent_temp 호출
        [Then]  기존 Wind Chill 공식 그대로 유지되어야 함(여름철 공식 교체와 무관)
        """
        api = self._api()
        result = api._calculate_apparent_temp(5, 60, 20 / 3.6)
        assert result < 5.0  # 강풍이면 체감온도가 실제기온보다 낮아야 함


# ══════════════════════════════════════════════════════════════════════════════
# 기상특보 3단계 검증: API 판단 → 페이지 검증 → 미해제 특보 병합
# ══════════════════════════════════════════════════════════════════════════════

class TestWarningPageMerge:
    """
    1) API(getPwnCd, 6일 조회 한도)로 특보현황을 파악하고
    2) weather.go.kr 실시간 특보 현황 페이지로 그 판단을 검증하며
    3) 페이지에는 있지만 API 6일 창에는 없는 미해제 특보를 병합해서 추가한다.

    코드-지역명 매핑은 기상청_기상특보구역정보_20260601.csv 기준
    (warn_area_names.json)을 사용한다.
    """

    def _api(self):
        return KMAWeatherAPI(MagicMock(), "key")

    def _page_html(self, rows: list[tuple[str, str, str]]) -> str:
        """rows: (특보종류, 수준, 해당지역) 튜플 목록으로 "특보 발효현황" 요약
        블록 HTML을 생성한다. 실제 페이지에서 예비특보는 이 요약에 나타나지
        않으므로, 수준이 "예비"인 행은 만들지 않는다(실제 동작 재현)."""
        lines = []
        for warn_type, level, region in rows:
            if level == "예비":
                continue
            lines.append(f"o {warn_type}{level} : {region}")
        content = "<br />".join(lines) if lines else "o 없음"
        return f'<div>특보 발효현황<p class="tit">{content}</p></div>'

    def _mock_session_get(self, api, html: str):
        class MockResp:
            status = 200
            async def text(self): return html
            async def __aenter__(self): return self
            async def __aexit__(self, *a): pass
        api.session.get = lambda *a, **kw: MockResp()

    # ── 1단계: 코드→지역명 매핑 ──────────────────────────────────────

    @pytest.mark.asyncio
    async def test_area_code_maps_to_correct_display_name(self):
        """
        [Given] CSV 기준 L1091320 = "제주시북부"
        [When]  _get_warn_area_display_name 호출
        [Then]  "제주시북부" 반환
        """
        api = self._api()
        assert await api._get_warn_area_display_name("L1091320") == "제주시북부"

    @pytest.mark.asyncio
    async def test_unknown_area_code_returns_none(self):
        """
        [Given] 매핑에 없는 코드
        [When]  _get_warn_area_display_name 호출
        [Then]  None 반환 (크래시 없음)
        """
        api = self._api()
        assert await api._get_warn_area_display_name("L9999999") is None

    # ── 2단계: 페이지 검증(API와 일치하는 경우) ──────────────────────

    @pytest.mark.asyncio
    async def test_api_and_page_agree_no_duplicate(self):
        """
        [Given] API가 폭염경보를 활성으로 판단했고, 페이지에도 동일하게 나타남
        [When]  _get_warning 호출
        [Then]  폭염경보가 중복 없이 한 번만 표시됨
        """
        api = self._api()
        api._fetch = AsyncMock(return_value={
            "response": {"header": {"resultCode": "00"},
                "body": {"items": {"item": [
                    {"areaCode": "L1091320", "cancel": "0", "command": "1",
                     "endTime": 0, "tmFc": 202607191000, "warnVar": 12, "warnStress": 1},
                ]}}}
        })
        html = self._page_html([("폭염", "경보", "제주도(제주시북부)")])
        self._mock_session_get(api, html)

        result = await api._get_warning("L1091320")

        assert result == "폭염경보"

    # ── 3단계: 페이지에만 있는 미해제 특보 병합 ──────────────────────

    @pytest.mark.asyncio
    async def test_page_only_warning_gets_merged_in(self):
        """
        [Given] API 6일 창에는 열대야 관련 기록이 전혀 없지만
                (6일보다 오래된 미해제 특보라 창 밖으로 밀려남)
                페이지에는 "제주시북부" 열대야주의보가 여전히 나타남
        [When]  _get_warning 호출
        [Then]  API 결과에 열대야주의보가 병합되어 추가됨
        """
        api = self._api()
        api._fetch = AsyncMock(return_value={
            "response": {"header": {"resultCode": "00"},
                "body": {"items": {"item": []}}}  # API 6일 창엔 아무 기록도 없음
        })
        html = self._page_html([("열대야", "주의보", "제주도(제주시북부)")])
        self._mock_session_get(api, html)

        result = await api._get_warning("L1091320")

        assert result == "열대야주의보"

    @pytest.mark.asyncio
    async def test_jeju_north_real_case_api_heatwave_page_adds_tropical_night(self):
        """
        [Given] 실제 사례 재현: API는 제주시북부 폭염경보(warnStress=1)만 찾고,
                페이지에는 폭염경보(API와 일치) + 7/10 발효된 열대야주의보
                (API 6일 창 밖이라 API엔 없음)가 함께 나타남
        [When]  _get_warning 호출
        [Then]  "폭염경보, 열대야주의보"로 둘 다 포함되어야 함
        """
        api = self._api()
        api._fetch = AsyncMock(return_value={
            "response": {"header": {"resultCode": "00"},
                "body": {"items": {"item": [
                    {"areaCode": "L1091320", "areaName": "제주시북부", "cancel": "0",
                     "command": "7", "endTime": 0, "tmFc": 202607191000,
                     "warnVar": 12, "warnStress": 1, "startTime": 202607191100},
                ]}}}
        })
        html = self._page_html([
            ("폭염", "경보", "제주도(제주시북부)"),
            ("열대야", "주의보", "제주도(제주시북부)"),
            ("강풍", "주의보", "서울특별시(서울동북권)"),  # 다른 지역, 무관해야 함
        ])
        self._mock_session_get(api, html)

        result = await api._get_warning("L1091320")

        assert "폭염경보" in result
        assert "열대야주의보" in result
        assert "강풍" not in result

    @pytest.mark.asyncio
    async def test_preliminary_warning_level_is_excluded(self):
        """
        [Given] 페이지에 우리 지역의 "예비"(예비특보) 등급 행이 있음
        [When]  _get_warning 호출
        [Then]  예비특보는 정식 발효가 아니므로 병합 대상에서 제외됨
        """
        api = self._api()
        api._fetch = AsyncMock(return_value={
            "response": {"header": {"resultCode": "00"},
                "body": {"items": {"item": []}}}
        })
        html = self._page_html([("호우", "예비", "제주도(제주시북부)")])
        self._mock_session_get(api, html)

        result = await api._get_warning("L1091320")

        assert result == "특보없음"

    @pytest.mark.asyncio
    async def test_other_region_on_page_does_not_leak_in(self):
        """
        [Given] 페이지에 우리 지역과 무관한 다른 지역 특보만 있음
        [When]  _get_warning 호출
        [Then]  "특보없음" (다른 지역 특보가 섞여 들어오면 안 됨)
        """
        api = self._api()
        api._fetch = AsyncMock(return_value={
            "response": {"header": {"resultCode": "00"},
                "body": {"items": {"item": []}}}
        })
        html = self._page_html([("강풍", "주의보", "서울특별시(서울동북권)")])
        self._mock_session_get(api, html)

        result = await api._get_warning("L1091320")

        assert result == "특보없음"

    @pytest.mark.asyncio
    async def test_page_fetch_failure_falls_back_to_api_only(self):
        """
        [Given] 페이지 조회가 실패함(네트워크 오류)
        [When]  _get_warning 호출
        [Then]  크래시 없이 API 결과만으로 정상 반환
        """
        api = self._api()
        api._fetch = AsyncMock(return_value={
            "response": {"header": {"resultCode": "00"},
                "body": {"items": {"item": [
                    {"areaCode": "L1091320", "cancel": "0", "command": "1",
                     "endTime": 0, "tmFc": 202607191000, "warnVar": 12, "warnStress": 0},
                ]}}}
        })

        def raise_error(*a, **kw):
            raise Exception("network error")
        api.session.get = raise_error

        result = await api._get_warning("L1091320")

        assert result == "폭염주의보"

    @pytest.mark.asyncio
    async def test_major_warning_level_from_page_recognized(self):
        """
        [Given] 페이지에 "중대경보" 등급으로 나타난 폭염 특보(API엔 없음)
        [When]  _get_warning 호출
        [Then]  "폭염중대경보"로 정확히 병합됨
        """
        api = self._api()
        api._fetch = AsyncMock(return_value={
            "response": {"header": {"resultCode": "00"},
                "body": {"items": {"item": []}}}
        })
        html = self._page_html([("폭염", "중대경보", "제주도(제주시북부)")])
        self._mock_session_get(api, html)

        result = await api._get_warning("L1091320")

        assert result == "폭염중대경보"


# ══════════════════════════════════════════════════════════════════════════════
# 특보 보완 확인 페이지 실패 시 알림 동작 검증
# ══════════════════════════════════════════════════════════════════════════════

class TestWarningPageFailureNotification:
    """
    weather.go.kr 보완 확인 페이지 조회 실패 시:
    - API(getPwnCd) 결과만으로도 정상적으로 특보 상태값이 출력되는지
    - 반복 실패 시 로그가 도배되지 않고, 최초 1회만 WARNING이 남는지
    - 복구 후 다시 실패하면 재알림되는지
    를 검증한다.
    """

    def _api(self):
        return KMAWeatherAPI(MagicMock(), "key")

    @pytest.mark.asyncio
    async def test_api_only_result_returned_when_page_fetch_raises(self):
        """
        [Given] 페이지 조회에서 예외가 발생함(네트워크 오류)
        [When]  _get_warning 호출
        [Then]  크래시 없이 API 결과(폭염주의보)만으로 정상 반환됨
        """
        api = self._api()
        api._fetch = AsyncMock(return_value={
            "response": {"header": {"resultCode": "00"},
                "body": {"items": {"item": [
                    {"areaCode": "L1091320", "cancel": "0", "command": "1",
                     "endTime": 0, "tmFc": 202607191000, "warnVar": 12, "warnStress": 0},
                ]}}}
        })
        api.session.get = MagicMock(side_effect=Exception("network down"))

        result = await api._get_warning("L1091320")

        assert result == "폭염주의보"

    @pytest.mark.asyncio
    async def test_api_only_result_returned_when_page_returns_non_200(self):
        """
        [Given] 페이지가 200이 아닌 상태코드(예: 503)를 반환함
        [When]  _get_warning 호출
        [Then]  크래시 없이 API 결과만으로 정상 반환됨
        """
        api = self._api()
        api._fetch = AsyncMock(return_value={
            "response": {"header": {"resultCode": "00"},
                "body": {"items": {"item": [
                    {"areaCode": "L1091320", "cancel": "0", "command": "1",
                     "endTime": 0, "tmFc": 202607191000, "warnVar": 13, "warnStress": 0},
                ]}}}
        })

        class ErrorResp:
            status = 503
            async def __aenter__(self): return self
            async def __aexit__(self, *a): pass
        api.session.get = lambda *a, **kw: ErrorResp()

        result = await api._get_warning("L1091320")

        assert result == "열대야주의보"

    @pytest.mark.asyncio
    async def test_first_failure_logs_warning(self, caplog):
        """
        [Given] 페이지 조회 실패가 처음 발생함
        [When]  _fetch_page_warnings_for_area 호출
        [Then]  WARNING 레벨 로그가 남음
        """
        import logging
        api = self._api()
        api.session.get = MagicMock(side_effect=Exception("timeout"))

        with caplog.at_level(logging.WARNING):
            await api._fetch_page_warnings_for_area("제주시북부")

        assert any("weather.go.kr" in r.message for r in caplog.records)
        assert any(r.levelname == "WARNING" for r in caplog.records)

    @pytest.mark.asyncio
    async def test_repeated_failure_does_not_spam_warning(self, caplog):
        """
        [Given] 페이지 조회가 연달아 두 번 실패함
        [When]  _fetch_page_warnings_for_area를 두 번 호출
        [Then]  WARNING은 첫 번째 호출에서만 남고, 두 번째는 안 남음
                (매 폴링마다 반복 실패해도 로그가 도배되지 않도록)
        """
        import logging
        api = self._api()
        api.session.get = MagicMock(side_effect=Exception("timeout"))

        with caplog.at_level(logging.WARNING):
            await api._fetch_page_warnings_for_area("제주시북부")
            caplog.clear()
            await api._fetch_page_warnings_for_area("제주시북부")

        assert not any(r.levelname == "WARNING" for r in caplog.records)

    @pytest.mark.asyncio
    async def test_recovery_resets_notification_so_next_failure_warns_again(self, caplog):
        """
        [Given] 실패 → 성공(복구) → 다시 실패 순서로 진행
        [When]  각 단계마다 _fetch_page_warnings_for_area 호출
        [Then]  복구 이후의 실패에서는 다시 WARNING이 남음
        """
        import logging
        api = self._api()

        api.session.get = MagicMock(side_effect=Exception("timeout"))
        await api._fetch_page_warnings_for_area("제주시북부")  # 1차 실패 → 알림 상태 True

        class OkResp:
            status = 200
            async def text(self): return "<table></table>"
            async def __aenter__(self): return self
            async def __aexit__(self, *a): pass
        api.session.get = lambda *a, **kw: OkResp()
        await api._fetch_page_warnings_for_area("제주시북부")  # 복구 → 알림 상태 초기화

        api.session.get = MagicMock(side_effect=Exception("timeout again"))
        with caplog.at_level(logging.WARNING):
            await api._fetch_page_warnings_for_area("제주시북부")  # 복구 후 재실패

        assert any(r.levelname == "WARNING" for r in caplog.records)


# ══════════════════════════════════════════════════════════════════════════════
# 이벤트 루프 블로킹 호출 방지 (warn_area_names.json 로딩)
# ══════════════════════════════════════════════════════════════════════════════

class TestWarnAreaNamesNonBlockingLoad:
    """
    _load_warn_area_names()의 동기 파일 읽기(Path.read_text)가
    이벤트 루프를 직접 막지 않고 hass.async_add_executor_job으로
    위임되는지 검증한다.

    배경: HA 로그에 "Detected blocking call to read_text ... inside
    the event loop"가 발생했던 실제 버그. area.json/pollen_area_map.json
    등 다른 리소스는 coordinator.py에서 이미 executor_job으로 로드하고
    있었는데, 이 파일만 async 함수 안에서 동기 호출로 남아있었다.
    """

    @pytest.mark.asyncio
    async def test_loading_delegates_to_executor_job_when_hass_present(self):
        """
        [Given] hass 객체가 있는 정상적인 런타임 환경
        [When]  _get_warn_area_display_name 호출(최초 1회, 캐시 비어있음)
        [Then]  파일 로딩이 hass.async_add_executor_job을 통해 실행됨
                (이벤트 루프를 직접 막는 동기 호출이 아님)
        """
        hass = MagicMock()
        call_count = {"n": 0}

        async def mock_executor(func, *args):
            call_count["n"] += 1
            return func(*args)
        hass.async_add_executor_job = mock_executor

        api = KMAWeatherAPI(MagicMock(), "key", hass=hass)
        # 모듈 전역 캐시를 비워서 실제로 로드가 일어나도록 강제
        import custom_components.kma_weather.api_kma as api_module
        api_module._WARN_AREA_NAMES = {}

        result = await api._get_warn_area_display_name("L1091320")

        assert call_count["n"] == 1, "파일 로딩이 executor_job으로 위임되지 않음"
        assert result == "제주시북부"

    @pytest.mark.asyncio
    async def test_falls_back_to_sync_load_when_hass_is_none(self):
        """
        [Given] hass가 없는 환경(단위테스트 등)
        [When]  _get_warn_area_display_name 호출
        [Then]  크래시 없이 동기 폴백으로 정상 동작함
        """
        import custom_components.kma_weather.api_kma as api_module
        api_module._WARN_AREA_NAMES = {}

        api = KMAWeatherAPI(MagicMock(), "key", hass=None)
        result = await api._get_warn_area_display_name("L1091320")

        assert result == "제주시북부"

    @pytest.mark.asyncio
    async def test_does_not_reload_once_cached(self):
        """
        [Given] 이미 한 번 로드되어 전역 캐시가 채워진 상태
        [When]  _get_warn_area_display_name을 다시 호출
        [Then]  executor_job이 다시 호출되지 않음(캐시 재사용)
        """
        hass = MagicMock()
        call_count = {"n": 0}

        async def mock_executor(func, *args):
            call_count["n"] += 1
            return func(*args)
        hass.async_add_executor_job = mock_executor

        api = KMAWeatherAPI(MagicMock(), "key", hass=hass)
        import custom_components.kma_weather.api_kma as api_module
        api_module._WARN_AREA_NAMES = {}

        await api._get_warn_area_display_name("L1091320")
        await api._get_warn_area_display_name("L1130120")

        assert call_count["n"] == 1, "캐시가 있는데도 다시 로드함"
