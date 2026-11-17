"""현재 예상 강수량 센서 키워드: 시간이 지나며 갱신될 때 상태값과 시간대별 속성의 변화를 확인한다."""
from datetime import timedelta

from testkit.factories import kst, make_api, short_forecast
from testkit.keywords import keyword

LIB = "precip (예상 강수량)"
TODAY = kst(2026, 10, 19, 0).date()


@keyword("예보를_준비한다", library=LIB)
def prepare_forecast(world, 강수량=None, 눈=None, 첫슬롯시=0, 일수=2):
    """단기예보를 준비한다. 강수량은 {시: 원본값}, 눈은 {시: 적설 원본값}, 첫슬롯시는 발표본의 첫 시각."""
    눈 = 눈 or {}
    world.forecast = short_forecast(
        kst(2026, 10, 19, 0), days=일수, first_slot_hour=첫슬롯시,
        pcp_by_hour={**(강수량 or {}), **눈},
        pty_by_hour={hour: "3" for hour in 눈})
    world.api = make_api()


@keyword("시각을_맞추고_갱신한다", library=LIB)
def refresh_at(world, 시, 분, 일=19):
    """가상 시각(2026-10 {일}일 시:분)으로 갱신(_merge_all)을 실행하고 결과를 저장한다."""
    world.now = kst(2026, 10, 일, 시, 분)
    world.result = world.api._merge_all(world.now, world.forecast, None, {})["weather"]


@keyword("한시간이_지나고_갱신한다", library=LIB)
def refresh_next_hour(world):
    """직전 갱신으로부터 1시간 뒤 시각으로 다시 갱신한다."""
    world.now += timedelta(hours=1)
    world.result = world.api._merge_all(world.now, world.forecast, None, {})["weather"]


@keyword("상태값을_확인한다", library=LIB)
def assert_state(world, 값):
    """센서 상태값(precip_amount)이 기대와 같은지 확인한다."""
    assert world.result["precip_amount"] == 값


@keyword("속성값을_확인한다", library=LIB)
def assert_attribute(world, 키, 값):
    """시간대별 속성(예: '15시')의 값이 기대와 같은지 확인한다. 지난 시간은 '-'."""
    assert world.result["hourly_precipitation_mm"][키] == 값


@keyword("속성_키가_하루_전체인지_확인한다", library=LIB)
def assert_keys_whole_day(world):
    """속성 키가 항상 '00시'~'23시' 24개이고 시간 순서인지 확인한다."""
    keys = list(world.result["hourly_precipitation_mm"])
    assert keys == [f"{h:02d}시" for h in range(24)]
