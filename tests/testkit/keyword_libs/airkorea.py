"""에어코리아 대기질 키워드: 측정소 조회 → 대기질 조회 → 페이지 보완 흐름의 성공/실패 조합을 조립한다."""
import logging
from unittest.mock import AsyncMock, MagicMock

from testkit.aio import run
from testkit.keywords import keyword
from custom_components.kma_weather.api_kma import KMAWeatherAPI

LIB = "airkorea (에어코리아 대기질)"
NEARBY, AIR = "getNearbyMsrstnList", "getMsrstnAcctoRltmMesureDnsty"
STATION_OK = {"response": {"header": {"resultCode": "00"}, "body": {"items": [{"stationName": "화랑로"}]}}}
AIR_OK = {"response": {"header": {"resultCode": "00"}, "body": {"items": [
    {"pm10Value": "23", "pm25Value": "16", "o3Value": "0.008"}]}}}
AIR_EMPTY = {"response": {"header": {"resultCode": "00"}, "body": {"items": []}}}
UNSUBSCRIBED = {"response": {"header": {"resultCode": "30"}}}
PAGE_OK = {"pm10Value": "30", "pm25Value": "12", "o3Value": "0.020"}
# 키워드 인자 '결과' 의 이름 → 가짜 API 응답
STATION_RESPONSES = {"정상": STATION_OK, "실패": None, "미신청": UNSUBSCRIBED}
AIR_RESPONSES = {"정상": AIR_OK, "비어있음": AIR_EMPTY, "실패": None}


@keyword("에어코리아를_준비한다", library=LIB)
def prepare(world):
    """가짜 에어코리아 API 를 준비한다. 처음엔 모든 호출이 실패하고 측정소코드 확보·페이지 보완도 못 하는 상태."""
    api = KMAWeatherAPI(MagicMock(), "key")
    world.routes, world.fetch_calls = {}, []

    async def fake_fetch(url, params=None, **kwargs):
        world.fetch_calls.append((url, kwargs))
        for fragment, value in world.routes.items():
            if fragment in url:
                return value
        return None

    api._fetch = fake_fetch
    api._get_address = AsyncMock(return_value="서울특별시 노원구")
    api._discover_airkorea_station_code = AsyncMock(return_value=None)
    api._fetch_page_air_quality = AsyncMock(return_value={})
    world.api = api


@keyword("측정소_조회가_응답한다", library=LIB)
def station_lookup(world, 결과):
    """측정소 조회 API 의 응답을 정한다: 정상 / 실패 / 미신청."""
    world.routes[NEARBY] = STATION_RESPONSES[결과]


@keyword("대기질_API가_응답한다", library=LIB)
def air_api(world, 결과):
    """대기질 조회 API 의 응답을 정한다: 정상 / 비어있음 / 실패."""
    world.routes[AIR] = AIR_RESPONSES[결과]


@keyword("측정소코드_확보가_성공한다", library=LIB)
def discover_code(world, 코드):
    """에어코리아 페이지에서 측정소코드를 확보하는 데 성공해 지정한 코드를 돌려준다."""
    world.api._discover_airkorea_station_code = AsyncMock(return_value=코드)


@keyword("페이지_보완이_성공한다", library=LIB)
def page_fallback_ok(world):
    """에어코리아 페이지 보완 조회가 성공해 미세먼지 30, 초미세먼지 12, 오존 0.020 을 돌려준다."""
    world.api._fetch_page_air_quality = AsyncMock(return_value=PAGE_OK)


@keyword("측정소가_캐시되어_있다", library=LIB)
def cached_station(world, 이름, 코드, 위도, 경도):
    """이전 주기에 확보한 측정소 이름·코드와 그때의 위치를 캐시에 넣는다."""
    api = world.api
    api._cached_station, api._cached_station_code = 이름, 코드
    api._cached_station_lat, api._cached_station_lon = 위도, 경도


@keyword("주소_조회_결과가_비어_있다", library=LIB)
def empty_address(world):
    """역지오코딩 결과에 시/구/동 정보가 없어 주소가 빈 문자열이다."""
    world.api._get_address = AsyncMock(return_value="")


@keyword("대기질을_조회한다", library=LIB)
def query_air_quality(world, 위도, 경도):
    """지정한 위치의 대기질(_get_air_quality)을 조회하고 결과를 저장한다."""
    world.result = run(world.api._get_air_quality(위도, 경도))


@keyword("결과를_확인한다", library=LIB)
def assert_result(world, 값):
    """조회 결과가 기대 딕셔너리와 정확히 같은지 확인한다."""
    assert world.result == 값


@keyword("결과_값을_확인한다", library=LIB)
def assert_result_value(world, 키, 값):
    """조회 결과의 특정 키 값이 기대와 같은지 확인한다."""
    assert world.result[키] == 값


@keyword("결과에_키가_없다", library=LIB)
def assert_no_key(world, 키):
    """조회 결과에 특정 키가 없는지 확인한다."""
    assert 키 not in world.result


@keyword("경고_횟수를_확인한다", library=LIB)
def assert_warning_count(world, 횟수):
    """WARNING 이상 로그가 정확히 기대 횟수만큼 남았는지 확인한다."""
    assert len([r for r in world.caplog.records if r.levelno >= logging.WARNING]) == 횟수


@keyword("에어코리아_호출은_긴_타임아웃과_DEBUG_로그를_쓴다", library=LIB)
def assert_airkorea_call_options(world, 호출수):
    """에어코리아(B552584) 호출이 기대 횟수이고 모두 timeout=30, fail_log_level=DEBUG 인지 확인한다."""
    calls = [kwargs for url, kwargs in world.fetch_calls if "B552584" in url]
    assert len(calls) == 호출수
    assert all(c.get("timeout") == 30 and c.get("fail_log_level") == logging.DEBUG for c in calls)


@keyword("에어코리아_API_호출_횟수를_확인한다", library=LIB)
def assert_api_call_count(world, 종류, 횟수):
    """측정소 조회 / 대기질 조회 API 중 지정한 종류가 기대 횟수만큼 호출됐는지 확인한다."""
    fragment = {"측정소": NEARBY, "대기질": AIR}[종류]
    assert len([1 for url, _ in world.fetch_calls if fragment in url]) == 횟수


@keyword("페이지_보완_호출을_확인한다", library=LIB)
def assert_page_fallback_calls(world, 횟수, 코드=None):
    """페이지 보완 조회가 기대 횟수만큼 불렸는지(코드가 있으면 그 코드로) 확인한다."""
    mock = world.api._fetch_page_air_quality
    assert mock.await_count == 횟수
    if 코드 is not None:
        mock.assert_awaited_once_with(코드)


@keyword("측정소코드_확보_호출을_확인한다", library=LIB)
def assert_discover_calls(world, 횟수, 인자=None):
    """측정소코드 확보가 기대 횟수만큼 불렸는지(인자가 있으면 그 인자로) 확인한다."""
    mock = world.api._discover_airkorea_station_code
    assert mock.await_count == 횟수
    if 인자 is not None:
        mock.assert_awaited_once_with(*인자)


@keyword("캐시된_측정소를_확인한다", library=LIB)
def assert_cached_station(world, 이름, 코드, 위도=None, 경도=None):
    """캐시된 측정소 이름·코드(와 위치)가 기대와 같은지 확인한다. 이름이 null 이면 이름 캐시가 비어 있어야 한다."""
    api = world.api
    assert (api._cached_station, api._cached_station_code) == (이름, 코드)
    if 위도 is not None:
        assert (api._cached_station_lat, api._cached_station_lon) == (위도, 경도)
