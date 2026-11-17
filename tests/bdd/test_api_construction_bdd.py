"""BDD: 코디네이터가 만드는 API 객체 — features/api_construction.feature (실제 Home Assistant)"""
import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kma_weather.const import DOMAIN
from custom_components.kma_weather.coordinator import KMAWeatherUpdateCoordinator
from testkit.aio import run_on

scenarios("features/api_construction.feature")


@pytest.fixture
def world():
    return {"data": {"api_key": "TEST_KEY", "location_entity": ""}}


@given(parsers.parse('설치 UUID 가 "{uuid}" 인 Home Assistant 가 있다'))
def hass_with_uuid(hass, uuid):
    hass.installation_uuid = uuid


@given(parsers.parse('설정 항목에 기온구역 "{temp}", 육상구역 "{land}" 이 들어 있다'))
def entry_with_region_ids(world, temp, land):
    world["data"].update({"reg_id_temp": temp, "reg_id_land": land})


@when("코디네이터가 만들어진다")
def build_coordinator(hass, world):
    async def build():
        entry = MockConfigEntry(domain=DOMAIN, data=world["data"], entry_id="api_construction")
        return KMAWeatherUpdateCoordinator(hass, entry)
    world["coordinator"] = run_on(hass, build())


@then(parsers.parse('API 의 요청 식별은 "{expected}" 이다'))
def user_agent_is(world, expected):
    assert world["coordinator"].api._nominatim_user_agent == expected


@then("API 에는 기온구역과 육상구역이 저장되어 있지 않다")
def no_region_ids_on_api(world):
    api = world["coordinator"].api
    assert not hasattr(api, "reg_id_temp")
    assert not hasattr(api, "reg_id_land")
