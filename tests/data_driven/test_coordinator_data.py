"""데이터 드리븐: 코디네이터·좌표·구역 도우미 — 표(tests/data_driven/cases/*.csv|yaml)만 고치면 케이스가 늘어난다.

  location_resolution.csv   기기 위치 결정 (엔티티 → 직전 유효 좌표 → HA 기본 좌표)
  korean_coord_range.csv    한반도 인근 좌표 범위 경계
  convert_grid.csv          위경도 → 기상청 격자 (ON/OFF 경계값)
  safe_float.csv            문자열 → 숫자 변환
  land_codes.csv            기온 구역 → 육상 구역 코드
  geo_distance.csv          두 좌표 사이 거리
  malformed_short_response.yaml  비정상 구조의 단기·중기예보 응답
"""
from unittest.mock import MagicMock

import pytest

from custom_components.kma_weather import coordinator as coordinator_module
from custom_components.kma_weather.const import (
    convert_grid, haversine, is_korean_coord_loose, safe_float)
from custom_components.kma_weather.coordinator import KMAWeatherUpdateCoordinator
from custom_components.kma_weather.sensor import SENSOR_TYPES
from testkit.factories import kst, make_coordinator
from testkit.forecasts import make_api
from testkit.tables import read_csv, read_yaml, table_params

coordinator_module._load_area_data()  # 구역코드 표 로드 (정적 데이터)

NONE_TOKENS = {"(None)": None, "(빈칸)": "", "(없음)": None}
HA_DEFAULT = (37.56, 126.98)  # 테스트용 HA 기본 좌표 (testkit.factories 의 가짜 hass 설정)


def token(value):
    return NONE_TOKENS.get(value, value)


# ── 기기 위치 결정 ───────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "row", table_params(read_csv("location_resolution.csv"), lambda r: r["분류"]))
def test_resolve_location(row):
    """
    [Given] 위치 엔티티 상태(좌표 유효/일부 누락/범위 밖/비숫자/없음), 직전 유효 좌표, HA 기본 좌표
    [When]  _resolve_location
    [Then]  엔티티 좌표 → 직전 유효 좌표 → HA 기본 좌표 → (없음) 순으로 결정된다
    """
    coord = make_coordinator(location_entity="zone.home")
    attributes = {}
    for key, column in (("latitude", "엔티티_위도"), ("longitude", "엔티티_경도")):
        if row[column] != "(없음)":
            attributes[key] = row[column]
    coord.hass.states.get = MagicMock(return_value=None if row["엔티티"] == "(없음)" else MagicMock(attributes=attributes))
    coord.hass.config.latitude, coord.hass.config.longitude = HA_DEFAULT if row["HA기본_유효"] == "예" else (0.0, 0.0)
    coord._last_lat = coord._last_lon = None
    if row["직전"] != "(없음)":
        coord._last_lat, coord._last_lon = map(float, row["직전"].split(";"))

    location = KMAWeatherUpdateCoordinator._resolve_location(coord)

    expected = {"HA기본": HA_DEFAULT, "(없음)": (None, None)}.get(row["기대"]) \
        or tuple(map(float, row["기대"].split(";")))
    assert location == pytest.approx(expected) if None not in expected else location == expected


@pytest.mark.parametrize(
    "row", table_params(read_csv("korean_coord_range.csv"), lambda r: f"{r['분류']}[{r['위도']},{r['경도']}]"))
def test_korean_coordinate_range(row):
    """한반도 인근 좌표 범위의 경계 안/밖 (위도 32.0~42.5, 경도 124.0~132.5, NaN 은 무효)."""
    assert is_korean_coord_loose(float(row["위도"]), float(row["경도"])) is (row["기대_유효"] == "예")


# ── 격자 변환 / 숫자 변환 / 구역 코드 / 거리 ─────────────────────────────────
@pytest.mark.parametrize(
    "row", table_params(read_csv("convert_grid.csv"), lambda r: r["분류"]))
def test_convert_grid(row):
    """
    [Given] 위경도 (한국 영토 극단부 ON 값 / 범위 완전 이탈 OFF 값)
    [When]  기상청 격자로 변환
    [Then]  ON 값은 기상청 기준 격자와 일치, OFF 값도 예외 없이 정수 쌍을 돌려준다 (현재 값 고정)
    """
    nx, ny = convert_grid(float(row["위도"]), float(row["경도"]))

    assert (nx, ny) == (int(row["기대_nx"]), int(row["기대_ny"]))
    assert isinstance(nx, int) and isinstance(ny, int)


@pytest.mark.parametrize("row", table_params(read_csv("safe_float.csv"), lambda r: f"{r['분류']}[{r['입력']}]"))
def test_safe_float(row):
    """숫자로 읽을 수 있으면 float, 아니면 None (결측 기호·빈 값·None·문자열 모두 예외 없음)."""
    expected = token(row["기대"])

    assert safe_float(token(row["입력"])) == (None if expected is None else float(expected))


@pytest.mark.parametrize("row", table_params(read_csv("land_codes.csv"), lambda r: r["분류"]))
def test_land_code(row):
    assert coordinator_module._land_code(row["기온구역"]) == row["기대_육상구역"]


@pytest.mark.parametrize("row", table_params(read_csv("geo_distance.csv"), lambda r: r["분류"]))
def test_haversine_distance(row):
    km = haversine(float(row["위도1"]), float(row["경도1"]), float(row["위도2"]), float(row["경도2"]))

    assert float(row["기대_최소"]) <= km <= float(row["기대_최대"])


def test_every_mid_term_area_resolves_to_itself():
    """모든 중기예보 기온 구역의 중심 좌표로 구역을 찾으면 그 구역이 나온다 (제외 대상 구역 제외), 육상 코드 형식도 맞다."""
    for area_id, (lat, lon) in coordinator_module._TEMP_ID_COORDS.items():
        if area_id in coordinator_module._EXCLUDE_FROM_NEAREST:
            continue
        found, land = coordinator_module._calc_reg_ids(lat, lon)

        assert found == area_id
        assert land.endswith("0000") or land in ("11A00101", "11E00101"), land


# ── 비정상 구조의 단기예보 응답 ──────────────────────────────────────────────
@pytest.mark.parametrize(
    "row", table_params(read_yaml("malformed_short_response.yaml"), lambda r: r["분류"]))
def test_malformed_short_response_does_not_stop_the_merge(row):
    """
    [Given] HTTP 200 이지만 JSON 구조가 비정상인 단기예보 응답
    [When]  _merge_all
    [Then]  예외 없이 이어지고 일 예보는 10칸, 기온은 비어 있다 (단건 dict 는 정상 항목으로 읽혀 기온이 채워짐)
    """
    now = kst(2026, 4, 24, 12)
    api = make_api()
    if row.get("대상") == "중기":
        result = api._merge_all(now, None, (row["응답"], row["응답"], api._get_mid_base_dt(now)), {})
    else:
        result = api._merge_all(now, row["응답"], None, {})

    assert result["weather"]["TMP"] == row.get("기대_TMP")
    assert len(result["weather"]["forecast_daily"]) == 10


# ── 관측 조건: 달 조명율 표시 ────────────────────────────────────────────────
def illumination_input(value):
    if value == "(None)":
        return None
    if value.startswith("s:"):
        return value[2:]
    return float(value) if "." in value else int(value)


@pytest.mark.parametrize(
    "row", table_params(read_csv("moon_illumination.csv"), lambda r: f"{r['분류']}[{r['달_조명율_입력']}]"))
def test_moon_illumination_display(row):
    """
    [Given] 날씨 데이터의 달 조명율 값 (정수/문자열/소수/숫자 아님/결측)
    [When]  관측 조건 평가(_eval_observation)
    [Then]  읽을 수 있으면 'N%', 아니면 '-' 로 표시한다
    """
    weather = {"current_condition": "sunny", "WSD": 2.0, "moon_phase": "보름달",
               "moon_illumination": illumination_input(row["달_조명율_입력"]), "current_condition_kor": "맑음"}

    _condition, attributes = make_coordinator()._eval_observation(weather, kst(2026, 4, 11, 22), 37.56, 126.98)

    assert attributes["달_조명율"] == row["기대_표시"]


# ── 센서 정의 ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("key", sorted(SENSOR_TYPES))
def test_sensor_definition_structure(key):
    """모든 센서 정의가 6개 필드(이름, 단위, 아이콘, 디바이스 클래스, 접미사, 카테고리)를 갖추고 이름·mdi 아이콘·접미사가 비어 있지 않다."""
    details = SENSOR_TYPES[key]
    name, _unit, icon, _device_class, suffix, _category = details

    assert len(details) == 6
    assert isinstance(name, str) and name
    assert isinstance(icon, str) and icon.startswith("mdi:")
    assert isinstance(suffix, str) and suffix


def test_sensor_entity_id_suffixes_are_unique():
    suffixes = [details[4] for details in SENSOR_TYPES.values()]

    assert len(suffixes) == len(set(suffixes)), [s for s in suffixes if suffixes.count(s) > 1]
