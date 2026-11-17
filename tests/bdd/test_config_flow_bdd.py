"""BDD: 통합구성요소 추가 화면 — features/config_flow.feature (실제 Home Assistant 플로우 매니저)"""
from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from pytest_bdd import given, parsers, scenarios, then, when
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kma_weather.const import DOMAIN
from testkit.aio import run_on

scenarios("features/config_flow.feature")

NO_ENTITY = "(없음)"  # 위치 엔티티를 고르지 않음
VALIDATION_URL = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"


@pytest.fixture(autouse=True)
def no_real_setup():
    """항목이 만들어져도 실제 통합 설정(네트워크 호출)은 하지 않는다."""
    with patch("custom_components.kma_weather.async_setup_entry", return_value=True):
        yield


@pytest.fixture
def world():
    return {}


# ── 조건 (Given) ─────────────────────────────────────────────────────────────
@given(parsers.parse('기상청 API 가 결과 코드 "{code}" 을 돌려준다'))
def api_result_code(aioclient_mock, code):
    aioclient_mock.get(VALIDATION_URL, status=200, json={"response": {"header": {"resultCode": code}}})


@given(parsers.parse('위치 엔티티 "{entity}" 의 상태 이름은 "{name}" 이다'))
def entity_state(hass, entity, name):
    if entity != NO_ENTITY and name != "-":
        hass.states.async_set(entity, "home", {"friendly_name": name})


@given(parsers.parse('API 키 "{key}", 접두어 "{prefix}" 으로 이미 등록되어 있다'))
def already_registered(hass, key, prefix):
    MockConfigEntry(domain=DOMAIN, data={"api_key": key, "prefix": prefix},
                    unique_id=f"{key}_{prefix}").add_to_hass(hass)


# ── 만일 (When) ──────────────────────────────────────────────────────────────
@when("통합구성요소 추가 화면을 연다")
def open_form(hass, world):
    world["result"] = run_on(hass, hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER}))


def submit(hass, world, user_input):
    async def go():
        opened = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
        return await hass.config_entries.flow.async_configure(opened["flow_id"], user_input)
    world["result"] = run_on(hass, go())


@when(parsers.parse('API 키 "{key}", 접두어 "{prefix}" 로 제출한다'))
@when(parsers.parse('API 키 "{key}", 접두어 "{prefix}" 으로 제출한다'))
def submit_without_location(hass, world, key, prefix):
    submit(hass, world, {"api_key": key, "prefix": prefix})


@when(parsers.parse('API 키 "{key}", 접두어 "{prefix}", 위치 "{entity}" 로 제출한다'))
def submit_with_location(hass, world, key, prefix, entity):
    user_input = {"api_key": key, "prefix": prefix}
    if entity != NO_ENTITY:
        user_input["location_entity"] = entity
    submit(hass, world, user_input)


# ── 그러면 (Then) ────────────────────────────────────────────────────────────
@then(parsers.parse('"{step_id}" 입력 화면이 오류 없이 보인다'))
def form_without_errors(world, step_id):
    assert world["result"]["type"] == FlowResultType.FORM
    assert world["result"]["step_id"] == step_id
    assert not world["result"]["errors"]


@then(parsers.parse('입력 화면이 다시 보이고 api_key 오류는 "{error}" 이다'))
def form_with_api_key_error(world, error):
    assert world["result"]["type"] == FlowResultType.FORM
    assert world["result"]["errors"] == {"api_key": error}


@then(parsers.parse('항목이 만들어지고 이름은 "{title}" 이다'))
def entry_created(world, title):
    assert world["result"]["type"] == FlowResultType.CREATE_ENTRY
    assert world["result"]["title"] == title


@then(parsers.parse('"{reason}" 사유로 중단된다'))
def aborted(world, reason):
    assert world["result"]["type"] == FlowResultType.ABORT
    assert world["result"]["reason"] == reason
