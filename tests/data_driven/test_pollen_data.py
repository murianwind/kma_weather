"""데이터 드리븐: 꽃가루 조회 _get_pollen — tests/data_driven/cases/pollen_query.csv

시각(시즌·06:59/07:00·18:59/19:00), 승인 상태, 캐시, 종류별 API 응답을 표로 바꿔 가며
센서에 담기는 등급·최악 등급·발표 문구·승인 여부·API 조회 횟수를 확인한다.
"""
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from custom_components.kma_weather.api_kma import KMAWeatherAPI
from testkit.aio import run
from testkit.factories import KST
from testkit.tables import read_csv, table_params

KINDS = ("pine", "oak", "grass")
URL_KIND = {"Pine": "pine", "Oak": "oak", "Weeds": "grass"}
RESPONSE_COLUMNS = {"pine": "소나무", "oak": "참나무", "grass": "잡초"}
NONE = "(None)"


def api_response(token):
    """응답 토큰 → _fetch 가 돌려줄 JSON (예외는 호출하는 쪽에서 처리)."""
    def body(code, items=()):
        return {"response": {"header": {"resultCode": code}, "body": {"items": {"item": list(items)}}}}

    if token == "빈":
        return body("00")
    if token.startswith("항목:"):
        today, tomorrow = token.removeprefix("항목:").split("/")
        return body("00", [{"today": today, "tomorrow": tomorrow}])
    return body(token)  # 99 / 30


def build_api(row):
    api = KMAWeatherAPI(MagicMock(), "test_key")
    api.hass = None
    if row["승인"] == "승인":
        api._approved_apis.add("pollen")
        api._pending_apis.discard("pollen")

    now = datetime.fromisoformat(row["일시"]).replace(tzinfo=KST)
    if row["캐시"] != "(없음)":
        day, grade = row["캐시"].split(":")
        cached_date = (now if day == "오늘" else now - timedelta(days=1)).strftime("%Y%m%d")
        for kind in KINDS:
            api._pollen_cache[kind] = {"today": grade, "tomorrow": None,
                                       "today_date": cached_date, "tomorrow_date": None}

    calls = []

    async def fake_fetch(url, params, *args, **kwargs):
        kind = next(kind for name, kind in URL_KIND.items() if name in url)
        calls.append(params["time"])
        token = row[RESPONSE_COLUMNS[kind]]
        if token == "예외":
            raise ConnectionError("boom")
        return api_response(token)

    api._fetch = fake_fetch
    return api, now, calls


@pytest.mark.parametrize("row", table_params(read_csv("pollen_query.csv"), lambda r: r["분류"]))
def test_get_pollen(row):
    """
    [Given] 시각 · 승인 상태 · 캐시 · 종류별 API 응답
    [When]  _get_pollen
    [Then]  등급·최악 등급·발표 문구, 승인 여부, API 조회 횟수와 첫 조회 시각, 내일 캐시가 표와 같다
    """
    api, now, calls = build_api(row)

    result = run(api._get_pollen(now, "1111051500", "서울"))

    assert ("pollen" in api._approved_apis) == (row["기대_승인"] == "예")
    assert len(calls) == int(row["기대_조회수"])
    if calls:
        assert calls[0] == row["기대_첫조회시각"]

    if row["기대_결과"] == "(None)":
        assert result is None
        return

    expected = {kind: (None if row[f"기대_{RESPONSE_COLUMNS[kind]}"] == NONE else row[f"기대_{RESPONSE_COLUMNS[kind]}"])
                for kind in KINDS}
    expected["worst"] = None if row["기대_최악"] == NONE else row["기대_최악"]
    assert {key: result[key] for key in (*KINDS, "worst")} == expected
    assert result["announcement"] == row["기대_발표"]
    assert (result["area_no"], result["area_name"]) == ("1111051500", "서울")
    tomorrow = api._pollen_cache["pine"]["tomorrow"]
    assert tomorrow == (None if row["기대_내일캐시"] == NONE else row["기대_내일캐시"])
