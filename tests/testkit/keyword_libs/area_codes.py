"""구역코드 키워드: 좌표 → (격자 nx, ny, 중기예보 기온/육상 구역, 특보 구역) 결정과 2km 캐시."""
import pytest

from custom_components.kma_weather import coordinator as coordinator_module
from testkit.factories import make_coordinator
from testkit.keywords import keyword

LIB = "area_codes (구역코드 결정·캐시)"


@keyword("구역코드_코디네이터를_준비한다", library=LIB)
def prepare(world):
    """구역코드 표를 읽어 두고, 구역코드를 결정할 코디네이터를 준비한다."""
    coordinator_module._load_area_data()
    world.coord = make_coordinator(location_entity="")
    world.codes = []


@keyword("구역코드를_결정한다", library=LIB)
def resolve(world, 위도, 경도):
    """좌표로 구역코드를 결정하고 결과를 차례대로 저장한다 (2km 안이면 캐시를 재사용)."""
    world.codes.append(world.coord._resolve_area_codes(위도, 경도))


@keyword("캐시가_비어_있다", library=LIB)
def assert_cache_empty(world):
    """아직 구역코드를 결정한 적이 없어 좌표·특보구역 캐시가 모두 비어 있는지 확인한다."""
    assert world.coord._cached_area_lat is None and world.coord._cached_warn_area_code is None


@keyword("구역코드는_다섯_개_값이다", library=LIB)
def assert_five_values(world):
    """가장 최근 결과가 (nx, ny, 기온구역, 육상구역, 특보구역) 다섯 개이고 격자는 정수, 나머지는 비어 있지 않은지 확인한다."""
    nx, ny, temp, land, warn = world.codes[-1]
    assert len(world.codes[-1]) == 5 and isinstance(nx, int) and isinstance(ny, int)
    assert temp and land and warn


@keyword("구역코드를_확인한다", library=LIB)
def assert_codes(world, 기온구역, 육상구역, 특보구역):
    """가장 최근 결과의 기온구역·육상구역·특보구역이 기대와 같은지 확인한다."""
    _nx, _ny, temp, land, warn = world.codes[-1]
    assert (temp, land, warn) == (기온구역, 육상구역, 특보구역)


@keyword("직전과_같은_결과다", library=LIB)
def assert_same_as_previous(world):
    """가장 최근 결과가 직전 결과와 완전히 같은지(캐시 재사용) 확인한다."""
    assert world.codes[-1] == world.codes[-2]


@keyword("직전과_특보구역이_다르다", library=LIB)
def assert_warn_area_changed(world):
    """가장 최근 결과의 특보구역이 직전 결과와 다른지(재계산) 확인한다."""
    assert world.codes[-1][4] != world.codes[-2][4]


@keyword("캐시된_좌표_위도를_확인한다", library=LIB)
def assert_cached_lat(world, 위도):
    """캐시에 기억된 기준 위도가 기대와 같은지 확인한다 (캐시 재사용이면 최초 좌표, 재계산이면 새 좌표)."""
    assert world.coord._cached_area_lat == pytest.approx(위도)
