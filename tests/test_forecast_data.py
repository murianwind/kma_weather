"""데이터 드리븐: 예보 병합 — 표(tests/data/*.csv|yaml)만 고치면 케이스가 늘어난다.

  mid_base_time.csv             중기예보 발표 회차(tmFc) 결정 — 06:30/18:30 경계
  forecast_boundary_times.csv   하루 24시간 갱신 + 회차 전환 전후에 D+3/D+4 가 비지 않는가
  rain_start_time.csv           강수 시작 시각 문구
  sky_pty_condition.csv         하늘상태 × 강수형태 → 날씨 상태
  current_slot_selection.csv    현재 날씨가 어느 단기예보 슬롯에서 오는가
  sensor_passthrough.yaml       센서가 원본값의 형(int/float/str)을 유지하는가
  condition_sync_entities.csv   현재 날씨가 센서·날씨 엔티티에 같은 값으로 나타나는가
  short_base_time.csv           단기예보 발표 회차(base_date/base_time) 결정 — 발표 +10분 경계
  short_term_response.csv       단기예보 호출 결과 → 반환값 / 승인 표시
  mid_condition_text.csv        중기예보 날씨 문구 → 표준 한글 날씨 상태 (포함 단어 우선순위)
"""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kma_weather.api_kma import KMAWeatherAPI, KOR_TO_CONDITION
from custom_components.kma_weather.const import DOMAIN
from custom_components.kma_weather.coordinator import KMAWeatherUpdateCoordinator
from custom_components.kma_weather.sensor import KMACustomSensor
from testkit.aio import run
from testkit.factories import KST, kst
from testkit.forecasts import (
    daily_entry, make_api, mid_response, short_four_slots, twice_daily_entry)
from testkit.tables import read_csv, read_yaml, table_params

NONE_TOKENS = {"(None)": None, "(빈칸)": "", "(없음)": None}


def token(value):
    return NONE_TOKENS.get(value, value)


# ── 중기예보 발표 회차 ───────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "row", table_params(read_csv("mid_base_time.csv"),
                        lambda r: f"{r['분류']}[{int(r['시']):02d}:{int(r['분']):02d}]"))
def test_mid_term_base_time(row):
    """
    [Given] 현재 시각 (회차 전환 06:30 / 18:30 의 전·후, 자정 전후)
    [When]  _get_mid_base_dt
    [Then]  발표 회차의 날짜(오늘/전날)와 시(06/18), 정각(분·초 0), 시간대 정보
    """
    now = datetime(2026, 4, 11, int(row["시"]), int(row["분"]), tzinfo=KST)

    base = make_api()._get_mid_base_dt(now)

    assert (base.date() - now.date()).days == int(row["기대_날짜차이"])
    assert base.hour == int(row["기대_시"])
    assert (base.minute, base.second) == (0, 0) and base.tzinfo is not None


# ── 하루 24시간 + 회차 전환에서 D+3/D+4 가 비지 않는가 ────────────────────────
def assert_d3_d4_filled(result):
    for day in (3, 4):
        entry = daily_entry(result, day)
        assert entry["native_temperature"] is not None and entry["native_templow"] is not None
        for daytime in (True, False):
            assert twice_daily_entry(result, day, daytime)["native_temperature"] is not None


@pytest.mark.parametrize(
    "row", table_params(read_csv("forecast_boundary_times.csv"), lambda r: r["분류"]))
def test_d3_d4_never_empty_across_the_day_and_release_transitions(row):
    """
    [Given] 단기예보 4일치(09·12·15·18시 슬롯)와 중기예보(해당 시각 기준 최신 회차)
    [When]  그 시각에 _merge_all
    [Then]  D+3·D+4 기온이 모두 채워지고, D+4~D+6 최고기온은 중기 발표일 기준 며칠째인지에 맞다
    """
    api = make_api()
    now = datetime(2026, 4, 11, int(row["시"]), int(row["분"]), tzinfo=KST)
    tm_fc = api._get_mid_base_dt(now)
    assert (tm_fc.hour, (tm_fc.date() - now.date()).days) == (int(row["기대_발표시"]), int(row["기대_발표일차이"]))

    result = api._merge_all(now, short_four_slots(now, 4), mid_response(tm_fc), air_data={})

    assert_d3_d4_filled(result)
    for day in (4, 5, 6):
        assert daily_entry(result, day)["native_temperature"] == float(20 + day - int(row["기대_발표일차이"]))


# ── 강수 시작 시각 ───────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "row", table_params(read_csv("rain_start_time.csv"), lambda r: r["분류"]))
def test_rain_start_time_wording(row):
    """
    [Given] 단기예보 캐시에 한 슬롯만 강수형태(PTY)가 지정된 예보
    [When]  _merge_all (단기·중기 수신 실패 → 캐시 사용)
    [Then]  rain_start_time 이 '오늘/내일/모레(M/D) H시[ M분] 형태' 문구이거나 강수없음
    """
    base = datetime.strptime(row["기준일"], "%Y-%m-%d")
    hour, minute = map(int, row["현재시각"].split(":"))
    now = base.replace(hour=hour, minute=minute, tzinfo=KST)
    target = (now + timedelta(days=int(row["일차"]))).strftime("%Y%m%d")
    api = make_api()
    api._cache_forecast_map = {target: {row["슬롯"]: {
        "PTY": row["PTY"], "SKY": "4", "TMP": "20", "REH": "80", "WSD": "2.0", "POP": "80"}}}

    result = api._merge_all(now, None, None, {})

    assert result["weather"]["rain_start_time"] == row["기대"]


# ── 하늘상태 × 강수형태 ──────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "row", table_params(read_csv("sky_pty_condition.csv"),
                        lambda r: f"{r['분류']}[SKY={r['SKY']},PTY={r['PTY']}]"))
def test_sky_and_pty_to_korean_condition(row):
    """
    [Given] 하늘상태(SKY)와 강수형태(PTY) (명세 안/밖 값, None, 빈 문자열 포함)
    [When]  _get_sky_kor
    [Then]  PTY>0 이면 PTY 가 우선, 아니면 SKY, 명세 밖 값도 예외 없이 표의 상태를 돌려준다
    """
    assert KMAWeatherAPI(None, "key")._get_sky_kor(token(row["SKY"]), token(row["PTY"])) == row["기대_상태"]


# ── 한글 상태 → HA condition ─────────────────────────────────────────────────
KOR_ROWS = read_csv("kor_condition.csv")
HA_CONDITIONS = {"sunny", "partlycloudy", "cloudy", "rainy", "snowy", "lightning", "lightning-rainy",
                 "fog", "windy", "hail", "exceptional", "clear-night", "pouring", "snowy-rainy"}


@pytest.mark.parametrize("row", table_params(KOR_ROWS, lambda r: r["한글"]))
def test_korean_condition_to_ha_condition(row):
    """한글 날씨 상태가 HA 표준 condition 으로 변환된다 (모르는 값·빈 값·None 은 None)."""
    assert KMAWeatherAPI.kor_to_condition(token(row["한글"])) == token(row["기대_영문"])


def test_condition_table_matches_the_mapping_constant():
    """표가 매핑 상수와 정확히 일치하고, 모든 결과가 HA 가 아는 condition 이다 (필수 상태 포함)."""
    tabled = {row["한글"]: row["기대_영문"] for row in KOR_ROWS if row["기대_영문"] != "(없음)"}

    assert tabled == KOR_TO_CONDITION
    assert set(KOR_TO_CONDITION.values()) <= HA_CONDITIONS
    assert {"맑음", "구름많음", "흐림", "비", "비/눈", "소나기", "눈"} <= set(KOR_TO_CONDITION)


# ── 현재 슬롯 선택 ───────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "row", table_params(read_csv("current_slot_selection.csv"),
                        lambda r: f"{r['분류']}[{r['현재시각']}]"))
def test_current_weather_comes_from_the_right_slot(row):
    """
    [Given] 시각별 기온이 다른 단기예보 슬롯들
    [When]  현재 시각으로 _merge_all
    [Then]  현재 시각의 시 이상인 첫 슬롯(없으면 마지막 슬롯)의 기온이 현재 기온
    """
    items = []
    for pair in row["슬롯"].split(";"):
        slot, temp = pair.split(":")
        items += [{"fcstDate": "20250101", "fcstTime": slot, "category": c, "fcstValue": v}
                  for c, v in [("TMP", temp), ("SKY", "1"), ("PTY", "0"), ("REH", "50"), ("WSD", "2")]]
    hour, minute = map(int, row["현재시각"].split(":"))
    now = datetime(2025, 1, 1, hour, minute, tzinfo=KST)

    result = make_api()._merge_all(now, {"response": {"body": {"items": {"item": items}}}},
                                   (None, None), {}, address="Seoul")

    assert str(result["weather"]["TMP"]) == row["기대_기온"]


# ── 센서 값의 형 유지 ────────────────────────────────────────────────────────
@pytest.mark.parametrize("row", table_params(read_yaml("sensor_passthrough.yaml"), lambda r: r["분류"]))
def test_sensor_keeps_the_source_value_type(row):
    """
    [Given] 코디네이터에 정수/소수/문자열 원본값이 들어 있음
    [When]  센서의 native_value
    [Then]  값이 같고 형(int/float/str)도 바뀌지 않는다
    """
    coordinator = MagicMock()
    coordinator.data = {"weather": row.get("weather", {}), "air": row.get("air", {})}
    coordinator._daily_max_temp = row.get("daily", {}).get("max")
    coordinator._daily_min_temp = row.get("daily", {}).get("min")
    entry = MagicMock(entry_id="test_id", data={"prefix": "test"}, options={})

    value = KMACustomSensor(coordinator, row["센서"], "test", entry).native_value

    assert value == pytest.approx(row["기대"]) if row["기대_타입"] == "float" else value == row["기대"]
    assert type(value).__name__ == row["기대_타입"]


# ── 센서·날씨 엔티티 동기화 (실제 HA 등록) ────────────────────────────────────
@pytest.mark.parametrize("row", table_params(read_csv("condition_sync_entities.csv"), lambda r: r["분류"]))
async def test_condition_is_synced_between_sensor_and_weather_entity(hass, row):
    """
    [Given] 코디네이터가 현재 날씨(한글/영문)와 예보를 돌려주는 통합구성요소
    [When]  구성요소를 등록(setup)
    [Then]  센서 상태(한글)와 날씨 엔티티 예보(영문)가 코디네이터 데이터와 같다
    """
    now = kst(2026, 4, 11, 12)
    data = {
        "weather": {"TMP": 22.0, "REH": 50, "WSD": 2.0, "VEC_KOR": "남동",
                    "current_condition_kor": row["한글"], "current_condition": row["영문"],
                    "forecast_twice_daily": [{"datetime": now.isoformat(), "is_daytime": True,
                                              "condition": row["영문"], "native_temperature": 25, "_day_index": 0}],
                    "forecast_daily": [{"datetime": now.isoformat(), "condition": row["영문"],
                                        "native_temperature": 25, "_day_index": 0}],
                    "last_updated": now},
        "air": {}, "pollen": {"oak": "좋음", "pine": "좋음", "grass": "좋음", "worst": "좋음"},
    }
    entry = MockConfigEntry(domain=DOMAIN, data={"prefix": "sync", "api_key": "test"}, entry_id=f"sync_{row['id']}")
    real_init = KMAWeatherUpdateCoordinator.__init__

    def init_with_approved_apis(coord, hass_arg, entry_arg):  # 가짜 갱신에서는 API 승인 표시가 안 남으므로 주입
        real_init(coord, hass_arg, entry_arg)
        coord.api._approved_apis = {"short", "mid", "air", "warning", "pollen"}

    with patch.object(KMAWeatherUpdateCoordinator, "__init__", init_with_approved_apis), \
            patch.object(KMAWeatherUpdateCoordinator, "_async_update_data", new=AsyncMock(return_value=data)):
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert hass.states.get("sensor.sync_condition").state == row["한글"]
        response = await hass.services.async_call(
            "weather", "get_forecasts", {"type": "twice_daily"},
            target={"entity_id": "weather.sync_weather"}, blocking=True, return_response=True)
        assert response["weather.sync_weather"]["forecast"][0]["condition"] == row["영문"]


# ── 중기예보 날씨 문구 ───────────────────────────────────────────────────────
@pytest.mark.parametrize("row", table_params(read_csv("mid_condition_text.csv"), lambda r: f"{r['분류']}[{r['입력']}]"))
def test_translate_mid_condition_text(row):
    """
    [Given] 중기예보가 돌려준 날씨 문구 (표준 문구 / 단어 포함 / 알 수 없는 문구 / 없음)
    [When]  _translate_mid_condition_kor
    [Then]  표준 한글 날씨 상태 (둘 이상 포함하면 앞선 규칙)
    """
    api = make_api()

    assert api._translate_mid_condition_kor(token(row["입력"])) == row["기대"]


# ── 단기예보 발표 회차와 호출 결과 ───────────────────────────────────────────
def short_term_api(body):
    """_fetch 가 항상 body 를 돌려주는 API. 호출 인자는 api.sent 에 쌓인다."""
    api = make_api()
    api.nx, api.ny = 60, 127
    api.sent = []

    async def fetch(url, params, *args, **kwargs):
        api.sent.append(params)
        return body

    api._fetch = fetch
    return api


@pytest.mark.parametrize("row", table_params(read_csv("short_base_time.csv"), lambda r: r["분류"]))
def test_short_term_base_time(row):
    """
    [Given] 현재 시각 (회차 전환 직전·직후, 자정 전후)
    [When]  _get_short_term
    [Then]  요청의 base_date / base_time 이 표의 회차이다 (발표 10분 뒤부터 새 회차)
    """
    api = short_term_api({})
    hour, minute = map(int, row["현재"].split(":"))

    run(api._get_short_term(kst(2026, 4, 11, hour, minute)))

    expected_date = (datetime(2026, 4, 11) + timedelta(days=int(row["기대_날짜"]))).strftime("%Y%m%d")
    assert (api.sent[0]["base_date"], api.sent[0]["base_time"]) == (expected_date, row["기대_시각"])
    assert (api.sent[0]["nx"], api.sent[0]["ny"]) == (60, 127)


RESPONSE_BODIES = {
    "정상": {"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": [{"category": "TMP"}]}}}},
    "항목없음": {"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": []}}}},
    "(None)": None,
    "단건dict": {"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": {"category": "TMP"}}}}},
    "items빈문자열": {"response": {"header": {"resultCode": "00"}, "body": {"items": ""}}},
}


def short_term_body(token):
    if token in RESPONSE_BODIES:
        return RESPONSE_BODIES[token]
    kind, value = token.split(":")
    return {"response": {"header": {"resultCode": value}}} if kind == "code" else {"_http_error": value}


@pytest.mark.parametrize("row", table_params(read_csv("short_term_response.csv"), lambda r: r["분류"]))
def test_short_term_response_handling(row):
    """
    [Given] 단기예보 호출이 정상 / 항목 없음 / 응답 없음 / 미신청 / HTTP 오류를 돌려줌
    [When]  _get_short_term
    [Then]  반환값과 '단기예보 승인' 표시가 표와 같다
    """
    body = short_term_body(row["응답"])
    api = short_term_api(body)

    result = run(api._get_short_term(kst(2026, 4, 11, 10, 30)))

    expected = {"응답 그대로": body, "(None)": None, "UNSUBSCRIBED": "UNSUBSCRIBED"}[row["기대_반환"]]
    assert result == expected
    assert ("short" in api._approved_apis) == (row["기대_승인"] == "예")
