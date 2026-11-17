"""데이터 드리븐: 기상특보 페이지 보완 — 표(tests/data_driven/cases/*.csv)만 고치면 케이스가 늘어난다.

  warning_page_merge.csv  API 판단 + 기상청 특보 발효현황 페이지 → 최종 표시 (병합 규칙)
  warn_area_names.csv     특보구역코드 → 지역 이름
(페이지 조회 실패 시 알림은 features/warning_page_failure.feature)
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from testkit.aio import run
from testkit.factories import make_api
from testkit.tables import read_csv, table_params

AREA_CODE = "L1091320"  # 제주시북부
NONE_TOKENS = {"(None)": None, "(빈칸)": "", "(없음)": None}


def token(value):
    return NONE_TOKENS.get(value, value)


def api_response(token_text):
    items = []
    if token_text != "(없음)":
        var, stress = token_text.split(":")
        items.append({"areaCode": AREA_CODE, "cancel": "0", "command": "1", "endTime": 0,
                      "tmFc": 202607191000, "warnVar": int(var), "warnStress": int(stress)})
    return {"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": items}}}}


SPECIAL_LINES = {
    "(콜론없음)": "o 폭염경보 제주시북부",
    "(알수없는특보)": "o 외계인경보 : 제주도(제주시북부)",
    "(o없는줄)": "폭염경보 : 제주도(제주시북부)",
}


def page_html(token_text):
    if token_text == "(블록없음)":
        return "<div>특보가 없습니다</div>"
    lines = []
    if token_text != "(없음)":
        for item in token_text.split(";"):
            if item in SPECIAL_LINES:
                lines.append(SPECIAL_LINES[item])
                continue
            kind, level, region = item.split("|")
            if level != "예비":  # 예비특보는 실제 페이지의 발효현황 요약에 나타나지 않는다
                lines.append(f"o {kind}{level} : {region}")
    content = "<br />".join(lines) if lines else "o 없음"
    return f'<div>특보 발효현황<p class="tit">{content}</p></div>'


class PageResponse:
    status = 200

    def __init__(self, html):
        self._html = html

    async def text(self):
        return self._html

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.mark.parametrize("row", table_params(read_csv("warning_page_merge.csv"), lambda r: r["분류"]))
def test_warning_api_and_page_merge(row):
    """
    [Given] API 가 알려 주는 특보와 기상청 특보 발효현황 페이지의 내용
    [When]  _get_warning
    [Then]  같은 종류는 API 수준을 우선하고, API 에 없는 우리 지역 정식 특보만 페이지에서 병합한다
    """
    api = make_api()
    api._fetch = AsyncMock(return_value=api_response(row["API"]))
    api.session = MagicMock()
    api.session.get = lambda *args, **kwargs: PageResponse(page_html(row["페이지"]))

    assert run(api._get_warning(AREA_CODE)) == ", ".join(row["기대"].split(";"))


@pytest.mark.parametrize("row", table_params(read_csv("warn_area_names.csv"), lambda r: r["분류"]))
def test_warn_area_display_name(row):
    """
    [Given] 특보구역코드 (매핑에 있는 것 / 없는 것 / 코드 없음)
    [When]  _get_warn_area_display_name
    [Then]  지역 이름, 모르면 None (예외 없음)
    """
    assert run(make_api()._get_warn_area_display_name(token(row["코드"]))) == token(row["기대"])
