"""
test_airkorea_resilience.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
에어코리아 호출 타임아웃/연결 오류 내성 검증 (v2.1.9)

배경:
  - 에어코리아(B552584)가 15초 안에 응답하지 않으면 TimeoutError가 나는데,
    기존 _fetch는 에러 메시지 문자열에 "500" 등이 있는지로 재시도를 판단해서
    메시지가 빈 TimeoutError는 재시도 없이 바로 ERROR를 남겼다.
  - 이동(2km 이상) 후 측정소 이름 조회가 실패하면 함수가 바로 끝나서,
    이름과 무관하게 동작하는 페이지 보완(측정소코드 기준)까지 가지 못했다.

검증 대상:
  - _fetch: 예외 타입 기준 재시도, fail_log_level, 예외 타입 로깅
  - _get_air_quality: 이름 조회 실패 시에도 페이지 보완, 경고는 전부 실패 시 1회
  - 이동 감지: 측정소코드만 캐시된 상태에서도 2km 이상 이동하면 무효화
"""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.kma_weather.api_kma import KMAWeatherAPI

NEARBY_URL_FRAGMENT = "getNearbyMsrstnList"
AIR_URL_FRAGMENT = "getMsrstnAcctoRltmMesureDnsty"

AIR_OK = {"response": {"header": {"resultCode": "00"}, "body": {"items": [
    {"pm10Value": "23", "pm25Value": "16", "o3Value": "0.008"},
]}}}
AIR_EMPTY = {"response": {"header": {"resultCode": "00"}, "body": {"items": []}}}
STATION_OK = {"response": {"header": {"resultCode": "00"}, "body": {"items": [
    {"stationName": "화랑로"},
]}}}
PAGE_OK = {"pm10Value": "30", "pm25Value": "12", "o3Value": "0.020"}


# ─────────────────────────────────────────────────────────────────────────────
# 공통 헬퍼
# ─────────────────────────────────────────────────────────────────────────────

class _OkResp:
    status = 200

    def __init__(self, text="{}"):
        self._text = text

    def raise_for_status(self):
        pass

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _session_with_sequence(outcomes):
    """
    outcomes: 호출 순서대로 사용할 결과 목록.
      - Exception 인스턴스 → session.get 진입 시 raise
      - str               → 정상 응답(200) 본문
    """
    calls = {"n": 0}
    queue = list(outcomes)

    def _get(*a, **kw):
        calls["n"] += 1
        item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return _OkResp(item)

    session = MagicMock()
    session.get = _get
    return session, calls


def _warning_or_above(caplog):
    return [r for r in caplog.records if r.levelno >= logging.WARNING]


def _api_with_fetch(routes, discover_code=None, page_result=None):
    """
    routes: {url 조각: 반환값} — _fetch를 대체한다. 호출 인자는 api.fetch_calls에 기록.
    """
    api = KMAWeatherAPI(MagicMock(), "key")
    api.fetch_calls = []

    async def _fake_fetch(url, params=None, **kwargs):
        api.fetch_calls.append((url, kwargs))
        for fragment, value in routes.items():
            if fragment in url:
                return value
        return None

    api._fetch = _fake_fetch
    api._get_address = AsyncMock(return_value="서울특별시 노원구")
    api._discover_airkorea_station_code = AsyncMock(return_value=discover_code)
    api._fetch_page_air_quality = AsyncMock(return_value=page_result or {})
    return api


# ─────────────────────────────────────────────────────────────────────────────
# 1. _fetch 재시도 판단 (예외 타입 기준)
# ─────────────────────────────────────────────────────────────────────────────

class TestFetchRetryOnTransientErrors:

    @pytest.mark.asyncio
    async def test_timeout_once_then_success_is_retried_silently(self, caplog):
        """
        [Given] 첫 요청은 TimeoutError, 두 번째 요청은 정상 응답
        [When]  _fetch 호출
        [Then]  재시도해서 정상 데이터를 반환하고, WARNING 이상 로그는 없다
        """
        session, calls = _session_with_sequence([asyncio.TimeoutError(), '{"ok": 1}'])
        api = KMAWeatherAPI(session, "key")

        with caplog.at_level(logging.DEBUG):
            result = await api._fetch("http://example.com", {})

        assert result == {"ok": 1}
        assert calls["n"] == 2
        assert _warning_or_above(caplog) == []

    @pytest.mark.asyncio
    async def test_connection_error_is_retried(self):
        """
        [Given] 첫 요청에서 서버 연결 끊김(ServerDisconnectedError)
        [When]  _fetch 호출
        [Then]  재시도해서 정상 데이터를 반환한다
        """
        session, calls = _session_with_sequence(
            [aiohttp.ServerDisconnectedError(), '{"ok": 2}']
        )
        api = KMAWeatherAPI(session, "key")

        result = await api._fetch("http://example.com", {})

        assert result == {"ok": 2}
        assert calls["n"] == 2

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status, expected_calls", [(500, 2), (503, 2), (400, 1)])
    async def test_client_response_error_retry_depends_on_status(self, status, expected_calls):
        """
        [Given] raise_for_status 계열 예외(ClientResponseError)
        [When]  _fetch 호출
        [Then]  5xx/429면 재시도하고, 그 외(400 등)는 재시도하지 않는다
        """
        err = aiohttp.ClientResponseError(MagicMock(), (), status=status)
        session, calls = _session_with_sequence([err, err])
        api = KMAWeatherAPI(session, "key")

        result = await api._fetch("http://example.com", {})

        assert result is None
        assert calls["n"] == expected_calls


# ─────────────────────────────────────────────────────────────────────────────
# 2. _fetch 최종 실패 로그
# ─────────────────────────────────────────────────────────────────────────────

class TestFetchFinalFailureLog:

    @pytest.mark.asyncio
    async def test_default_final_failure_logs_error_with_exception_type(self, caplog):
        """
        [Given] 두 번 모두 TimeoutError (기본 로그 레벨)
        [When]  _fetch 호출
        [Then]  None 반환, ERROR 로그 1건, 메시지에 예외 타입과 시도 횟수가 들어간다
        """
        session, calls = _session_with_sequence([asyncio.TimeoutError(), asyncio.TimeoutError()])
        api = KMAWeatherAPI(session, "key")

        with caplog.at_level(logging.DEBUG):
            result = await api._fetch("http://example.com", {})

        errors = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert result is None
        assert calls["n"] == 2
        assert len(errors) == 1
        assert "API 호출 실패" in errors[0].getMessage()
        assert "TimeoutError" in errors[0].getMessage()
        assert "2회 시도" in errors[0].getMessage()

    @pytest.mark.asyncio
    async def test_fail_log_level_debug_suppresses_error(self, caplog):
        """
        [Given] 두 번 모두 TimeoutError, 호출자가 fail_log_level=DEBUG 지정
        [When]  _fetch 호출
        [Then]  None 반환, WARNING 이상 로그는 없다 (DEBUG로만 남음)
        """
        session, _ = _session_with_sequence([asyncio.TimeoutError(), asyncio.TimeoutError()])
        api = KMAWeatherAPI(session, "key")

        with caplog.at_level(logging.DEBUG):
            result = await api._fetch("http://example.com", {}, fail_log_level=logging.DEBUG)

        assert result is None
        assert _warning_or_above(caplog) == []
        assert any("TimeoutError" in r.getMessage() for r in caplog.records)

    @pytest.mark.asyncio
    async def test_non_retryable_failure_reports_single_attempt(self, caplog):
        """
        [Given] 재시도 대상이 아닌 예외(ValueError)
        [When]  _fetch 호출
        [Then]  1회만 시도하고 로그에 '1회 시도'와 예외 타입이 남는다
        """
        session, calls = _session_with_sequence([ValueError("boom")])
        api = KMAWeatherAPI(session, "key")

        with caplog.at_level(logging.ERROR):
            result = await api._fetch("http://example.com", {})

        assert result is None
        assert calls["n"] == 1
        assert "ValueError" in caplog.text
        assert "1회 시도" in caplog.text


# ─────────────────────────────────────────────────────────────────────────────
# 3. _get_air_quality 흐름
# ─────────────────────────────────────────────────────────────────────────────

class TestAirQualityResilience:

    @pytest.mark.asyncio
    async def test_airkorea_calls_use_long_timeout_and_debug_failure_level(self):
        """
        [Given] 측정소 캐시가 없는 상태
        [When]  _get_air_quality 호출
        [Then]  측정소 조회와 대기질 조회 모두 timeout=30, fail_log_level=DEBUG로 호출된다
        """
        api = _api_with_fetch({NEARBY_URL_FRAGMENT: STATION_OK, AIR_URL_FRAGMENT: AIR_OK})

        await api._get_air_quality(37.6, 127.09)

        airkorea_calls = [kw for url, kw in api.fetch_calls if "B552584" in url]
        assert len(airkorea_calls) == 2
        for kw in airkorea_calls:
            assert kw.get("timeout") == 30
            assert kw.get("fail_log_level") == logging.DEBUG

    @pytest.mark.asyncio
    async def test_air_api_failure_filled_by_page_without_warning(self, caplog):
        """
        [Given] 측정소는 캐시되어 있고 대기질 API가 최종 실패(None), 페이지 보완은 성공
        [When]  _get_air_quality 호출
        [Then]  페이지 값으로 채워지고 WARNING 이상 로그는 없다
        """
        api = _api_with_fetch({AIR_URL_FRAGMENT: None}, page_result=PAGE_OK)
        api._cached_station, api._cached_station_code = "화랑로", "111312"
        api._cached_station_lat, api._cached_station_lon = 37.6, 127.09

        with caplog.at_level(logging.DEBUG):
            result = await api._get_air_quality(37.6, 127.09)

        assert result["pm10Value"] == "30"
        assert result["station"] == "화랑로"
        assert _warning_or_above(caplog) == []

    @pytest.mark.asyncio
    async def test_station_lookup_failure_still_uses_page_fallback(self, caplog):
        """
        [Given] 2km 이상 이동해서 캐시가 무효화되고, 측정소 이름 조회가 실패(None),
                측정소코드 확보(realSearch)와 페이지 보완은 성공
        [When]  _get_air_quality 호출
        [Then]  페이지 값으로 채워지고, 대기질 API는 호출되지 않으며, 경고도 없다
        """
        api = _api_with_fetch({NEARBY_URL_FRAGMENT: None}, discover_code="222333", page_result=PAGE_OK)
        api._cached_station, api._cached_station_code = "서석동", "999999"
        api._cached_station_lat, api._cached_station_lon = 35.145, 126.918

        with caplog.at_level(logging.DEBUG):
            result = await api._get_air_quality(37.6, 127.09)

        assert result["pm10Value"] == "30"
        assert result["pm25Value"] == "12"
        assert "station" not in result
        assert api._cached_station is None
        assert api._cached_station_code == "222333"
        api._fetch_page_air_quality.assert_awaited_once_with("222333")
        assert not any(AIR_URL_FRAGMENT in url for url, _ in api.fetch_calls)
        assert _warning_or_above(caplog) == []

    @pytest.mark.asyncio
    async def test_everything_failing_logs_single_warning(self, caplog):
        """
        [Given] 측정소 이름 조회, 측정소코드 확보 모두 실패
        [When]  _get_air_quality 호출
        [Then]  빈 dict 반환, WARNING 정확히 1회, ERROR 없음
        """
        api = _api_with_fetch({NEARBY_URL_FRAGMENT: None}, discover_code=None)

        with caplog.at_level(logging.DEBUG):
            result = await api._get_air_quality(37.6, 127.09)

        warnings = _warning_or_above(caplog)
        assert result == {}
        assert len(warnings) == 1
        assert warnings[0].levelno == logging.WARNING

    @pytest.mark.asyncio
    async def test_station_known_but_api_and_page_fail_logs_single_warning(self, caplog):
        """
        [Given] 측정소 이름은 조회되지만 대기질 API와 페이지 보완 모두 실패
        [When]  _get_air_quality 호출
        [Then]  {"station": 이름} 반환(기존 동작 유지), WARNING 정확히 1회
        """
        api = _api_with_fetch({NEARBY_URL_FRAGMENT: STATION_OK, AIR_URL_FRAGMENT: AIR_EMPTY})

        with caplog.at_level(logging.DEBUG):
            result = await api._get_air_quality(37.6, 127.09)

        assert result == {"station": "화랑로"}
        assert len(_warning_or_above(caplog)) == 1

    @pytest.mark.asyncio
    async def test_code_only_cache_is_invalidated_after_move(self):
        """
        [Given] 이전 주기에 이름 조회는 실패하고 측정소코드만 캐시된 상태
        [When]  2km 이상 떨어진 곳에서 _get_air_quality 호출
        [Then]  오래된 코드를 버리고 새 위치 기준으로 코드를 다시 확보한다
        """
        api = _api_with_fetch({NEARBY_URL_FRAGMENT: None}, discover_code="NEW001", page_result=PAGE_OK)
        api._cached_station = None
        api._cached_station_code = "OLD001"
        api._cached_station_lat, api._cached_station_lon = 35.145, 126.918

        await api._get_air_quality(37.6, 127.09)

        api._discover_airkorea_station_code.assert_awaited_once()
        assert api._cached_station_code == "NEW001"
        assert (api._cached_station_lat, api._cached_station_lon) == (37.6, 127.09)

    @pytest.mark.asyncio
    async def test_unsubscribed_station_api_returns_empty_without_fallback(self):
        """
        [Given] 측정소 조회 API가 미신청(resultCode=30) 응답
        [When]  _get_air_quality 호출
        [Then]  기존처럼 빈 dict를 반환하고 페이지 보완은 시도하지 않는다
        """
        unsub = {"response": {"header": {"resultCode": "30"}}}
        api = _api_with_fetch({NEARBY_URL_FRAGMENT: unsub}, discover_code="222333", page_result=PAGE_OK)

        result = await api._get_air_quality(37.6, 127.09)

        assert result == {}
        api._fetch_page_air_quality.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_empty_address_does_not_break_station_code_discovery(self):
        """
        [Given] 역지오코딩(Nominatim) 결과에 시/구/동 정보가 없어 주소가 빈 문자열
        [When]  _get_air_quality 호출
        [Then]  예외 없이 시/도명 ""으로 측정소코드 확보를 시도하고 대기질을 반환한다
        """
        api = _api_with_fetch({NEARBY_URL_FRAGMENT: STATION_OK, AIR_URL_FRAGMENT: AIR_OK},
                              discover_code="111312")
        api._get_address = AsyncMock(return_value="")

        result = await api._get_air_quality(37.6, 127.09)

        assert result["pm10Value"] == "23"
        api._discover_airkorea_station_code.assert_awaited_once_with(37.6, 127.09, "")
