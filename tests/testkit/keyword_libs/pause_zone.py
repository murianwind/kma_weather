"""pause_zones(일시정지 존) 키워드: 이탈 감지 → 5분 대기 → 판정 흐름을 시간 순으로 조립한다."""
from datetime import timedelta

from testkit.aio import run
from testkit.factories import FakeTimer, kst, make_coordinator, meters_north, zone_state
from testkit.keywords import keyword

LIB = "pause_zone (일시정지 존)"
HOME = (37.56, 126.98)
PLACES = {"집": HOME, "집 밖": (meters_north(HOME[0], 5000), HOME[1])}
ZONES = {"집": "zone.home"}


@keyword("기기를_등록한다", library=LIB)
def register_device(world, 존=("집",)):
    """모바일 기기(device_tracker)를 등록하고 지정한 존을 pause_zones 로 설정한다. 처음엔 집 안, 시각은 10:00."""
    zones = {ZONES[name]: zone_state(ZONES[name], *HOME, radius=100) for name in 존}
    world.coord = make_coordinator(zones=zones, pause_zones=list(zones), location=HOME)
    world.now = kst(2026, 10, 19, 10, 0)
    world.coord._now = lambda: world.now
    world.timer = FakeTimer(lambda: world.now).install()
    world.setdefault("cleanups", []).append(world.timer.uninstall)
    world.coord._in_pause_zone_state = True


@keyword("현재시각을_설정한다", library=LIB)
def set_clock(world, 시, 분):
    """가상 시계를 오늘(2026-10-19) 시:분으로 맞춘다."""
    world.now = kst(2026, 10, 19, 시, 분)


@keyword("위치를_이동한다", library=LIB)
def move(world, 장소):
    """기기의 위치를 '집' 또는 '집 밖'으로 옮기고 위치 변화 이벤트를 발생시킨다."""
    world.coord._resolve_location.return_value = PLACES[장소]
    world.coord._handle_location_change(None)


@keyword("시간이_흐른다", library=LIB)
def advance(world, 분):
    """가상 시계를 분 단위로 진행하고, 대기 시간이 끝난 예약이 있으면 실행한다."""
    world.now += timedelta(minutes=분)
    pending = world.timer.pending
    if pending and world.now >= pending["due"]:
        world.timer.pending = None
        run(pending["callback"](world.now))


@keyword("정기업데이트가_실행된다", library=LIB)
def scheduled_update(world, 결과="성공"):
    """매시 :15 정기 업데이트를 실행한다. 결과가 '실패'이면 API 가 빈 응답을 돌려준다."""
    if 결과 == "실패":
        world.coord.api.fetch_data.return_value = None
    run(world.coord._async_update_data())
    if 결과 == "실패":
        world.coord.api.fetch_data.return_value = {
            "weather": {"TMP": 25}, "air": {}, "pollen": None, "raw_forecast": {}}


@keyword("API_호출횟수를_확인한다", library=LIB)
def assert_api_calls(world, 횟수):
    """지금까지 API(fetch_data)가 호출된 횟수가 기대와 같은지 확인한다."""
    assert world.coord.api.fetch_data.await_count == 횟수


@keyword("예약된_대기가_있는지_확인한다", library=LIB)
def assert_pending(world, 있음):
    """존 이탈 후 5분 대기 예약이 남아 있는지(있음/없음) 확인한다."""
    assert (world.timer.pending is not None) == 있음


@keyword("존_안_상태를_확인한다", library=LIB)
def assert_in_zone(world, 안):
    """코디네이터가 기억하는 '존 안/밖' 상태가 기대와 같은지 확인한다."""
    assert world.coord._in_pause_zone_state == 안
