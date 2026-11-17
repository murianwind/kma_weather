"""단기/중기 예보 응답 생성기 (예보 병합 테스트들이 함께 쓴다).

단기예보: {"response": {"body": {"items": {"item": [{fcstDate, fcstTime, category, fcstValue}, ...]}}}}
중기예보: (기온 응답, 육상 응답, 발표 시각) 3개짜리 튜플
"""
from datetime import timedelta

from testkit.factories import make_api as _make_api


def make_api():
    """격자·좌표가 지정된 API (서울 시청 기준)."""
    api = _make_api()
    api.lat, api.lon, api.nx, api.ny = 37.56, 126.98, 60, 127
    return api


def short_response(base, *, days, slots, values):
    """base 날짜부터 days 일치, slots(시 목록)마다 values(날짜 번호, 시) 의 카테고리 값을 담은 단기예보 응답."""
    items = []
    for day_no in range(days):
        date_str = (base + timedelta(days=day_no)).strftime("%Y%m%d")
        for hour in slots:
            for category, value in values(day_no, hour).items():
                items.append({"fcstDate": date_str, "fcstTime": f"{hour:02d}00",
                              "category": category, "fcstValue": str(value)})
    return {"response": {"body": {"items": {"item": items}}}}


def short_three_hourly(base, days=4):
    """06~21시 3시간 간격 슬롯, 기온은 날짜·시각에 따라 달라짐 (D+n 기온 비교용)."""
    return short_response(
        base, days=days, slots=range(6, 22, 3),
        values=lambda d, h: {"TMP": 10 + d * 2 + h // 3, "SKY": "3" if h == 15 else "1",
                             "PTY": 0, "REH": 50, "WSD": 2.0, "POP": 10})


def short_four_slots(base, days=4):
    """09·12·15·18시 4개 슬롯 (단기 발표 경계 점검용)."""
    temps = {9: 10, 12: 12, 15: 15, 18: 13}
    return short_response(
        base, days=days, slots=temps,
        values=lambda d, h: {"TMP": temps[h] + d * 2, "SKY": "1", "PTY": 0,
                             "REH": 50, "WSD": 2.0, "POP": 10})


def short_all_hours(base, days=4, pop_by_hour=None):
    """매시 슬롯, 기온 20·맑음·강수 없음, 강수확률만 시각별로 지정 (강수확률 점검용)."""
    pop_by_hour = pop_by_hour or {}
    return short_response(
        base, days=days, slots=range(24),
        values=lambda d, h: {"TMP": 20, "SKY": 1, "PTY": 0, "POP": pop_by_hour.get(h, 0)})


def wrap_mid(item):
    return {"response": {"body": {"items": {"item": [item]}}}}


def mid_response(tm_fc, start_idx=3, end_idx=10, rn_am=None, rn_pm=None):
    """중기예보 (기온, 육상, 발표시각). 기온은 최고 20+n / 최저 5+n, 날씨는 n 이 짝수면 맑음·홀수면 흐림.

    rn_am / rn_pm 을 주면 모든 n 에 같은 오전/오후 강수확률(rnSt{n}Am/Pm)을 넣는다.
    """
    ta, land = {}, {}
    for n in range(start_idx, end_idx + 1):
        ta[f"taMax{n}"], ta[f"taMin{n}"] = str(20 + n), str(5 + n)
        weather = "맑음" if n % 2 == 0 else "흐림"
        land[f"wf{n}Am"], land[f"wf{n}Pm"] = weather, weather
        if rn_am is not None:
            land[f"rnSt{n}Am"] = str(rn_am)
        if rn_pm is not None:
            land[f"rnSt{n}Pm"] = str(rn_pm)
    return wrap_mid(ta), wrap_mid(land), tm_fc


def empty_mid(tm_fc):
    """모든 항목이 비어 있는 중기예보 응답 (10일 예보 항목 수 점검용)."""
    return wrap_mid({}), wrap_mid({}), tm_fc


def daily_entry(result, day_index):
    """병합 결과에서 forecast_daily 의 해당 날짜 항목."""
    return next(e for e in result["weather"]["forecast_daily"] if e["_day_index"] == day_index)


def twice_daily_entry(result, day_index, daytime):
    """병합 결과에서 forecast_twice_daily 의 해당 날짜 주간/야간 항목."""
    return next(e for e in result["weather"]["forecast_twice_daily"]
                if e["_day_index"] == day_index and e["is_daytime"] is daytime)
