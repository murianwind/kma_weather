"""데이터 드리븐: 공통 호출(_fetch)의 재시도와 최종 실패 로그 — tests/data/fetch_retry.csv

예외 종류·HTTP 상태·응답 본문 형식에 따라 한 번 더 재시도하거나 바로 포기한다.
에어코리아는 15초 안에 응답하지 않는 일이 잦아 호출자가 fail_log_level 로 최종 실패 로그 레벨을 낮출 수 있다.
"""
import asyncio
import logging
from unittest.mock import MagicMock

import aiohttp
import pytest

from custom_components.kma_weather.api_kma import KMAWeatherAPI
from testkit.aio import run
from testkit.factories import scripted_session
from testkit.tables import read_csv, table_params

OUTCOMES = {
    "정상": '{"ok": 1}',
    "Timeout": asyncio.TimeoutError,
    "연결끊김": aiohttp.ServerDisconnectedError,
    "예외500": lambda: aiohttp.ClientResponseError(MagicMock(), (), status=500),
    "예외503": lambda: aiohttp.ClientResponseError(MagicMock(), (), status=503),
    "예외400": lambda: aiohttp.ClientResponseError(MagicMock(), (), status=400),
    "ValueError": lambda: ValueError("boom"),
    "HTTP429": 429, "HTTP500": 500, "HTTP502": 502, "HTTP503": 503, "HTTP504": 504,
    "HTTP401": 401, "HTTP403": 403, "HTTP404": 404,
    "비JSON": "<xml>NOT JSON</xml>", "JSON배열": "[1, 2]",
}
EXPECTED = {"ok": {"ok": 1}, "(None)": None}
EXPECTED.update({f"http:{code}": {"_http_error": str(code)} for code in (401, 403, 404, 429, 500, 502, 503, 504)})


def outcome(token):
    value = OUTCOMES[token]
    if isinstance(value, type) and issubclass(value, BaseException):
        return value()
    return value() if callable(value) else value


@pytest.mark.parametrize(
    "row", table_params(read_csv("fetch_retry.csv"), lambda r: f"{r['분류']}[{r['시도_순서']}]"))
def test_fetch_retry_and_failure_log(row, caplog):
    """
    [Given] 시도마다 정해진 결과(정상/예외/HTTP 상태)를 내놓는 세션과 최종 실패 로그 레벨
    [When]  _fetch 호출
    [Then]  시도 횟수, 반환값, WARNING/ERROR 로그 건수와 문구가 표의 기대값과 같다
    """
    session, calls = scripted_session([outcome(t) for t in row["시도_순서"].split(";")])
    api = KMAWeatherAPI(session, "key")
    extra = {"fail_log_level": logging.DEBUG} if row["fail_log_level"] == "DEBUG" else {}

    with caplog.at_level(logging.DEBUG):
        result = run(api._fetch("http://example.com", {}, **extra))

    assert calls["n"] == int(row["기대_시도횟수"])
    assert result == EXPECTED[row["기대_결과"]]
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == int(row["기대_WARNING"])
    assert len([r for r in caplog.records if r.levelno == logging.ERROR]) == int(row["기대_ERROR"])
    if row["기대_로그문구"] != "-":
        assert all(phrase in caplog.text for phrase in row["기대_로그문구"].split(";"))
