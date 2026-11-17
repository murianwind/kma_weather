# 테스트 시연 가이드

도메인별로 **세 가지 방식**을 보여줍니다 (현재: 강수량, 일시정지 존 pause_zones, 자외선지수, 에어코리아/지역코드, 기상특보·API 미신청/중지·구역코드, 예보 병합·중기예보·일일 기온·날씨 상태, 코디네이터 위치·캐시·통합 시나리오, API 객체·역지오코딩·설정 화면·천문 서비스 입력·꽃가루).
한 테스트는 성격에 맞는 한 가지 방식으로만 작성해 중복을 피합니다 — 시나리오(BDD) / 긴 호출·실패 흐름(키워드) / 입력→출력 규칙(데이터).
커버리지 측정(`--cov-branch`, Codecov)과 CI 요약은 기존 그대로 동작합니다.

| 방식 | 위치 | 무엇을 보여주나 | 보는 법 |
|---|---|---|---|
| **BDD** (pytest-bdd, 한국어 Gherkin) | `tests/bdd/features/*.feature` + `tests/bdd/test_*_bdd.py` | 사용자 시나리오(조건/만일/그러면), 시나리오 개요 + 예 표 | `pytest tests/bdd --gherkin-terminal-reporter -v` |
| **키워드 드리븐** | `tests/keyword/scenarios/*.yaml` + `tests/testkit/keyword_libs/` | 코드 없이 키워드를 나열한 시나리오 표, 키워드 목록 | `python tests/keyword/catalog.py` (문서: `tests/keyword/KEYWORDS.md`) |
| **데이터 드리븐** | `tests/data/*.csv\|yaml` + `tests/test_*_data.py` | 같은 테스트 코드에 표만 바꿔 케이스 확장 | `pytest tests/test_precip_data.py tests/test_pause_zone_data.py -v` |

### Gherkin 한국어 키워드 대응표

`.feature` 첫 줄 `# language: ko` 는 Gherkin 공식 한국어 사전을 쓴다는 선언이며, 이 사전이 인식하는 키워드만 쓸 수 있습니다.
각 `.feature` 파일 상단에도 같은 대응표가 주석으로 들어 있습니다.

| 한국어 | English |
|---|---|
| 기능 | Feature |
| 시나리오 / 시나리오 개요 / 예 | Scenario / Scenario Outline / Examples |
| 조건 (먼저) | Given |
| 만일 (만약) | When |
| 그러면 | Then |
| 그리고 / 하지만 (단) | And / But |

## 테스트 설계 기법 → 표/시나리오 대응

| 기법 | 적용 위치 |
|---|---|
| 동등분할 | `precip_amount.csv`(EP*), `pause_zone_polling.csv`, `pause_zone_visibility.csv`, `pause_zone_options.csv`, `precip_sensor_exposure.yaml`, `uv_grade.csv`(EP*), `uv_base_time.csv`(EP*), `uv_sensor_exposure.yaml`, `fetch_retry.csv`(오류 종류별·HTTP 상태·응답 본문 형식), `api_key_decode.csv`, `user_agent.csv`, `address_lookup.csv`(행정 단위 조합·실패), `config_flow_result_codes.csv`(결과 코드 묶음), `geocode_results.csv`, `astro_service_errors.csv`(점검 순서별), `pollen_query.csv`(시즌·캐시·응답 종류), `short_term_response.csv`, `fetch_gating.csv`, `mid_condition_text.csv`, `warning_items.yaml`(발표/연장/정정/해제/취소/경보 수준), `warn_type_map.csv`(열대야 포함 전 종류), `unsubscribed_codes.csv`, `area_resolution.csv`, `eligible_sensors.yaml`, `api_sensor_availability.yaml`, `sky_pty_condition.csv`(SKY×PTY), `kor_condition.csv`, `rain_start_time.csv`, `current_slot_selection.csv`, `sensor_passthrough.yaml`, `forecast_boundary_times.csv`(하루 24시간 + 회차 전환 전후 34개 시각), `korean_coord_range.csv`(위도 32.0/31.999 등 범위 경계), `convert_grid.csv`(ON/OFF 경계값), `location_resolution.csv`, `safe_float.csv`, `moon_illumination.csv`, `malformed_short_response.yaml`(알려진 문제는 xfail) |
| 경계값분석 | `precip_amount.csv`(BV*), `pause_zone_radius.csv`(반경 ±0.1m, 기본 반경), `pause_zone_exit.feature`(판정 분 14/15, 0/59, 성공 시각 = 이탈 시각), `precip_hourly.feature`(00:05 … 23:30), `uv_grade.csv`(BV*: 2.9/3, 5.9/6 …), `uv_base_time.csv`(BV*: 02:59/03:00), `uv_query.feature`(발표 시각 02:59/03:00), `fetch_retry.csv`(시도 한도 2회), `time_parse.csv`(00:00/23:59/24:00, 12:59/12:60), `astro_service_errors.csv`(조회 가능 날짜 어제/오늘/오늘+4/오늘+5), `pollen_query.csv`(시즌 3/31·4/1, 6/30·7/1, 7/31·8/1, 10/31·11/1, 06:59/07:00, 18:59/19:00), `short_base_time.csv`(발표 +10분 경계, 자정 전후), `unsubscribed_codes.csv`(미신청 코드 19/20, 22/23, 29/30, 33/34), `warning_items.yaml`(같은 특보의 발표 시각 최신 기준), `coordinator_resilience.feature`(위치×API×캐시 결정표), `coordinator_sync.feature`(실시간 값 보존), `area_code_cache.yaml`(구역 캐시 2km 바로 안/밖 1.9km·2.1km, 오전 요약 비움 10:59/11:00), `mid_base_time.csv`(06:29/06:30, 18:29/18:30, 자정 전후), `daily_summary.feature`(11:59/12:00), `rain_start_time.csv`(현재 시간대 슬롯 포함/제외, 모레·3일 뒤) |
| 페어와이즈 | `precip_pairwise.csv` — 96조합을 16개로 (`python tests/testkit/pairwise.py` 로 생성, 쌍 커버 여부는 테스트가 검증) |
| 상태 전이 | `pause_zone_commute.yaml`(집 안 → 이탈 → 대기 → 판정), `pause_zone_lifecycle.feature`, `airkorea_air_quality.yaml`(캐시 → 이동 → 실패 → 보완), `midterm_query.yaml`(빈 응답 → 이전 회차 재시도), `forecast_cache.yaml`(단기·중기 연속 실패 시 캐시 유지) |

## 주의: pytest-bdd 의 async 스텝

pytest-bdd 는 `async def` 스텝을 **실행하지 않고** 코루틴 객체만 만들어 조용히 통과시킵니다. 실제 Home Assistant(`hass`)가 필요한
스텝은 동기 함수로 쓰고 `testkit.aio.run_on(hass, 코루틴)` 으로 실행하세요 (`test_integration_*_bdd.py` 참고).
`tests/bdd/test_bdd_guard.py` 가 async 스텝이 섞이지 않았는지 확인합니다.

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
