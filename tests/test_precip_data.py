"""데이터 드리븐: 현재 예상 강수량 — 표(tests/data/*.csv|yaml)만 고치면 케이스가 늘어난다.

  동등분할 + 경계값분석 : precip_amount.csv
  센서 노출 방식       : precip_sensor_exposure.yaml
  페어와이즈 조합      : precip_pairwise.csv (생성기: python tests/testkit/pairwise.py)
"""

import pytest

from testkit.factories import kst, make_api, short_forecast
from testkit.tables import number_or_text, read_csv, read_yaml, table_params

NOW = kst(2026, 10, 19, 14, 30)  # 현재 슬롯 14시, 다음 슬롯 15시


def merge(raw, pty, *, now=NOW, days=2, every_hour=False):
    """원본값이 현재/다음 슬롯(또는 모든 슬롯)에 들어간 단기예보로 _merge_all 을 실행한다."""
    hours = range(24) if every_hour else (now.hour, now.hour + 1)
    forecast = short_forecast(
        now, days=days,
        pcp_by_hour={h: raw for h in hours},
        pty_by_hour={h: str(pty) for h in hours})
    return make_api()._merge_all(now, forecast, None, {})["weather"]


@pytest.mark.parametrize(
    "row", table_params(read_csv("precip_amount.csv"), lambda r: f"{r['분류']}[{r['원본값']}]"))
def test_precip_amount_from_raw_value(row):
    """
    [Given] PTY 와 원본값(PCP 또는 SNO)이 표의 한 행인 단기예보
    [When]  14:30 에 갱신
    [Then]  상태값 / 표기 속성 / 다음 시각(15시) 속성이 표의 기대값과 같다
    """
    weather = merge(row["원본값"], row["pty"])

    assert weather["precip_amount"] == float(row["기대_상태"])
    assert weather["precip_amount_display"] == row["기대_표기"]
    assert weather["hourly_precipitation_mm"]["15시"] == number_or_text(row["기대_시간대값"])


@pytest.mark.parametrize(
    "row", table_params(read_yaml("precip_sensor_exposure.yaml"), lambda r: r["분류"]))
def test_sensor_exposes_state_and_attributes(row):
    """
    [Given] 코디네이터 데이터(weather)가 표의 한 행
    [When]  센서의 native_value / extra_state_attributes 를 읽음
    [Then]  상태값은 precip_amount, 속성은 시간대별 값(+표기)이 평탄하게 노출됨
    """
    from unittest.mock import MagicMock
    from custom_components.kma_weather.sensor import KMACustomSensor

    sensor = KMACustomSensor.__new__(KMACustomSensor)
    sensor.coordinator = MagicMock(data={"weather": row["weather"], "air": {}})
    sensor._type = "precip_amount"
    sensor._entry = MagicMock(entry_id="testkit")
    sensor._attr_native_unit_of_measurement = "mm"

    assert sensor.native_value == row["기대_상태"]
    assert sensor.extra_state_attributes == row["기대_속성"]


# ── 페어와이즈 ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "row", table_params(read_csv("precip_pairwise.csv"),
                        lambda r: f"PTY{r['pty']}/{r['형식']}/{r['현재시각']}/{r['예보일수']}일"))
def test_precip_pairwise_combinations(row):
    """
    [Given] PTY × 원본값 형식 × 현재 시각 × 예보 일수 의 페어와이즈 조합 한 행
    [When]  그 시각에 갱신 (모든 슬롯에 같은 원본값)
    [Then]  상태값 / 표기 / 확인 키의 속성 값이 오라클(기대값)과 같다
    """
    hour, minute = map(int, row["현재시각"].split(":"))
    weather = merge(row["원본값"], row["pty"], now=kst(2026, 10, 19, hour, minute),
                    days=int(row["예보일수"]), every_hour=True)

    assert weather["precip_amount"] == float(row["기대_상태"])
    assert weather["precip_amount_display"] == row["기대_표기"]
    assert weather["hourly_precipitation_mm"][row["확인_키"]] == number_or_text(row["기대_속성값"])


def test_pairwise_table_is_up_to_date():
    """커밋된 페어와이즈 표가 생성기(요인·오라클)와 일치한다. (갱신: python tests/testkit/pairwise.py)"""
    from testkit import pairwise
    assert pairwise.CSV_PATH.read_text(encoding="utf-8") == pairwise.render()


def test_pairwise_table_covers_every_value_pair():
    """표에 모든 요인 쌍의 모든 값 조합이 최소 한 번씩 등장한다 (페어와이즈의 정의)."""
    from itertools import combinations, product
    from testkit.pairwise import FACTORS

    rows = read_csv("precip_pairwise.csv")
    for first, second in combinations(FACTORS, 2):
        seen = {(row[first], row[second]) for row in rows}
        assert seen == set(product(FACTORS[first], FACTORS[second])), f"{first} × {second}"


def test_pairwise_table_is_smaller_than_full_factorial():
    """페어와이즈는 전체 조합(96)보다 훨씬 적은 행으로 같은 쌍 커버리지를 얻는다."""
    from math import prod
    from testkit.pairwise import FACTORS

    assert len(read_csv("precip_pairwise.csv")) < prod(len(v) for v in FACTORS.values()) / 3
