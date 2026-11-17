# language: ko
# ┌ 키워드 대응표 (Gherkin 한국어 ↔ English) ───────────────────────────────┐
# │ 기능 Feature · 시나리오 Scenario · 시나리오 개요 Scenario Outline · 예 Examples │
# │ 조건 Given (먼저) · 만일 When (만약) · 그러면 Then · 그리고 And · 하지만 But    │
# └──────────────────────────────────────────────────────────────────────────────┘
기능: 특보 지역 이름 파일 읽기
  특보 지역 이름 파일(warn_area_names.json)을 읽는 동기 파일 입출력이 이벤트 루프를 막지 않도록
  Home Assistant 가 있으면 executor 로 넘기고, 한 번 읽은 뒤에는 다시 읽지 않아야 합니다.
  (실제로 "Detected blocking call to read_text inside the event loop" 로그가 나왔던 문제입니다.)

  시나리오: Home Assistant 가 있으면 파일 읽기를 executor 로 넘긴다
    조건 Home Assistant 가 있는 API 가 있고 지역 이름은 아직 읽지 않았다
    만일 특보구역 "L1091320" 의 지역 이름을 조회한다
    그러면 지역 이름은 "제주시북부" 이다
    그리고 파일 읽기는 executor 로 1번 넘겨졌다

  시나리오: Home Assistant 가 없으면 직접 읽는다
    조건 Home Assistant 가 없는 API 가 있고 지역 이름은 아직 읽지 않았다
    만일 특보구역 "L1091320" 의 지역 이름을 조회한다
    그러면 지역 이름은 "제주시북부" 이다

  시나리오: 한 번 읽은 뒤에는 다시 읽지 않는다
    조건 Home Assistant 가 있는 API 가 있고 지역 이름은 아직 읽지 않았다
    만일 특보구역 "L1091320" 의 지역 이름을 조회한다
    그리고 특보구역 "L1130120" 의 지역 이름을 조회한다
    그러면 지역 이름은 "광주동부" 이다
    그리고 파일 읽기는 executor 로 1번 넘겨졌다

  시나리오: 상위 지역 파일도 Home Assistant 가 있으면 executor 로 넘긴다
    조건 Home Assistant 가 있는 API 가 있고 지역 이름은 아직 읽지 않았다
    만일 특보구역 "L1091320" 의 상위 지역을 조회한다
    그러면 상위 지역 목록은 비어 있지 않다
    그리고 파일 읽기는 executor 로 1번 넘겨졌다

