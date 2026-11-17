"""데이터 드리븐: 센서 표시 — 표(tests/data_driven/cases/*.csv)만 고치면 케이스가 늘어난다.

  pollen_sensor.csv  꽃가루 센서의 상태·아이콘·속성·사용 가능 여부
  weather_icon.csv   날씨 문구 센서들의 아이콘
"""
from unittest.mock import MagicMock

import pytest

from custom_components.kma_weather.sensor import SENSOR_TYPES, KMACustomSensor
from testkit.tables import read_csv, table_params

NONE = "(None)"


def make_sensor(sensor_type, data):
    coordinator = MagicMock()
    coordinator.data = data
    entry = MagicMock()
    entry.entry_id, entry.options, entry.data = "sensor_data", {}, {"prefix": "test"}
    return KMACustomSensor(coordinator, sensor_type, "test", entry)


def pollen_data(token):
    if token == NONE:
        return None
    if token == "(빈 dict)":
        return {}
    fields = (pair.split("=", 1) for pair in token.split("|"))
    return {key: None if value == NONE else value for key, value in fields}


@pytest.mark.parametrize("row", table_params(read_csv("pollen_sensor.csv"), lambda r: r["분류"]))
def test_pollen_sensor(row):
    """
    [Given] coordinator 의 꽃가루 데이터 (API 중지 / 데이터 없음 / 등급별 / 일부 없음)
    [When]  꽃가루 센서의 상태·아이콘·속성·사용 가능 여부를 읽는다
    [Then]  표와 같다 (API 중지만 unavailable, 데이터 없음은 unknown)
    """
    sensor = make_sensor("pollen", {"weather": {}, "air": {}, "pollen": pollen_data(row["꽃가루"])})

    assert sensor.native_value == (None if row["기대_상태"] == NONE else row["기대_상태"])
    assert sensor.icon == row["기대_아이콘"]
    assert sensor.available is (row["기대_사용가능"] == "예")
    if row["기대_속성"] == "(없음)":
        assert sensor.extra_state_attributes is None
    else:
        assert sensor.extra_state_attributes == dict(pair.split("=", 1) for pair in row["기대_속성"].split("|"))


WEATHER_TEXT_SENSORS = ("current_condition_kor", "wf_am_today", "wf_pm_today", "wf_am_tomorrow", "wf_pm_tomorrow")


@pytest.mark.parametrize("sensor_type", WEATHER_TEXT_SENSORS)
@pytest.mark.parametrize("row", table_params(read_csv("weather_icon.csv"), lambda r: r["분류"]))
def test_weather_text_sensor_icon(row, sensor_type):
    """
    [Given] 날씨 문구 센서(현재·오늘 오전/오후·내일 오전/오후)의 상태값
    [When]  아이콘을 읽는다
    [Then]  상태에 맞는 mdi 아이콘, 알 수 없는 값은 기본 아이콘
    """
    sensor = make_sensor(sensor_type, {"weather": {sensor_type: row["값"]}, "air": {}, "pollen": {}})

    expected = SENSOR_TYPES[sensor_type][2] if row["기대_아이콘"] == "(센서 기본)" else row["기대_아이콘"]
    assert sensor.icon == expected
