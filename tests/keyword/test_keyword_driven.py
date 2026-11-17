"""키워드 드리븐 테스트 — tests/keyword/scenarios/*.yaml 의 시나리오를 키워드로 실행한다.

시나리오는 코드 없이 YAML 표로만 작성되며, 각 단계는 testkit/keyword_libs 의 키워드를 호출한다.
  - 키워드 목록 보기 : python tests/keyword/catalog.py   (문서: tests/keyword/KEYWORDS.md)
  - 시나리오 목록 보기: pytest tests/keyword --collect-only -q
"""
import logging
from pathlib import Path

import pytest

from testkit import keyword_libs  # noqa: F401  (import 하는 것만으로 키워드가 등록된다)
from testkit.keywords import REGISTRY, World, load_scenarios

HERE = Path(__file__).parent
SCENARIOS = load_scenarios(HERE / "scenarios")


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: f"{s.source}::{s.name}")
def test_keyword_scenario(scenario, caplog):
    """시나리오의 단계(키워드)를 순서대로 실행한다. 어느 단계에서 실패했는지 메시지에 드러난다."""
    world = World(caplog=caplog)
    try:
        with caplog.at_level(logging.DEBUG):
            for number, step in enumerate(scenario.steps, start=1):
                try:
                    REGISTRY.execute(world, step)
                except Exception as exc:
                    raise AssertionError(f"[{scenario.name}] {number}번째 단계 {step!r} 실패: {exc!r}") from exc
    finally:
        for cleanup in world.get("cleanups", []):
            cleanup()


def test_every_keyword_is_documented():
    """모든 키워드에는 설명(docstring)이 있어야 카탈로그에서 읽을 수 있다."""
    assert [kw.name for kw in REGISTRY.all() if not kw.doc] == []


def test_keywords_catalog_file_is_up_to_date():
    """KEYWORDS.md 가 등록된 키워드와 일치하는지 확인한다. (갱신: python tests/keyword/catalog.py --write)"""
    assert (HERE / "KEYWORDS.md").read_text(encoding="utf-8") == REGISTRY.catalog_markdown()


def test_scenarios_only_use_registered_keywords():
    """YAML 이 존재하지 않는 키워드를 부르면 실행 전에 오타를 알 수 있다."""
    unknown = []
    for scenario in SCENARIOS:
        for step in scenario.steps:
            name = step if isinstance(step, str) else next(iter(step))
            try:
                REGISTRY.get(name)
            except KeyError:
                unknown.append((scenario.name, name))
    assert unknown == []
