"""중기예보 조회 키워드: 발표 회차(tmFc) 요청, 빈 응답 재시도, 미신청 처리를 호출 순서대로 확인한다."""
from datetime import datetime

from testkit.aio import run
from testkit.factories import kst
from testkit.forecasts import make_api
from testkit.keywords import keyword

LIB = "midterm (중기예보 조회)"
EMPTY = {"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": []}}}}
VALID_TA = {"response": {"body": {"items": {"item": [{"taMax3": "25", "taMin3": "15"}]}}}}
VALID_LAND = {"response": {"body": {"items": {"item": [{"wf3Am": "맑음", "wf3Pm": "흐림"}]}}}}
UNSUBSCRIBED = {"response": {"header": {"resultCode": "30"}}}


@keyword("중기예보를_준비한다", library=LIB)
def prepare(world, 월, 일, 시, 분, 응답="정상"):
    """2026년 월/일 시:분 시점의 중기예보 조회를 준비하고 가짜 응답을 정한다: 정상 / 빈응답 / 미신청 / 두번빈응답후정상."""
    world.api = make_api()
    world.now = kst(2026, 월, 일, 시, 분)
    world.requests = []

    async def fake_fetch(url, params, **_kwargs):
        world.requests.append((url, params.get("tmFc", "")))
        count = len(world.requests)
        if 응답 == "빈응답" or (응답 == "두번빈응답후정상" and count <= 2):
            return EMPTY
        if 응답 == "미신청":
            return UNSUBSCRIBED
        return VALID_TA if "getMidTa" in url else VALID_LAND

    world.api._fetch = fake_fetch


@keyword("중기예보를_조회한다", library=LIB)
def query(world):
    """중기예보(기온 + 육상)를 조회하고 (기온 응답, 육상 응답, 발표 시각) 결과를 저장한다."""
    world.result = run(world.api._get_mid_term(world.now, "11B10101", "11B00000"))


@keyword("발표_회차_시각을_확인한다", library=LIB)
def assert_base_hour(world, 시):
    """현재 시각 기준 중기예보 발표 회차의 시(06 또는 18)가 기대와 같은지 확인한다."""
    assert world.api._get_mid_base_dt(world.now).hour == 시


@keyword("결과는_세_값이다", library=LIB)
def assert_three_values(world):
    """결과가 (기온 응답, 육상 응답, 시간대 정보가 있는 발표 시각) 세 값인지 확인한다."""
    assert isinstance(world.result, tuple) and len(world.result) == 3
    announced = world.result[2]
    assert isinstance(announced, datetime) and announced.tzinfo is not None


@keyword("호출_횟수를_확인한다", library=LIB)
def assert_request_count(world, 횟수):
    """기온·육상 API 호출이 모두 합쳐 기대 횟수만큼 나갔는지 확인한다."""
    assert len(world.requests) == 횟수


@keyword("첫_두_호출의_발표시각은_계산한_회차와_같다", library=LIB)
def assert_first_requests_use_base(world):
    """처음 두 호출(기온, 육상)이 현재 시각 기준 발표 회차(YYYYMMDDHHMM)로 요청됐는지 확인한다."""
    expected = world.api._get_mid_base_dt(world.now).strftime("%Y%m%d%H%M")
    assert [tm for _, tm in world.requests[:2]] == [expected, expected]


@keyword("재시도_발표시각은_다음으로_끝난다", library=LIB)
def assert_retry_base_suffix(world, 끝자리):
    """첫 두 호출 이후(재시도) 요청 중 하나 이상의 발표시각이 지정한 끝자리(예: 1800, 0600)로 끝나는지 확인한다."""
    assert any(tm.endswith(끝자리) for _, tm in world.requests[2:])


@keyword("정상_값을_돌려준다", library=LIB)
def assert_values_present(world):
    """기온과 육상 응답이 모두 값이 있는(None 이 아닌) 상태로 돌아왔는지 확인한다."""
    assert world.result[0] is not None and world.result[1] is not None


@keyword("발표_시각은_돌려준다", library=LIB)
def assert_announced_returned(world):
    """실패해도 발표 시각(세 번째 값)은 항상 돌려주는지 확인한다."""
    assert world.result[2] is not None


@keyword("미신청_신호를_돌려준다", library=LIB)
def assert_unsubscribed_signal(world):
    """첫째 값이 UNSUBSCRIBED 이고 둘째 값이 None 인지 확인한다."""
    assert world.result[0] == "UNSUBSCRIBED" and world.result[1] is None
