"""데이터 드리븐: 천문 정보 서비스 입력 처리 — 시각 해석 / 주소 지오코딩 / 계산 전 점검 순서.

  time_parse.csv            _parse_time_str 의 입력 → 시각/오류
  geocode_results.csv       _geocode_ko 의 Nominatim 응답 → 좌표
  astro_service_errors.csv  _handle_get_astronomical_info 가 계산 전에 거르는 입력·환경 오류
(천문 계산 자체는 test_astro_sensors.py)
"""
from datetime import datetime, time, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.core import ServiceCall
from homeassistant.exceptions import HomeAssistantError

from custom_components.kma_weather.__init__ import (
    _geocode_ko, _handle_get_astronomical_info, _parse_time_str)
from custom_components.kma_weather.const import DOMAIN
from testkit.tables import read_csv, table_params

KST = ZoneInfo("Asia/Seoul")
NONE = "(None)"


# ── _parse_time_str ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("row", table_params(read_csv("time_parse.csv"), lambda r: f"{r['분류']}[{r['입력']}]"))
def test_parse_time_str(row):
    """
    [Given] 서비스에 입력한 시각 문자열
    [When]  _parse_time_str 로 해석한다
    [Then]  시각이 되거나, 빈 값/형식 오류는 안내 문구가 담긴 HomeAssistantError
    """
    text = "" if row["입력"] == "(빈 값)" else row["입력"]

    if row["기대"].startswith("오류:"):
        with pytest.raises(HomeAssistantError, match=row["기대"].removeprefix("오류:")):
            _parse_time_str(text)
    else:
        assert _parse_time_str(text) == time.fromisoformat(row["기대"])


# ── _geocode_ko ───────────────────────────────────────────────────────────────
GEOCODE_URL = "https://nominatim.openstreetmap.org/search"


def register_geocode(aioclient_mock, token):
    if token == "(연결 오류)":
        aioclient_mock.get(GEOCODE_URL, exc=Exception("Conn Error"))
    elif token == "(빈 목록)":
        aioclient_mock.get(GEOCODE_URL, json=[])
    else:
        fields = dict(pair.split("=") for pair in token.split(";"))
        first = {"lat": fields["lat"], "lon": fields["lon"]}
        if "name" in fields:
            first["display_name"] = fields["name"]
        aioclient_mock.get(GEOCODE_URL, json=[first])


@pytest.mark.parametrize("row", table_params(read_csv("geocode_results.csv"), lambda r: r["분류"]))
async def test_geocode_ko(row, hass, aioclient_mock):
    """
    [Given] Nominatim 이 표의 응답(결과 / 빈 목록 / 이상한 값 / 연결 오류)을 돌려줌
    [When]  한국어 주소를 위·경도로 바꾼다
    [Then]  첫 결과의 (위도, 경도, 이름), 실패하면 (None, None, None) — 예외는 밖으로 나가지 않는다
    """
    register_geocode(aioclient_mock, row["응답"])

    result = await _geocode_ko(hass, "주소")

    if row["기대"] == "(실패)":
        assert result == (None, None, None)
    else:
        lat, lon, name = row["기대"].split(";")
        assert result == (float(lat), float(lon), None if name == NONE else name)


# ── _handle_get_astronomical_info: 계산 전 점검 ──────────────────────────────
def build_call(hass, row):
    data = {"address": " " if row["주소"] == "(공백)" else row["주소"]}
    if row["날짜"] != "(없음)":
        data["date"] = datetime.now(KST).date() + timedelta(days=int(row["날짜"]))
    if row["시각"] != "(없음)":
        data["time"] = row["시각"]
    call = MagicMock(spec=ServiceCall)
    call.hass, call.data = hass, data
    return call


def prepare_environment(hass, token):
    """환경 토큰: 통합없음 / 라이브러리없음 / 계산오류 / 정상준비 (뒤로 갈수록 더 준비된 상태)."""
    coordinator = MagicMock()
    coordinator._sf_eph = None if token == "라이브러리없음" else MagicMock()
    coordinator._sf_ts = MagicMock()
    coordinator.calc_astronomical_for_date = AsyncMock(return_value={"error": "Unknown Calc Error"})
    hass.data[DOMAIN] = {} if token == "통합없음" else {"entry": coordinator}


@pytest.mark.parametrize("row", table_params(read_csv("astro_service_errors.csv"), lambda r: r["분류"]))
async def test_astro_service_rejects_before_calculation(row, hass):
    """
    [Given] 입력(주소·날짜·시각)과 환경(지오코딩·통합·천문 라이브러리)이 표와 같음
    [When]  천문 정보 서비스를 호출한다
    [Then]  첫 번째로 걸리는 점검에서 안내 문구가 담긴 HomeAssistantError 가 난다
    """
    prepare_environment(hass, row["환경"])
    coords = (None, None, None) if row["좌표"] == "(실패)" else (*map(float, row["좌표"].split(";")), "서울")

    with patch("custom_components.kma_weather.__init__._geocode_ko", AsyncMock(return_value=coords)):
        with pytest.raises(HomeAssistantError, match=row["기대_오류"]):
            await _handle_get_astronomical_info(build_call(hass, row))
