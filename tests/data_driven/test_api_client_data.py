"""데이터 드리븐: KMAWeatherAPI 생성자와 역지오코딩 — 표(tests/data_driven/cases/*.csv)만 고치면 케이스가 늘어난다.

  api_key_decode.csv   생성자가 API 키를 디코딩하는 규칙
  user_agent.csv       Nominatim User-Agent 를 정하는 규칙 (속성 + 실제 요청 헤더)
  address_lookup.csv   _get_address 가 응답을 표시 주소로 바꾸고 실패 시 좌표로 대체하는 규칙
"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.kma_weather.api_kma import KMAWeatherAPI
from testkit.aio import run
from testkit.factories import scripted_session
from testkit.tables import read_csv, table_params

LAT, LON = 37.56, 126.98
COORDINATES = "37.5600, 126.9800"


@pytest.mark.parametrize("row", table_params(read_csv("api_key_decode.csv"), lambda r: r["분류"]))
def test_api_key_is_decoded_once(row):
    """
    [Given] 인코딩됐거나 그렇지 않은 API 키 문자열
    [When]  KMAWeatherAPI 를 만든다
    [Then]  api_key 는 한 번만 디코딩된 값이고, 입력 원본은 따로 보관된다
    """
    api = KMAWeatherAPI(None, row["입력"])

    assert api.api_key == row["기대_api_key"]
    assert api._raw_api_key == row["입력"]


def hass_for(token):
    if token == "(hass 없음)":
        return None
    return SimpleNamespace(installation_uuid=None if token == "(UUID 없음)" else token)


USER_AGENT_ROWS = table_params(read_csv("user_agent.csv"), lambda r: r["분류"])


@pytest.mark.parametrize("row", USER_AGENT_ROWS)
def test_nominatim_user_agent(row):
    """
    [Given] hass(설치 UUID 유무) 와 API 키
    [When]  KMAWeatherAPI 를 만든다
    [Then]  User-Agent 가 표의 값이다 (UUID 앞 12자리, 없으면 키 해시 앞 12자리)
    """
    api = KMAWeatherAPI(MagicMock(), row["api_key"], hass=hass_for(row["hass_uuid"]))

    assert api._nominatim_user_agent == row["기대_User-Agent"]


@pytest.mark.parametrize("row", USER_AGENT_ROWS)
def test_address_request_sends_user_agent_and_korean(row):
    """
    [Given] 정상 응답을 주는 Nominatim 과 표의 hass/키
    [When]  _get_address 를 호출한다
    [Then]  요청 헤더에 그 User-Agent 와 Accept-Language=ko 가 실린다
    """
    session, _ = scripted_session([json.dumps({"address": {"city": "서울특별시"}})])
    sent = {}
    original_get = session.get

    def spy_get(*args, **kwargs):
        sent.update(kwargs)
        return original_get(*args, **kwargs)

    session.get = spy_get
    api = KMAWeatherAPI(session, row["api_key"], hass=hass_for(row["hass_uuid"]))

    run(api._get_address(LAT, LON))

    assert sent["headers"] == {"User-Agent": row["기대_User-Agent"], "Accept-Language": "ko"}


def address_outcomes(token):
    if token == "(빈 JSON)":
        return ["{}"]
    if token == "(Timeout)":
        return [TimeoutError(), TimeoutError()]
    if token in ("(HTTP500)", "(HTTP429)"):
        return [int(token[5:8])] * 2
    if token == "(주소 없음)":
        return [json.dumps({"address": {}})]
    return [json.dumps({"address": dict(pair.split("=") for pair in token.split(";"))})]


@pytest.mark.parametrize("row", table_params(read_csv("address_lookup.csv"), lambda r: r["분류"]))
def test_get_address(row):
    """
    [Given] Nominatim 이 행정 단위별 주소 / 빈 응답 / 오류를 돌려줌
    [When]  _get_address 를 호출한다
    [Then]  시·구·동을 공백으로 이은 문자열, 실패하면 좌표 문자열 (예외는 밖으로 나가지 않음)
    """
    session, _ = scripted_session(address_outcomes(row["응답"]))
    api = KMAWeatherAPI(session, "key")

    expected = COORDINATES if row["기대"] == "(좌표)" else row["기대"]
    assert run(api._get_address(LAT, LON)) == expected
