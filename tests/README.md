# 테스트 시연 가이드

같은 대상(현재 예상 강수량 센서, 일시정지 존 pause_zones)을 **세 가지 방식**으로 보여줍니다.
커버리지 측정(`--cov-branch`, Codecov)과 CI 요약은 기존 그대로 동작합니다.

| 방식 | 위치 | 무엇을 보여주나 | 보는 법 |
|---|---|---|---|
| **BDD** (pytest-bdd, 한국어 Gherkin) | `tests/bdd/features/*.feature` + `tests/bdd/test_*_bdd.py` | 사용자 시나리오(조건/만일/그러면), 시나리오 개요 + 예 표 | `pytest tests/bdd --gherkin-terminal-reporter -v` |
| **키워드 드리븐** | `tests/keyword/scenarios/*.yaml` + `tests/testkit/keyword_libs/` | 코드 없이 키워드를 나열한 시나리오 표, 키워드 목록 | `python tests/keyword/catalog.py` (문서: `tests/keyword/KEYWORDS.md`) |
| **데이터 드리븐** | `tests/data/*.csv\|yaml` + `tests/test_*_data.py` | 같은 테스트 코드에 표만 바꿔 케이스 확장 | `pytest tests/test_precip_data.py tests/test_pause_zone_data.py -v` |

## 테스트 설계 기법 → 표/시나리오 대응

| 기법 | 적용 위치 |
|---|---|
| 동등분할 | `precip_amount.csv`(EP*), `pause_zone_polling.csv`, `pause_zone_visibility.csv`, `pause_zone_options.csv`, `precip_sensor_exposure.yaml` |
| 경계값분석 | `precip_amount.csv`(BV*), `pause_zone_radius.csv`(반경 ±0.1m, 기본 반경), `pause_zone_exit.feature`(판정 분 14/15, 0/59, 성공 시각 = 이탈 시각), `precip_hourly.feature`(00:05 … 23:30) |
| 페어와이즈 | `precip_pairwise.csv` — 96조합을 16개로 (`python tests/testkit/pairwise.py` 로 생성, 쌍 커버 여부는 테스트가 검증) |
| 상태 전이 | `pause_zone_commute.yaml`(집 안 → 이탈 → 대기 → 판정), `pause_zone_lifecycle.feature` |

## 자주 쓰는 명령

```bash
pytest tests/bdd tests/keyword tests/test_precip_data.py tests/test_pause_zone_data.py   # 시연 대상만
pytest tests/bdd --collect-only -q                    # 시나리오 목록
pytest tests/keyword --collect-only -q                # 키워드 시나리오 목록
python tests/keyword/catalog.py --write               # 키워드 문서 갱신 (키워드 추가 후)
python tests/testkit/pairwise.py                      # 페어와이즈 표 다시 생성 (요인 변경 후)
```

## 새 케이스 추가하기

- **데이터 드리븐**: CSV 행 하나만 추가하면 테스트가 늘어납니다 (코드 수정 없음).
- **키워드 드리븐**: YAML 에 키워드를 나열합니다. 필요한 키워드가 없으면 `tests/testkit/keyword_libs/` 에 `@keyword("이름", library=...)` 함수를 추가하고 카탈로그를 갱신합니다.
- **BDD**: `.feature` 에 시나리오를 쓰고, 없는 문장만 스텝 함수로 추가합니다.

## 공용 도구 (`tests/testkit/`)

`factories.py`(예보·존·코디네이터 생성기, 가짜 타이머), `aio.py`(동기 스텝에서 코루틴 실행), `keywords.py`(키워드 엔진), `tables.py`(CSV/YAML 읽기), `pairwise.py`(페어와이즈 생성기)
