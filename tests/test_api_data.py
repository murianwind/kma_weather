"""데이터 드리븐: 기상특보 · API 서비스 · 구역코드 — 표(tests/data/*.csv|yaml)만 고치면 케이스가 늘어난다.

  warning_items.yaml          _get_warning 이 특보 항목을 표시 문자열로 바꾸는 규칙 (동등분할 + 발표 시각 경계)
  warn_type_map.csv           특보 종류 코드 → 이름 (열대야 누락 재발 방지)
  unsubscribed_codes.csv      resultCode 가 미신청/접근 거부인가 (경계값분석)
  api_services.csv            공공데이터포털 서비스 이름·URL
  area_resolution.csv         좌표 → 중기예보/특보 구역코드
  eligible_sensors.yaml       승인된 API → 등록되는 센서
  api_sensor_availability.yaml  센서 상태·사용 가능 여부
  fetch_gating.csv              승인·대기 중인 API 만 조회하는 규칙
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.kma_weather import coordinator as coordinator_module
from custom_components.kma_weather.api_kma import KMAWeatherAPI
from custom_components.kma_weather.const import API_SERVICES, WARN_TYPE_MAP
from custom_components.kma_weather.sensor import (
    SENSOR_TYPES, KMACustomSensor, _eligible_sensor_types)
from testkit.aio import run
from testkit.factories import kst, make_api
from testkit.tables import read_csv, read_yaml, table_params

coordinator_module._load_area_data()  # 구역코드 표 로드 (정적 데이터)


def yes(token):
    return token == "예"


# ── _get_warning: 항목 → 표시 문자열 ─────────────────────────────────────────
def warning_response(items):
    return {"response": {"header": {"resultCode": "00", "resultMsg": "NORMAL_SERVICE"},
                         "body": {"items": {"item": items}}}}


@pytest.mark.parametrize(
    "row", table_params(read_yaml("warning_items.yaml"), lambda r: r["분류"]))
def test_get_warning_formats_active_warnings(row):
    """
    [Given] API 가 특보 항목(발표/연장/해제/취소/종류/수준)을 돌려줌
    [When]  _get_warning 호출 (기상청 페이지 보완은 없음으로 고정)
    [Then]  유효한 특보만 이름으로 표시되고, 없으면 '특보없음'
    """
    api = make_api()
    api._fetch = AsyncMock(return_value=warning_response(row["항목"]))
    api._fetch_page_warnings_for_area = AsyncMock(return_value={})

    assert run(api._get_warning("L1100200")) == row["기대"]


@pytest.mark.parametrize("row", table_params(read_csv("warn_type_map.csv"), lambda r: f"warnVar {r['warnVar']}"))
def test_warn_type_map_names(row):
    """모든 특보 종류 코드의 주의보/경보(/중대경보) 이름이 표와 같다 (13=열대야 포함)."""
    names = WARN_TYPE_MAP[row["warnVar"]]
    expected = [row["주의보"], row["경보"]] + ([] if row["중대경보"] == "(없음)" else [row["중대경보"]])

    assert list(names) == expected


def test_warn_type_map_covers_exactly_the_tabled_codes():
    assert set(WARN_TYPE_MAP) == {row["warnVar"] for row in read_csv("warn_type_map.csv")}


# ── 미신청 코드 / 서비스 정보 ────────────────────────────────────────────────
@pytest.mark.parametrize(
    "row", table_params(read_csv("unsubscribed_codes.csv"), lambda r: f"{r['분류']}[{r['resultCode']}]"))
def test_result_code_is_unsubscribed(row):
    """
    [Given] API 응답의 resultCode
    [When]  _check_unsubscribed 로 미신청/접근 거부인지 판정
    [Then]  미신청 코드 집합에 속할 때만 True (경계: 19/20, 22/23, 29/30, 33/34)
    """
    code = "" if row["resultCode"] == "(빈칸)" else row["resultCode"]

    assert KMAWeatherAPI(MagicMock(), "key")._check_unsubscribed("short", code) is yes(row["기대_미신청"])


@pytest.mark.parametrize("row", table_params(read_csv("api_services.csv"), lambda r: r["키"]))
def test_api_service_registration(row):
    """서비스 키마다 이름과 data.go.kr 신청 URL(데이터셋 ID)이 등록되어 있다."""
    name, url = API_SERVICES[row["키"]]

    assert name == row["이름"]
    assert url.startswith("https://www.data.go.kr/") and row["URL_데이터셋_ID"] in url


def test_api_services_are_exactly_the_registered_keys_with_distinct_urls():
    """서비스는 표의 7개뿐이고, 신청 URL 은 서로 달라야 한다 (자외선지수와 꽃가루는 별개의 신청 건)."""
    assert set(API_SERVICES) == {row["키"] for row in read_csv("api_services.csv")}
    urls = [url for _, url in API_SERVICES.values()]
    assert len(urls) == len(set(urls))


# ── 구역코드 ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "row", table_params(read_csv("area_resolution.csv"), lambda r: f"{r['분류']}"))
def test_area_codes_for_coordinates(row):
    """
    [Given] 좌표
    [When]  중기예보 구역코드와 특보 구역코드를 계산
    [Then]  표의 코드와 같다 (제외 대상 구역은 선택되지 않음)
    """
    lat, lon = float(row["위도"]), float(row["경도"])

    assert coordinator_module._calc_reg_ids(lat, lon) == (row["기대_기온구역"], row["기대_육상구역"])
    assert coordinator_module._calc_warn_area_code(lat, lon) == row["기대_특보구역"]


def test_area_tables_are_loaded():
    """구역코드 표(area.json, warn_area.json)가 읽혀 있고 구조가 맞다."""
    assert len(coordinator_module._TEMP_ID_COORDS) > 100 and "11B10101" in coordinator_module._TEMP_ID_COORDS
    assert len(coordinator_module._LAND_CODE_MAP) >= 14
    assert dict(coordinator_module._LAND_CODE_MAP).get("11B") == "11B00000"
    assert {"11G00601", "11E00102"} <= coordinator_module._EXCLUDE_FROM_NEAREST
    first = coordinator_module._WARN_AREA[0]
    assert len(coordinator_module._WARN_AREA) > 500 and isinstance(first[0], float) and first[2].startswith("L")


# ── 센서 등록 / 상태 / 사용 가능 여부 ────────────────────────────────────────
@pytest.mark.parametrize("row", table_params(read_yaml("eligible_sensors.yaml"), lambda r: r["분류"]))
def test_eligible_sensors_follow_approved_apis(row):
    """
    [Given] 승인된 API 키 목록
    [When]  등록 가능한 센서 종류를 계산
    [Then]  승인된 API 의 센서만 포함되고 상시 센서는 항상 포함된다
    """
    coordinator = MagicMock()
    coordinator.api._approved_apis = set(row["approved"])

    eligible = _eligible_sensor_types(coordinator)

    assert all(sensor in eligible for sensor in row["포함"])
    assert not any(sensor in eligible for sensor in row["제외"])


def test_newly_approved_api_adds_its_sensors():
    """처음엔 없던 꽃가루 센서가 pollen API 가 승인되면 목록에 추가된다."""
    coordinator = MagicMock()
    coordinator.api._approved_apis = set()
    before = set(_eligible_sensor_types(coordinator))
    coordinator.api._approved_apis = {"pollen"}

    assert "pollen" in set(_eligible_sensor_types(coordinator)) - before


@pytest.mark.parametrize("row", table_params(read_yaml("api_sensor_availability.yaml"), lambda r: r["분류"]))
def test_sensor_state_and_availability(row):
    """
    [Given] 코디네이터 데이터와 승인된 API 목록 (코디네이터 자체는 정상 갱신 중)
    [When]  센서의 상태/사용 가능 여부를 읽음
    [Then]  표에 적힌 항목만 기대값과 같다
    """
    coordinator = MagicMock(data=row["data"])
    coordinator.api._approved_apis = set(row["approved"])
    coordinator._daily_max_temp = coordinator._daily_min_temp = None
    entry = MagicMock(options={}, data={"prefix": "test"})

    with patch.object(CoordinatorEntity, "available", new_callable=lambda: property(lambda self: True)):
        sensor = KMACustomSensor(coordinator, row["센서"], "test", entry)
        if "기대_상태" in row:
            assert sensor.native_value == row["기대_상태"]
        if "기대_가용" in row:
            assert sensor.available is row["기대_가용"]


def test_warning_sensor_definition():
    """기상특보 센서 정의: 이름, 단위 없음, 아이콘, 접미사, 일반 카테고리."""
    name, unit, icon, _device_class, suffix, category = SENSOR_TYPES["warning"]

    assert (name, unit, icon, suffix, category) == ("기상특보", None, "mdi:alert-outline", "warning", None)


# ── fetch_data: 승인/대기 중인 API 만 호출 ──────────────────────────────────
def names(token):
    return set() if token == "(없음)" else set(token.split(";"))


@pytest.mark.parametrize("row", table_params(read_csv("fetch_gating.csv"), lambda r: r["분류"]))
def test_fetch_data_calls_only_eligible_apis(row):
    """
    [Given] 승인된 API 와 승인 대기 중인 API 목록
    [When]  fetch_data
    [Then]  둘 중 하나에 있는 조회만 호출된다 (단기·중기·주소 조회는 항상 호출)
    """
    api = make_api()
    api._approved_apis, api._pending_apis = names(row["승인"]), names(row["대기"])
    called = set()

    def stub(name, value):
        async def call(*_args, **_kwargs):
            called.add(name)
            return value
        return call

    api._get_short_term = stub("short", None)
    api._get_mid_term = stub("mid", (None, None, kst(2026, 4, 11, 6)))
    api._get_address = stub("address", "서울시")
    api._get_air_quality = stub("air", {})
    api._get_warning = stub("warning", "없음")
    api._get_pollen = stub("pollen", {})
    api._get_uv_index = stub("uv", {})

    run(api.fetch_data(lat=37.56, lon=126.98, nx=60, ny=127, reg_id_temp="11B10101",
                       reg_id_land="11B00000", warn_area_code="L1100200",
                       pollen_area_no="1111051500", pollen_area_name="서울",
                       uv_area_no="1111051500", uv_area_name="서울"))

    assert called - {"short", "mid", "address"} == names(row["기대_호출"])
    assert {"short", "mid", "address"} <= called
