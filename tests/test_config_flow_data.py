"""데이터 드리븐: 설정 화면 API 키 검증 — tests/data/config_flow_result_codes.csv (응답 → 화면 오류 키)."""
import pytest

from custom_components.kma_weather.config_flow import _validate_api_key
from testkit.tables import read_csv, table_params

URL = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"


def register_response(aioclient_mock, token):
    if token == "(연결 오류)":
        aioclient_mock.get(URL, exc=ConnectionError("Connection refused"))
    elif token == "(코드 없음)":
        aioclient_mock.get(URL, status=200, json={"response": {"header": {}}})
    elif token.startswith("http:"):
        aioclient_mock.get(URL, status=int(token.split(":")[1]))
    else:
        aioclient_mock.get(URL, status=200, json={"response": {"header": {"resultCode": token.split(":")[1]}}})


@pytest.mark.parametrize("row", table_params(read_csv("config_flow_result_codes.csv"), lambda r: r["분류"]))
async def test_validate_api_key(row, hass, aioclient_mock):
    """
    [Given] 단기예보 호출이 표의 응답(결과 코드 / HTTP 상태 / 연결 오류)을 돌려줌
    [When]  설정 화면에서 API 키를 검증한다
    [Then]  통과하면 None, 아니면 표의 오류 키
    """
    register_response(aioclient_mock, row["응답"])

    expected = None if row["기대"] == "(None)" else row["기대"]
    assert await _validate_api_key(hass, "any_key") == expected
