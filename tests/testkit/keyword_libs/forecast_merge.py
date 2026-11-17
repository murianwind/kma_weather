"""예보 병합 키워드: 단기·중기 수신이 성공/실패를 오갈 때 캐시로 D+3/D+4 가 유지되는지 확인한다."""
from testkit.factories import kst
from testkit.forecasts import (
    daily_entry, make_api, mid_response, short_four_slots, twice_daily_entry)
from testkit.keywords import keyword

LIB = "forecast_merge (예보 병합·캐시)"


@keyword("예보_병합을_준비한다", library=LIB)
def prepare(world, 시, 분):
    """2026-04-11 시:분 시점에 같은 API 객체(캐시 유지)로 예보를 병합할 준비를 한다."""
    world.api = make_api()
    world.now = kst(2026, 4, 11, 시, 분)


@keyword("예보를_병합한다", library=LIB)
def merge(world, 단기="정상", 중기="정상"):
    """단기예보(정상 / 5일치 / 실패)와 중기예보(정상 / 5일부터 / 실패)로 병합한다. 실패는 응답 없음(None)이다."""
    now = world.now
    tm_fc = world.api._get_mid_base_dt(now)
    short = {"정상": lambda: short_four_slots(now, 4), "5일치": lambda: short_four_slots(now, 5), "실패": lambda: None}[단기]()
    mid = {"정상": lambda: mid_response(tm_fc), "5일부터": lambda: mid_response(tm_fc, start_idx=5), "실패": lambda: None}[중기]()
    world.result = world.api._merge_all(now, short, mid, air_data={})


@keyword("D3_D4_예보가_모두_채워져_있다", library=LIB)
def assert_d3_d4_filled(world):
    """D+3·D+4 의 일 예보와 주간/야간 예보 기온이 모두 비어 있지 않은지 확인한다."""
    for day in (3, 4):
        entry = daily_entry(world.result, day)
        assert entry["native_temperature"] is not None and entry["native_templow"] is not None
        for daytime in (True, False):
            assert twice_daily_entry(world.result, day, daytime)["native_temperature"] is not None


@keyword("일_예보_항목은_열_개이고_기온은_비어_있다", library=LIB)
def assert_ten_empty_days(world):
    """일 예보 항목은 10개로 유지되지만 받은 데이터가 없어 모든 날의 최고기온이 비어 있는지 확인한다."""
    daily = world.result["weather"]["forecast_daily"]
    assert len(daily) == 10 and all(entry["native_temperature"] is None for entry in daily)
