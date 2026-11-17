"""키워드 카탈로그 출력.

  python tests/keyword/catalog.py             # 터미널에 키워드 목록 출력
  python tests/keyword/catalog.py --markdown  # Markdown 으로 출력
  python tests/keyword/catalog.py --write     # tests/keyword/KEYWORDS.md 갱신
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE.parent.parent)]

from testkit import keyword_libs  # noqa: E402,F401  (import 하는 것만으로 키워드가 등록된다)
from testkit.keywords import REGISTRY, load_scenarios  # noqa: E402


def main(argv):
    if "--write" in argv:
        (HERE / "KEYWORDS.md").write_text(REGISTRY.catalog_markdown(), encoding="utf-8")
        print("KEYWORDS.md 를 갱신했습니다.")
    elif "--markdown" in argv:
        print(REGISTRY.catalog_markdown(), end="")
    else:
        library = None
        for kw in REGISTRY.all():
            if kw.library != library:
                library = kw.library
                print(f"\n[{library}]")
            params = ", ".join(kw.params) or "-"
            print(f"  {kw.name:<28} ({params})\n      {kw.doc}")
        scenarios = load_scenarios(HERE / "scenarios")
        print(f"\n시나리오 {len(scenarios)}개:")
        for sc in scenarios:
            print(f"  - [{sc.source}] {sc.name}\n      {sc.description}")


if __name__ == "__main__":
    main(sys.argv[1:])
