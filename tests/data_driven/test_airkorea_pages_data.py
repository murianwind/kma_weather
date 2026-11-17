"""데이터 드리븐: 에어코리아 웹 페이지 보완 — 시/도 코드, 측정소코드 확보, 실시간 차트 조회.

  airkorea_district.csv      시/도명 → myDistrict 코드
  airkorea_station_code.csv  realSearch 응답 → 가장 가까운 측정소코드
  airkorea_page_chart.csv    key 발급 → 차트 조회 → PM10/PM2.5/오존 (1회 재시도)
"""
import aiohttp
import pytest

from custom_components.kma_weather.api_kma import KMAWeatherAPI, _airkorea_district_code
from testkit.aio import run
from testkit.airkorea_pages import PageResponse, PageSession
from testkit.factories import make_api
from testkit.tables import read_csv, table_params

REAL_DISCOVER = KMAWeatherAPI._discover_airkorea_station_code  # conftest 가 기본으로 None 을 돌려주게 막아 둔 원본
NONE_TOKENS = {"(None)": None, "(빈칸)": "", "(없음)": None}
KEY_PAGE = "var key = 'abc-key';"


def token(value):
    return NONE_TOKENS.get(value, value)


def use_session(monkeypatch, session):
    monkeypatch.setattr(aiohttp, "ClientSession", lambda: session)


# ── 시/도명 → myDistrict ─────────────────────────────────────────────────────
@pytest.mark.parametrize("row", table_params(read_csv("airkorea_district.csv"), lambda r: r["분류"]))
def test_airkorea_district_code(row):
    """
    [Given] 주소의 시/도명 (신·구 명칭, 약칭 포함)
    [When]  _airkorea_district_code
    [Then]  에어코리아 myDistrict 코드, 모르는 이름이면 None
    """
    assert _airkorea_district_code(token(row["시도명"])) == token(row["기대"])


# ── 측정소코드 확보 ──────────────────────────────────────────────────────────
def station_outcome(token_text):
    if token_text.startswith("목록:"):
        radios = "".join(
            f'<input type="radio" value="{item.split("_")[0]}_{item.split("_")[1]}_주소_206564_457267_stationCode{i}">'
            for i, item in enumerate(token_text.removeprefix("목록:").split(";")))
        return PageResponse(text=f"var key = 'k';{radios}")
    if token_text == "빈HTML":
        return PageResponse(text="<html>측정소 없음</html>")
    if token_text == "HTTP500":
        return PageResponse(status=500)
    return RuntimeError("network down")


@pytest.mark.parametrize("row", table_params(read_csv("airkorea_station_code.csv"), lambda r: r["분류"]))
def test_discover_station_code(row, monkeypatch):
    """
    [Given] realSearch 가 측정소 목록 / 빈 화면 / HTTP 오류 / 예외를 돌려줌
    [When]  _discover_airkorea_station_code
    [Then]  첫 번째(가장 가까운) 측정소코드를 돌려주고, 요청에는 시/도에 맞는 myDistrict 가 실린다
    """
    session = PageSession([station_outcome(row["응답"])])
    use_session(monkeypatch, session)
    api = make_api()

    code = run(REAL_DISCOVER(api, 37.608, 127.094, token(row["시도명"])))

    assert code == token(row["기대_코드"])
    (url, data), = session.posts
    assert url.endswith("/realSearch")
    assert data["myDistrict"] == row["기대_myDistrict"]


# ── 실시간 차트 보완 ─────────────────────────────────────────────────────────
def chart_entries(text):
    def value(part):
        return None if part == "없음" else part
    return [dict(zip(("VALUE_10007", "VALUE_10008", "VALUE_10003"), map(value, item.split("/"))))
            for item in text.split(";")]


def attempt_outcomes(token_text):
    """한 번의 시도가 받는 post 결과 목록 (key 발급, [차트 조회])."""
    if token_text == "(없음)":
        return []
    if token_text == "key500":
        return [PageResponse(status=500)]
    if token_text == "key없음":
        return [PageResponse(text="<html/>")]
    if token_text == "예외":
        return [RuntimeError("network down")]
    key = PageResponse(text=KEY_PAGE)
    if token_text == "차트500":
        return [key, PageResponse(status=500)]
    if token_text == "빈차트":
        return [key, PageResponse(payload={"charts": []})]
    if token_text == "키없는차트":
        return [key, PageResponse(payload={})]
    return [key, PageResponse(payload={"charts": chart_entries(token_text.removeprefix("정상:"))})]


@pytest.mark.parametrize("row", table_params(read_csv("airkorea_page_chart.csv"), lambda r: r["분류"]))
def test_page_air_quality(row, monkeypatch):
    """
    [Given] 측정소코드와, 시도마다 정해진 realSearch/getRealChart 결과
    [When]  _fetch_page_air_quality
    [Then]  가장 최근의 유효한 PM10/PM2.5/오존 값, 실패하면 한 번 재시도 후 빈 값, POST 횟수가 표와 같다
    """
    session = PageSession(attempt_outcomes(row["1차"]) + attempt_outcomes(row["2차"]))
    use_session(monkeypatch, session)
    api = make_api()

    result = run(api._fetch_page_air_quality(token(row["측정소코드"])))

    keys = {"pm10": "pm10Value", "pm25": "pm25Value", "o3": "o3Value"}
    expected = {} if row["기대"] == "(빈 dict)" else {
        keys[name]: value for name, value in (pair.split("=") for pair in row["기대"].split(";"))}
    assert result == expected
    assert len(session.posts) == int(row["기대_post"])
