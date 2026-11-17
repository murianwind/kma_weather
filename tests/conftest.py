import pytest
from unittest.mock import patch
from datetime import timedelta
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

# fast_sleep 등이 patch 대상 경로(custom_components.kma_weather.*)를 해석하려면
# 모듈이 먼저 import되어 있어야 한다. 테스트 파일 하나만 단독 실행해도 동작하도록 미리 import.
import custom_components.kma_weather.api_kma  # noqa: F401
import custom_components.kma_weather.coordinator  # noqa: F401

# 1. DNS 스레드 패치
@pytest.fixture(autouse=True)
def allow_pycares_thread(monkeypatch):
    import threading
    original_enumerate = threading.enumerate
    def patched_enumerate():
        return [t for t in original_enumerate() if "_run_safe_shutdown_loop" not in t.name]
    monkeypatch.setattr(threading, "enumerate", patched_enumerate)

@pytest.fixture(autouse=True)
def fast_sleep():
    """부하 분산을 위한 asyncio.sleep 대기 시간을 테스트 환경에서 무력화합니다."""
    with patch("custom_components.kma_weather.coordinator.asyncio.sleep", return_value=None), \
         patch("custom_components.kma_weather.api_kma.asyncio.sleep", return_value=None), \
         patch("custom_components.kma_weather.asyncio.sleep", return_value=None):
        yield

@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield

@pytest.fixture(autouse=True)
def no_real_airkorea_station_discovery(monkeypatch):
    """_discover_airkorea_station_code는 실제 airkorea.or.kr에 라이브 네트워크
    요청을 보낸다 — 유닛 테스트가 실제 사이트 가용성에 의존하지 않도록
    기본값을 None으로 막는다. 이 흐름 자체를 검증하는 테스트는 각자
    명시적으로 다시 mock(또는 monkeypatch)해서 이 기본값을 덮어쓴다."""
    from unittest.mock import AsyncMock
    from custom_components.kma_weather.api_kma import KMAWeatherAPI
    monkeypatch.setattr(KMAWeatherAPI, "_discover_airkorea_station_code", AsyncMock(return_value=None))

# 2. 10일치 예보 데이터 생성 헬퍼
def generate_forecast_data(start_date):
    twice_daily = []
    for i in range(10):
        day = start_date + timedelta(days=i)
        d_str = day.strftime("%Y-%m-%dT00:00:00Z")
        n_str = day.strftime("%Y-%m-%dT12:00:00Z")
        twice_daily.append({
            "datetime": d_str,
            "is_daytime": True,
            "condition": "sunny",
            "native_temperature": 25 - i,
            "precipitation_probability": 10
        })
        twice_daily.append({
            "datetime": n_str,
            "is_daytime": False,
            "condition": "clear-night",
            "native_temperature": 18 - i,
            "precipitation_probability": 20
        })
    return twice_daily

now = dt_util.now()
forecast_list = generate_forecast_data(now)

# ── Mock 시나리오 ────────────────────────────────────────────────────────────
MOCK_SCENARIOS = {
    "full_test": {
        "weather": {
            "TMP": 22,
            "REH": 45,
            "WSD": 2.1,
            "VEC_KOR": "남동",
            "POP": 10,
            "PTY": 0,
            "SKY": 1,
            "current_condition_kor": "맑음",
            "current_condition": "sunny",
            "TMX_today": 25,
            "TMN_today": 15,
            "TMX_tomorrow": 26,
            "TMN_tomorrow": 16,
            "wf_am_today": "맑음",
            "wf_pm_today": "구름많음",
            "wf_am_tomorrow": "흐림",
            "wf_pm_tomorrow": "맑음",
            "apparent_temp": 23.4,
            "rain_start_time": "강수없음",
            "address": "경기도 화성시",
            "현재 위치": "경기도 화성시",
            "forecast_twice_daily": forecast_list,
        },
        "air": {
            "pm10Value": 35,
            "pm10Grade": "보통",
            "pm25Value": 15,
            "pm25Grade": "좋음",
            "station": "화성"
        },
        # ── 꽃가루 데이터 추가 ──────────────────────────────────────────────
        # pollen 센서는 pollen API 승인 시에만 등록(SENSOR_API_GROUPS["pollen"]).
        # full_test 시나리오는 pollen API가 승인된 상태이므로 데이터를 포함한다.
        "pollen": {
            "oak": "좋음",
            "pine": "좋음",
            "grass": "좋음",
            "worst": "좋음",
        },
    },
    "jeju_missing": {
        "weather": {"address": "제주시", "현재 위치": "제주시", "forecast_twice_daily": []},
        "air": {}
    }
}

# "full_test" 시나리오에서 승인된 것으로 가정하는 API 키 목록.
# fetch_data를 mock으로 대체하면 실제 _mark_approved()가 호출되지 않으므로
# coordinator 초기화 직후 _approved_apis를 직접 주입해야 한다.
# 그렇지 않으면 sensor.py의 _eligible_sensor_types()가 short/air/warning 등
# API 의존 센서를 등록 대상에서 제외해 테스트가 실패한다.
_FULL_TEST_APPROVED: frozenset[str] = frozenset(
    {"short", "mid", "air", "warning", "pollen"}
)


@pytest.fixture
def mock_config_entry():
    return MockConfigEntry(
        domain="kma_weather",
        data={"api_key": "test_key", "location_mode": "zone", "prefix": "test"},
        entry_id="mock_id_123"
    )


@pytest.fixture
def kma_api_mock_factory():
    """
    fetch_data를 패치하면서 "full_test" 시나리오일 때
    coordinator.__init__ 완료 직후 api._approved_apis를 자동 주입한다.

    [문제]
    sensor.py::async_setup_entry 에서 _eligible_sensor_types(coordinator) 를
    호출할 때 coordinator.api._approved_apis 를 참조한다.
    fetch_data 가 mock 으로 대체되면 실제 API 호출이 없어
    _mark_approved() 가 한 번도 호출되지 않는다.
    결과적으로 _approved_apis 가 빈 set 으로 남아
    short / air / warning 관련 센서가 전혀 등록되지 않아 테스트가 실패한다.

    [해결]
    KMAWeatherUpdateCoordinator.__init__ 를 감싸서
    실제 __init__ 실행 후 api._approved_apis 를 직접 주입한다.
    patch.object 를 사용하므로 patch.stopall() 과 별도로 정리한다.
    """
    _obj_patchers: list = []

    def _create_mock(scenario_name: str):
        # ── fetch_data 패치 ────────────────────────────────────────────────
        mock_fetch = patch(
            "custom_components.kma_weather.api_kma.KMAWeatherAPI.fetch_data"
        ).start()

        if scenario_name == "error":
            mock_fetch.side_effect = Exception("API Error")
        else:
            mock_fetch.return_value = MOCK_SCENARIOS.get(scenario_name)

        # ── "full_test": coordinator 생성 시 _approved_apis 주입 ───────────
        if scenario_name == "full_test":
            from custom_components.kma_weather.coordinator import (
                KMAWeatherUpdateCoordinator,
            )

            _real_init = KMAWeatherUpdateCoordinator.__init__

            def _patched_init(self_coord, hass, entry):
                # 원본 __init__ 그대로 실행
                _real_init(self_coord, hass, entry)
                # fetch_data mock으로 _mark_approved가 호출되지 않으므로
                # 테스트 목적상 모든 API가 승인된 상태로 초기화한다.
                self_coord.api._approved_apis = set(_FULL_TEST_APPROVED)

            patcher = patch.object(
                KMAWeatherUpdateCoordinator, "__init__", _patched_init
            )
            patcher.start()
            _obj_patchers.append(patcher)

        return mock_fetch

    yield _create_mock

    # 정리: object 패치는 patch.stopall() 대상이 아니므로 별도 처리
    for p in _obj_patchers:
        try:
            p.stop()
        except RuntimeError:
            pass
    patch.stopall()
