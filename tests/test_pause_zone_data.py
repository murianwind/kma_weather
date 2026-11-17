"""데이터 드리븐: 일시정지 존(pause_zones) — 표(tests/data/pause_zone_*.csv)만 고치면 케이스가 늘어난다.

  경계값분석 : pause_zone_radius.csv      (반경 안/밖 경계)
  동등분할   : pause_zone_polling.csv     (정기 업데이트에서 API 를 호출하는가)
              pause_zone_visibility.csv  (옵션 화면 노출)
              pause_zone_options.csv     (옵션 저장 결과)
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kma_weather import coordinator as coordinator_module
from custom_components.kma_weather.const import DOMAIN
from testkit.aio import run
from testkit.factories import make_coordinator, meters_north, zone_state
from testkit.tables import read_csv, table_params

HOME = (37.56, 126.98)
OFFICE = (37.50, 127.02)
LOCATIONS = {"집 안": HOME, "직장 안": OFFICE,
             "집 밖": (meters_north(HOME[0], 5000), HOME[1]), "모든 존 밖": (37.40, 127.10)}


def yes(token):
    return token == "예"


def zone_list(token):
    return [] if token == "(없음)" else token.split(";")


# ── 경계값분석: 반경 ─────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "row", table_params(read_csv("pause_zone_radius.csv"), lambda r: f"{r['분류']}[반경{r['반경_m']}m/거리{r['거리_m']}m]"))
def test_inside_zone_radius_boundary(row):
    """
    [Given] 반경이 표의 값인 존 (반경 속성이 없으면 기본 100m)
    [When]  정북쪽으로 거리_m 떨어진 위치가 존 안인지 판정
    [Then]  반경 바로 안쪽은 안, 바로 바깥쪽은 밖
    """
    zone = zone_state("zone.home", *HOME)
    if row["반경_m"] == "(없음)":
        del zone.attributes["radius"]
    else:
        zone.attributes["radius"] = float(row["반경_m"])
    coord = make_coordinator(zones={"zone.home": zone}, pause_zones=["zone.home"])

    inside = coord._in_pause_zone(meters_north(HOME[0], float(row["거리_m"])), HOME[1])

    assert inside is yes(row["기대_존안"])


def test_distance_exactly_equal_to_radius_counts_as_inside():
    """
    [Given] 반경 100m 존, 위치까지 거리가 정확히 100m (실수 오차 없이 haversine 값을 고정)
    [When]  존 안인지 판정
    [Then]  경계값(반경과 같은 거리)은 존 안으로 본다
    """
    zone = zone_state("zone.home", *HOME, radius=100)
    coord = make_coordinator(zones={"zone.home": zone}, pause_zones=["zone.home"])

    with patch.object(coordinator_module, "haversine", return_value=0.1):
        assert coord._in_pause_zone(*HOME) is True


# ── 동등분할: 정기 업데이트에서의 폴링 ───────────────────────────────────────
def _zones(status):
    home, office = zone_state("zone.home", *HOME), zone_state("zone.office", *OFFICE)
    return {
        "정상": {"zone.home": home, "zone.office": office},
        "전부삭제": {},
        "속성없음": {"zone.home": _broken(), "zone.office": _broken()},
        "첫째삭제": {"zone.office": office},
    }[status]


def _broken():
    state = MagicMock()
    state.attributes = {}
    return state


@pytest.mark.parametrize(
    "row", table_params(read_csv("pause_zone_polling.csv"), lambda r: r["분류"]))
def test_polling_on_scheduled_update(row):
    """
    [Given] 기기 종류 / pause_zones 설정 / 존 상태 / 현재 위치 / API 결과가 표의 한 행
    [When]  정기 업데이트(_async_update_data) 실행
    [Then]  API 호출 횟수와 반환 데이터(온도)가 표의 기대값과 같다
    """
    entity = "" if row["위치_엔티티"] == "(없음)" else row["위치_엔티티"]
    pause_zones = None if row["pause_zones"] == "(키없음)" else zone_list(row["pause_zones"])
    coord = make_coordinator(zones=_zones(row["존_상태"]), location_entity=entity,
                             pause_zones=pause_zones, location=LOCATIONS[row["위치"]])
    if row["API결과"] == "실패":
        coord.api.fetch_data = AsyncMock(return_value=None)

    result = run(coord._async_update_data())

    assert coord.api.fetch_data.await_count == int(row["기대_API호출"])
    assert result["weather"]["TMP"] == int(row["기대_온도"])


# ── 동등분할: 옵션 화면 (실제 hass 필요) ─────────────────────────────────────
def _entry(location_entity, options=None):
    return MockConfigEntry(
        domain=DOMAIN, entry_id="pause_data_test", options=options or {},
        data={"api_key": "test_key", "location_entity": location_entity,
              "prefix": "test", "location_mode": "zone"})


@pytest.mark.parametrize(
    "row", table_params(read_csv("pause_zone_visibility.csv"), lambda r: r["분류"]))
async def test_pause_zones_option_visibility(hass, row):
    """
    [Given] 위치 엔티티 도메인이 표의 값 (이전에 저장된 pause_zones 가 남아 있을 수도 있음)
    [When]  옵션 플로우를 연다
    [Then]  모바일 기기(device_tracker/person)에만 pause_zones 항목이 보인다
    """
    stored = {} if row["저장된_pause_zones"] == "(없음)" else {"pause_zones": zone_list(row["저장된_pause_zones"])}
    location = "" if row["위치_엔티티"] == "(없음)" else row["위치_엔티티"]
    entry = _entry(location, {"location_entity": location, **stored})
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    keys = [str(key) for key in result["data_schema"].schema]
    assert ("pause_zones" in keys) is yes(row["기대_노출"])


@pytest.mark.parametrize(
    "row", table_params(read_csv("pause_zone_options.csv"), lambda r: r["분류"]))
async def test_saving_pause_zones_option_preserves_other_options(hass, row):
    """
    [Given] 기존 pause_zones 가 표의 값(키가 없을 수도 있음)이고 다른 옵션(만료일 등)이 설정된 기기
    [When]  옵션 화면에서 pause_zones 를 표의 값으로 제출
    [Then]  pause_zones 는 기대 저장값이 되고 다른 옵션은 그대로 보존된다
    """
    hass.states.async_set("zone.home", "0", {"latitude": HOME[0], "longitude": HOME[1],
                                             "radius": 100, "friendly_name": "우리집"})
    options = {"location_entity": "device_tracker.phone",
               "expire_date": "2026-12-31", "apply_date": "2025-01-01"}
    if row["기존_pause_zones"] != "(키없음)":
        options["pause_zones"] = zone_list(row["기존_pause_zones"])
    entry = _entry("device_tracker.phone", options)
    entry.add_to_hass(hass)

    flow = await hass.config_entries.options.async_init(entry.entry_id)
    saved = await hass.config_entries.options.async_configure(
        flow["flow_id"],
        user_input={"location_entity": "device_tracker.phone",
                    "expire_date": "2026-12-31", "apply_date": "2025-01-01",
                    "pause_zones": zone_list(row["제출_pause_zones"])})

    assert saved["type"] == "create_entry"
    assert saved["data"]["pause_zones"] == zone_list(row["기대_저장값"])
    assert saved["data"]["expire_date"] == "2026-12-31"
    assert saved["data"]["apply_date"] == "2025-01-01"
