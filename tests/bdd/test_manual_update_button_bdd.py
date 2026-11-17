"""BDD: 수동 업데이트 버튼 — features/manual_update_button.feature (실제 Home Assistant)"""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kma_weather.button import KMAUpdateButton
from custom_components.kma_weather.const import DOMAIN
from testkit.aio import run_on

scenarios("features/manual_update_button.feature")

NO_ENTITY = "(없음)"
T0 = datetime(2026, 4, 11, 10, 0, 0)


@pytest.fixture
def world():
    return {}


def setup_integration(hass, kma_api_mock_factory, entity, prefix):
    kma_api_mock_factory("full_test")
    data = {"api_key": "k", "prefix": prefix, "location_entity": "" if entity == NO_ENTITY else entity}
    entry = MockConfigEntry(domain=DOMAIN, data=data, entry_id=f"button_{prefix}")
    entry.add_to_hass(hass)

    async def setup():
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    run_on(hass, setup())
    return entry


# ── 조건 (Given) ─────────────────────────────────────────────────────────────
@given(parsers.parse('위치 엔티티가 "{entity}" 이고 접두어가 "{prefix}" 인 통합구성요소가 설정되어 있다'))
def integration_with_location(hass, kma_api_mock_factory, entity, prefix):
    setup_integration(hass, kma_api_mock_factory, entity, prefix)


@given("업데이트 버튼이 있다")
def button_exists(hass, kma_api_mock_factory, world):
    entry = setup_integration(hass, kma_api_mock_factory, "device_tracker.phone", "pad")
    coordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.async_request_refresh = AsyncMock()
    world["coordinator"], world["button"] = coordinator, KMAUpdateButton(coordinator, entry)


# ── 만일 (When) ──────────────────────────────────────────────────────────────
def press_at(hass, world, moment):
    with patch("custom_components.kma_weather.button.datetime") as clock:
        clock.now.return_value = moment
        run_on(hass, world["button"].async_press())


@when("버튼을 한 번 누른다")
def press_once(hass, world):
    press_at(hass, world, T0)


@when(parsers.parse("버튼을 한 번 누르고 {seconds}초 뒤에 다시 누른다"))
def press_twice(hass, world, seconds):
    press_at(hass, world, T0)
    press_at(hass, world, T0 + timedelta(seconds=float(seconds)))


# ── 그러면 (Then) ────────────────────────────────────────────────────────────
@then(parsers.parse('업데이트 버튼 "{entity_id}" 는 만들어진다'))
def button_created(hass, entity_id):
    assert hass.states.get(entity_id) is not None


@then(parsers.parse('업데이트 버튼 "{entity_id}" 는 만들어지지 않는다'))
def button_not_created(hass, entity_id):
    assert hass.states.get(entity_id) is None


@then(parsers.parse("갱신 요청은 {count:d}번 일어난다"))
def refresh_count(world, count):
    assert world["coordinator"].async_request_refresh.call_count == count


@then(parsers.parse('갱신 이유는 "{reason}" 이다'))
def refresh_reason(world, reason):
    assert world["coordinator"]._update_reason == reason
