"""BDD 스텝 점검: pytest-bdd 는 `async def` 스텝을 실행하지 않고 코루틴만 만들어 조용히 통과시킨다.
그런 스텝은 아무것도 검증하지 않으므로 스텝 모듈에 async 스텝이 없는지 확인한다 (대신 testkit.aio.run_on 사용)."""
import ast
from pathlib import Path

import pytest

STEP_DECORATORS = {"given", "when", "then"}
STEP_MODULES = sorted(Path(__file__).parent.glob("test_*_bdd.py"))


def is_step_decorator(decorator):
    call = decorator.func if isinstance(decorator, ast.Call) else decorator
    return isinstance(call, ast.Name) and call.id in STEP_DECORATORS


@pytest.mark.parametrize("path", STEP_MODULES, ids=lambda p: p.name)
def test_bdd_steps_are_not_async(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    async_steps = [node.name for node in ast.walk(tree)
                   if isinstance(node, ast.AsyncFunctionDef) and any(is_step_decorator(d) for d in node.decorator_list)]

    assert async_steps == [], f"async 스텝은 실행되지 않습니다 (run_on 사용): {async_steps}"
