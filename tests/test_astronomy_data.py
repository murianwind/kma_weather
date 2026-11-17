"""데이터 드리븐: 천문 계산 — 표(tests/data/*.csv)만 고치면 케이스가 늘어난다.

  moon_phase_name.csv      달 위상각 → 8단계 이름 (45° 경계)
  sun_time_prefix.csv      지금 이후 천문 시각의 "오늘/내일" 접두어
  observation_condition.csv 날씨·주야간·달·풍속 → 관측 조건 등급과 판단사유
태양·달 위치는 skyfield 와 de440s.bsp 로 실제 계산한다 (없으면 해당 테스트는 건너뜀).
"""
from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from custom_components.kma_weather.coordinator import KMAWeatherUpdateCoordinator
from testkit.astro import SF_EPH, SF_TS, needs_skyfield
from testkit.tables import read_csv, table_params

TZ = ZoneInfo("Asia/Seoul")
LAT, LON = 37.608025, 127.094222
DAY = (2026, 4, 21)
NONE = "(None)"
CONDITION_KOR = {"sunny": "맑음", "partlycloudy": "구름많음", "cloudy": "흐림", "rainy": "비",
                 "pouring": "소나기", "snowy": "눈", "snowy-rainy": "비/눈"}


def make_coord():
    coord = MagicMock()
    coord.api.tz = TZ
    coord._sun_times = {}
    coord._sf_ts, coord._sf_eph = SF_TS, SF_EPH
    coord._OBS_ORDER = KMAWeatherUpdateCoordinator._OBS_ORDER
    coord._moon_phase_name = staticmethod(KMAWeatherUpdateCoordinator._moon_phase_name)
    return coord


# ── 달 위상 이름 ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("row", table_params(read_csv("moon_phase_name.csv"), lambda r: f"{r['분류']}[{r['위상각']}°]"))
def test_moon_phase_name(row):
    """
    [Given] 달 위상각 (단계 경계 직전/직후 포함)
    [When]  _moon_phase_name
    [Then]  45° 간격 8단계 이름
    """
    assert KMAWeatherUpdateCoordinator._moon_phase_name(float(row["위상각"])) == row["기대"]


# ── 오늘/내일 접두어와 형식 ──────────────────────────────────────────────────
TIME_KEYS = ("dawn", "sunrise", "sunset", "dusk", "astro_dawn", "astro_dusk")
MOON_PHASES = {"삭", "초승달", "상현달", "준상현달", "보름달", "준하현달", "하현달", "그믐달"}


@needs_skyfield
@pytest.mark.parametrize("row", table_params(read_csv("sun_time_prefix.csv"), lambda r: f"{r['분류']}[{r['현재_시']}시]"))
def test_sun_time_prefix_and_format(row):
    """
    [Given] 2026-04-21 의 한 시각
    [When]  _calc_sun_times
    [Then]  이미 지난 시각은 "내일", 아직 오지 않은 시각은 "오늘" 접두어가 붙고 "HH:MM" 형식이며,
            달 위상은 8단계 이름, 달 조명율은 0~100 정수이다
    """
    now = datetime(*DAY, int(row["현재_시"]), 0, tzinfo=TZ)

    result = KMAWeatherUpdateCoordinator._calc_sun_times(make_coord(), LAT, LON, now)

    for key in TIME_KEYS:
        prefix, clock = result[key].split(" ")
        hour, minute = clock.split(":")
        assert prefix == row[f"기대_{key}"], f"{key}: {result[key]}"
        assert 0 <= int(hour) <= 23 and 0 <= int(minute) <= 59
    assert result["moon_phase"] in MOON_PHASES
    assert isinstance(result["moon_illumination"], int) and 0 <= result["moon_illumination"] <= 100


# ── 관측 조건 ────────────────────────────────────────────────────────────────
@needs_skyfield
@pytest.mark.parametrize("row", table_params(
    read_csv("observation_condition.csv"),
    lambda r: f"{r['분류']}[{r['시각']}시/{r['날씨']}/달{r['달조명율']}/풍속{r['풍속']}]"))
def test_observation_condition(row):
    """
    [Given] 날씨 · 시각 · 달 조명율 · 풍속
    [When]  _eval_observation
    [Then]  가장 나쁜 항목이 최종 등급이고 그 항목들이 판단사유이며, 속성에 입력값이 그대로 표시된다
    """
    illum = None if row["달조명율"] == NONE else int(row["달조명율"])
    wind = None if row["풍속"] == NONE else (float(row["풍속"]) if row["풍속"] != "abc" else "abc")
    weather = {"current_condition": row["날씨"], "current_condition_kor": CONDITION_KOR[row["날씨"]],
               "moon_illumination": illum, "moon_phase": "보름달", "WSD": wind}
    now = datetime(*DAY, int(row["시각"]), 0, tzinfo=TZ)

    condition, attrs = KMAWeatherUpdateCoordinator._eval_observation(make_coord(), weather, now, LAT, LON)

    assert condition == row["기대_판정"]
    assert attrs["판단사유"] == row["기대_사유"]
    assert attrs["주야간"] == row["기대_주야간"]
    assert attrs["날씨"] == CONDITION_KOR[row["날씨"]]
    assert attrs["달_조명율"] == ("-" if illum is None else f"{illum}%")
    assert attrs["풍속"] == ("-" if wind is None else f"{wind} m/s")
    assert attrs["달_위상"] == "보름달"
    assert set(attrs) == {"풍속", "달_조명율", "달_고도", "은하수_고도", "날씨", "주야간", "달_위상", "판단사유"}
