"""키워드 드리븐 테스트 엔진.

  - 키워드: 한국어 이름이 붙은 파이썬 함수 (@keyword 로 등록, docstring 이 설명)
  - 시나리오: YAML 에 키워드를 순서대로 나열한 표 (코드 없이 읽고 고칠 수 있음)
  - 카탈로그: 등록된 키워드의 이름·인자·설명을 표로 출력 (tests/keyword_driven/KEYWORDS.md)

YAML 시나리오 형식:

    library: 라이브러리이름
    scenarios:
      - name: 시나리오 이름
        description: 한 줄 설명
        steps:
          - 키워드이름: {인자: 값}     # 인자가 매핑이면 키워드 인자로 전달
          - 키워드이름: 값              # 스칼라/리스트면 첫 인자로 전달
          - 키워드이름                  # 인자 없음
"""
import inspect
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Keyword:
    name: str
    func: object
    library: str
    doc: str
    params: list = field(default_factory=list)


class KeywordRegistry:
    def __init__(self):
        self._keywords: dict[str, Keyword] = {}

    def keyword(self, name, *, library):
        """함수를 한국어 이름의 키워드로 등록한다. 첫 인자 world 는 시나리오 상태 저장소."""
        def decorator(func):
            if name in self._keywords:
                raise ValueError(f"키워드 이름 중복: {name}")
            params = [p for p in list(inspect.signature(func).parameters)[1:]]
            doc = inspect.getdoc(func) or ""
            self._keywords[name] = Keyword(name, func, library, doc.splitlines()[0] if doc else "", params)
            return func
        return decorator

    def get(self, name) -> Keyword:
        try:
            return self._keywords[name]
        except KeyError:
            raise KeyError(f"등록되지 않은 키워드: {name!r}") from None

    def all(self):
        return sorted(self._keywords.values(), key=lambda k: (k.library, k.name))

    def execute(self, world, step):
        """step 하나(키워드 이름 또는 {키워드: 인자})를 실행한다."""
        if isinstance(step, str):
            name, args = step, None
        else:
            (name, args), = step.items()
        keyword = self.get(name)
        if args is None:
            return keyword.func(world)
        if isinstance(args, dict):
            return keyword.func(world, **args)
        return keyword.func(world, args)

    def catalog_markdown(self):
        lines = ["# 키워드 목록", "",
                 "`python tests/keyword_driven/catalog.py --write` 로 생성한 문서입니다. "
                 "키워드를 추가하면 이 파일도 다시 생성하세요 (일치 여부는 테스트가 확인합니다).", ""]
        library = None
        for kw in self.all():
            if kw.library != library:
                library = kw.library
                lines += ([""] if lines[-1] != "" else []) + [f"## {library}", "", "| 키워드 | 인자 | 설명 |", "|---|---|---|"]
            lines.append(f"| `{kw.name}` | {', '.join(kw.params) or '-'} | {kw.doc} |")
        return "\n".join(lines) + "\n"


@dataclass
class Scenario:
    name: str
    description: str
    steps: list
    source: str


def load_scenarios(directory):
    """디렉터리의 *.yaml 시나리오 파일을 모두 읽는다."""
    scenarios = []
    for path in sorted(Path(directory).glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for item in data["scenarios"]:
            scenarios.append(Scenario(item["name"], item.get("description", ""),
                                      item["steps"], path.name))
    return scenarios


REGISTRY = KeywordRegistry()
keyword = REGISTRY.keyword


class World(dict):
    """시나리오가 진행되는 동안 키워드들이 공유하는 상태 저장소 (world.coord 처럼 접근)."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name) from None

    def __setattr__(self, name, value):
        self[name] = value
