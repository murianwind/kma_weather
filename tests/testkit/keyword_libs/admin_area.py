"""행정구역 지역코드 키워드: 꽃가루와 자외선지수가 같은 지역코드 캐시를 공유하는 흐름."""
import logging
from unittest.mock import AsyncMock, MagicMock, patch

from testkit.aio import run
from testkit.factories import make_coordinator
from testkit.keywords import keyword

LIB = "admin_area (꽃가루·자외선 지역코드)"


@keyword("코디네이터를_준비한다", library=LIB)
def prepare(world):
    """지역코드표를 실제 파일에서 읽을 수 있는 코디네이터를 준비한다."""
    world.coord = make_coordinator(location_entity="")
    world.coord.hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))


@keyword("꽃가루_지역을_조회한다", library=LIB)
def find_pollen(world, 위도, 경도):
    """꽃가루용 지역코드를 조회하고 결과를 저장한다."""
    world.pollen = run(world.coord.find_pollen_area(위도, 경도))


@keyword("자외선_지역을_조회한다", library=LIB)
def find_uv(world, 위도, 경도):
    """자외선지수용 지역코드를 조회하고 결과를 저장한다."""
    world.uv = run(world.coord.find_uv_area(위도, 경도))


@keyword("지역파일을_더_읽을_수_없다", library=LIB)
def file_gone(world):
    """이미 읽어 둔 지역코드표가 사라진 상황을 만든다 (이후 읽기도 성공하지 못함)."""
    world.coord._admin_area_data = None
    world.coord._load_admin_area_map = MagicMock()


@keyword("지역파일이_없는_채로_불러온다", library=LIB)
def load_missing_file(world):
    """지역코드표 파일(admin_area_map.json)이 없는 상태에서 로드를 시도한다 (경고 로그를 world.logs 에 모은다)."""
    records = []
    handler = logging.Handler()
    handler.emit = records.append
    logger = logging.getLogger("custom_components.kma_weather.coordinator")
    logger.addHandler(handler)
    try:
        with patch("builtins.open", side_effect=FileNotFoundError):
            world.coord._load_admin_area_map()
    finally:
        logger.removeHandler(handler)
    world.logs = records


@keyword("지역코드표가_비어_있다", library=LIB)
def assert_table_empty(world):
    """로드에 실패해 지역코드표가 비어 있고(None), 로드 실패 경고가 한 번 남았는지 확인한다."""
    assert world.coord._admin_area_data is None
    warnings = [r for r in world.logs if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "행정구역코드 룩업 로드 실패" in warnings[0].getMessage()


@keyword("꽃가루_지역을_확인한다", library=LIB)
def assert_pollen(world, 코드, 이름):
    """꽃가루용 조회 결과(코드, 이름)가 기대와 같은지 확인한다. 코드가 빈 문자열이면 조회 실패를 뜻한다."""
    assert world.pollen == (코드, 이름)


@keyword("자외선_지역을_확인한다", library=LIB)
def assert_uv(world, 코드, 이름):
    """자외선지수용 조회 결과(코드, 이름)가 기대와 같은지 확인한다."""
    assert world.uv == (코드, 이름)


@keyword("캐시된_지역코드를_확인한다", library=LIB)
def assert_cached_code(world, 값):
    """공용 캐시에 들어 있는 지역코드가 기대와 같은지 확인한다. 값이 null 이면 캐시가 비어 있어야 한다."""
    assert world.coord._admin_cached_area_no == 값
