"""BDD: 통합구성요소 등록과 해제 — features/integration_setup.feature (실제 Home Assistant, 코루틴은 run_on 으로 실행)"""
from pytest_bdd import given, parsers, scenarios, then, when

from custom_components.kma_weather.const import DOMAIN
from testkit.aio import run_on

scenarios("features/integration_setup.feature")


# ── 조건 (Given) ─────────────────────────────────────────────────────────────
@given(parsers.parse('위도 {lat:f}, 경도 {lon:f} 에서 "{scenario}" 데이터로 구성요소를 추가한다'))
def add_entry(hass, mock_config_entry, kma_api_mock_factory, lat, lon, scenario):
    hass.config.latitude, hass.config.longitude = lat, lon
    kma_api_mock_factory(scenario)
    mock_config_entry.add_to_hass(hass)


@given("구성요소를 설정한다")
@when("구성요소를 설정한다")
def setup_entry(hass, mock_config_entry):
    async def setup():
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    run_on(hass, setup())


# ── 만일 (When) ──────────────────────────────────────────────────────────────
@when("구성요소를 해제한다")
def unload_entry(hass, mock_config_entry):
    async def unload():
        await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    run_on(hass, unload())


# ── 그러면 (Then) ────────────────────────────────────────────────────────────
@then("코디네이터가 등록 정보에 들어 있다")
def coordinator_registered(hass, mock_config_entry):
    assert mock_config_entry.entry_id in hass.data[DOMAIN]


@then("코디네이터가 등록 정보에서 제거되어 있다")
def coordinator_removed(hass, mock_config_entry):
    assert mock_config_entry.entry_id not in hass.data.get(DOMAIN, {})
