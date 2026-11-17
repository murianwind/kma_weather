"""BDD: 특보 지역 이름 파일 읽기 — features/warn_area_names_loading.feature"""
from unittest.mock import MagicMock

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from custom_components.kma_weather import api_kma as api_module
from custom_components.kma_weather.api_kma import KMAWeatherAPI
from testkit.aio import run
from testkit.keywords import World

scenarios("features/warn_area_names_loading.feature")


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setattr(api_module, "_WARN_AREA_NAMES", {})  # 아직 읽지 않은 상태 (테스트가 끝나면 원래대로)
    return World(executor_calls=0)


@given("Home Assistant 가 있는 API 가 있고 지역 이름은 아직 읽지 않았다")
def api_with_hass(world):
    hass = MagicMock()

    async def executor(func, *args):
        world.executor_calls += 1
        return func(*args)

    hass.async_add_executor_job = executor
    world.api = KMAWeatherAPI(MagicMock(), "key", hass=hass)


@given("Home Assistant 가 없는 API 가 있고 지역 이름은 아직 읽지 않았다")
def api_without_hass(world):
    world.api = KMAWeatherAPI(MagicMock(), "key", hass=None)


@when(parsers.parse('특보구역 "{code}" 의 지역 이름을 조회한다'))
def query_name(world, code):
    world.name = run(world.api._get_warn_area_display_name(code))


@then(parsers.parse('지역 이름은 "{name}" 이다'))
def name_is(world, name):
    assert world.name == name


@then(parsers.parse("파일 읽기는 executor 로 {count:d}번 넘겨졌다"))
def executor_count(world, count):
    assert world.executor_calls == count
