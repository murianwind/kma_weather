"""데이터 드리븐: 자외선지수(UV) — 표(tests/data_driven/cases/uv_*.csv|yaml)만 고치면 케이스가 늘어난다.

  경계값분석 + 동등분할 : uv_grade.csv (등급 경계), uv_base_time.csv (3시간 발표 구간)
  동등분할             : uv_sensor_exposure.yaml (센서의 상태/속성/가용성), uv_area_codes.csv (지역 매칭)
"""
import json
import pathlib
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.kma_weather.api_kma import KMAWeatherAPI
from custom_components.kma_weather.sensor import SENSOR_API_GROUPS, SENSOR_TYPES, KMACustomSensor
from testkit.aio import run
from testkit.factories import KST, make_coordinator
from testkit.tables import read_csv, read_yaml, table_params

AREA_MAP = (pathlib.Path(__file__).resolve().parents[2] / "custom_components"
            / "kma_weather" / "admin_area_map.json")


# ── 경계값분석 + 동등분할: 등급 ──────────────────────────────────────────────
GRADE_INPUTS = {"(None)": None, "(빈칸)": ""}


@pytest.mark.parametrize(
    "row", table_params(read_csv("uv_grade.csv"), lambda r: f"{r['분류']}[{r['입력']}]"))
def test_uv_grade_boundaries(row):
    """
    [Given] 자외선지수 입력값 (등급 경계의 아래/정확히/위, 또는 잘못된 값)
    [When]  _get_uv_grade 로 등급 변환
    [Then]  표의 기대 등급 (변환할 수 없으면 None)
    """
    value = GRADE_INPUTS.get(row["입력"], row["입력"])
    expected = None if row["기대_등급"] == "(없음)" else row["기대_등급"]

    assert KMAWeatherAPI._get_uv_grade(value) == expected


# ── 경계값분석 + 동등분할: 발표 시각 ─────────────────────────────────────────
@pytest.mark.parametrize(
    "row", table_params(read_csv("uv_base_time.csv"),
                        lambda r: f"{r['분류']}[{int(r['시']):02d}:{int(r['분']):02d}]"))
def test_uv_base_time_rounds_down_to_three_hour_mark(row):
    """
    [Given] 현재 시각 (3시간 구간 대표값, 구간의 첫 분과 마지막 분)
    [When]  _calc_uv_base_time
    [Then]  가장 최근에 발표된 시각(00,03,…,21시)의 YYYYMMDDHH
    """
    now = datetime(2026, 8, 16, int(row["시"]), int(row["분"]), tzinfo=KST)

    assert KMAWeatherAPI._calc_uv_base_time(now) == f"20260816{row['기대_발표시']}"


# ── 동등분할: 센서 노출 ──────────────────────────────────────────────────────
def _sensor(row):
    coordinator = MagicMock()
    coordinator.data = {"weather": {}, "air": {}, "uv": row["uv"]}
    coordinator.api._approved_apis = set(row.get("approved", []))
    coordinator.last_update_success = True
    return KMACustomSensor(coordinator, row["센서"], "kma_weather", MagicMock())


@pytest.mark.parametrize(
    "row", table_params(read_yaml("uv_sensor_exposure.yaml"), lambda r: r["분류"]))
def test_uv_sensor_exposure(row):
    """
    [Given] 코디네이터의 uv 데이터와 센서 종류(uv_value / uv_grade), 승인 상태
    [When]  센서의 상태 / 속성 / 가용성을 읽음
    [Then]  표에 적힌 항목만 기대값과 같다
    """
    sensor = _sensor(row)

    if "기대_상태" in row:
        assert sensor.native_value == row["기대_상태"]
        assert type(sensor.native_value) is type(row["기대_상태"])  # 정수 값은 int, 소수 값은 float 으로 낸다
    if "기대_속성" in row:
        assert sensor.extra_state_attributes == row["기대_속성"]
    if "기대_가용" in row:
        assert sensor.available is row["기대_가용"]


def test_uv_sensors_are_registered_under_the_uv_api_group():
    """uv 센서 2개가 SENSOR_TYPES 에 있고 'uv' API 승인 그룹에 묶여 있다."""
    assert {"uv_value", "uv_grade"} <= set(SENSOR_TYPES)
    assert SENSOR_API_GROUPS.get("uv") == ["uv_value", "uv_grade"]


# ── 지역코드표 파일 ──────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def area_map():
    return json.loads(AREA_MAP.read_text(encoding="utf-8"))


def test_area_map_has_expected_structure(area_map):
    """지역코드표는 3000개 넘는 항목의 목록이고, 항목마다 코드/이름/위도/경도 필드를 가진다."""
    assert isinstance(area_map, list) and len(area_map) > 3000
    assert set(area_map[0]) == {"c", "n", "la", "lo"}
    assert isinstance(area_map[0]["c"], str) and isinstance(area_map[0]["n"], str)
    assert isinstance(area_map[0]["la"], float) and isinstance(area_map[0]["lo"], float)


def test_area_map_codes_are_unique(area_map):
    codes = [row["c"] for row in area_map]
    assert len(codes) == len(set(codes))


def test_area_map_reflects_recent_administrative_reorganization(area_map):
    """화성시 동탄구 신설 등 최신 행정구역이 반영돼 있다 (꽃가루 코드 파일에는 개편 이전 코드가 남아 있음)."""
    assert "경기도 화성시동탄구 동탄4동" in {row["n"] for row in area_map}


@pytest.mark.parametrize(
    "row", table_params(read_csv("uv_area_codes.csv"), lambda r: r["분류"]))
def test_nearest_area_for_coordinates(row):
    """
    [Given] 지역코드표와 좌표
    [When]  가장 가까운 지역을 찾음
    [Then]  실제 API 지역코드표에서 확인한 코드와 이름
    """
    coord = make_coordinator()
    coord.hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    code, name = run(coord.find_uv_area(float(row["위도"]), float(row["경도"])))

    assert (code, name) == (row["기대_코드"], row["기대_이름"])
