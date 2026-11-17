"""데이터 드리븐: 기상 값 변환 함수 — 표(tests/data_driven/cases/*.csv)만 고치면 케이스가 늘어난다.

  apparent_temp.csv  체감온도 (겨울 Wind Chill / 여름 기상청 공식 / 그 외)
  air_grade.csv      PM10·PM2.5·오존 농도 → 등급
  vec_kor.csv        풍향 각도 → 8방위
  wgs84_to_tm.csv    위·경도 → TM 좌표(EPSG:5181), PROJ 기준값
"""
import pytest

from testkit.forecasts import make_api
from testkit.tables import number_or_text, read_csv, table_params

NONE_TOKENS = {"(None)": None, "(빈칸)": "", "(없음)": None}


def token(value):
    return NONE_TOKENS.get(value, value)


def maybe_number(value):
    """숫자로 읽히면 float, (None) 등은 None, 그 밖의 문자열은 그대로."""
    value = token(value)
    return value if value is None else number_or_text(value)


@pytest.mark.parametrize("row", table_params(read_csv("apparent_temp.csv"), lambda r: r["분류"]))
def test_apparent_temperature(row):
    """
    [Given] 기온 · 습도 · 풍속(m/s)
    [When]  _calculate_apparent_temp
    [Then]  겨울이면 Wind Chill, 여름이면 기상청 공식, 그 외는 기온 그대로
    """
    api = make_api()

    result = api._calculate_apparent_temp(
        maybe_number(row["기온"]), maybe_number(row["습도"]), maybe_number(row["풍속_ms"]))

    expected = maybe_number(row["기대"])
    if isinstance(expected, float):
        assert result == pytest.approx(expected, abs=0.05)
    else:
        assert result == expected


@pytest.mark.parametrize("row", table_params(read_csv("air_grade.csv"), lambda r: f"{r['분류']}[{r['값']}]"))
def test_air_grade(row):
    """
    [Given] 항목(pm10/pm25/o3)과 농도
    [When]  _get_air_grade
    [Then]  등급 상한 값까지는 그 등급, 바로 위는 다음 등급, 값이 없으면 '정보없음'
    """
    assert make_api()._get_air_grade(maybe_number(row["값"]), row["항목"]) == row["기대"]


@pytest.mark.parametrize("row", table_params(read_csv("vec_kor.csv"), lambda r: f"{r['분류']}[{r['입력']}]"))
def test_wind_direction_name(row):
    """
    [Given] 풍향 각도 (8방위 경계 직전·직후 포함)
    [When]  _get_vec_kor
    [Then]  45° 간격 8방위 이름, 각도가 없거나 숫자가 아니면 None
    """
    assert make_api()._get_vec_kor(token(row["입력"])) == token(row["기대"])


@pytest.mark.parametrize("row", table_params(read_csv("wgs84_to_tm.csv"), lambda r: r["분류"]))
def test_wgs84_to_tm_matches_epsg_5181(row):
    """
    [Given] 위·경도
    [When]  _wgs84_to_tm
    [Then]  PROJ 가 계산한 EPSG:5181 좌표와 0.5 m 이내로 같다
    """
    x, y = make_api()._wgs84_to_tm(float(row["위도"]), float(row["경도"]))

    assert (x, y) == (pytest.approx(float(row["기대_x"]), abs=0.5), pytest.approx(float(row["기대_y"]), abs=0.5))
