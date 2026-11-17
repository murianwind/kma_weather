"""페어와이즈(2-way) 조합 표 생성기.

요인이 4개(4×4×3×2 = 96조합)여도 '모든 값 쌍'이 한 번 이상 등장하는 조합만 골라 케이스를 줄인다.
결과는 tests/data_driven/cases/precip_pairwise.csv 로 커밋되어 시연에서 표 그대로 볼 수 있다.

    python tests/testkit/pairwise.py          # CSV 다시 생성
"""
import csv
import io
import sys
from pathlib import Path

from allpairspy import AllPairs

# 요인(입력 조건)과 수준(값)
FACTORS = {
    "pty": ["0", "1", "3", "4"],                      # 강수형태: 없음/비/눈/소나기 (3=눈은 적설 SNO 사용)
    "형식": ["없음", "수치", "미만", "범위"],           # 원본 값의 표기 형식
    "현재시각": ["00:30", "14:30", "23:30"],           # 하루의 처음 / 한낮 / 마지막
    "예보일수": ["1", "3"],                            # 오늘만 / 사흘치
}

RAW = {  # (눈 여부, 형식) → 원본 값
    (False, "없음"): "강수없음", (False, "수치"): "5.0mm", (False, "미만"): "1mm 미만", (False, "범위"): "30.0~50.0mm",
    (True, "없음"): "적설없음", (True, "수치"): "3.0cm", (True, "미만"): "1cm 미만", (True, "범위"): "3.0~5.0cm",
}
# 오라클(기대값): 프로덕션 코드를 쓰지 않고 규칙만으로 계산한다
STATE = {"없음": "0.0", "수치": None, "미만": "0.5", "범위": None}   # None 은 눈 여부로 결정
HOURLY = {"없음": "0", "미만": "~1"}
COLUMNS = ["id", "pty", "형식", "현재시각", "예보일수", "원본값",
           "기대_상태", "기대_표기", "확인_키", "기대_속성값"]

CSV_PATH = Path(__file__).resolve().parent.parent / "data_driven" / "cases" / "precip_pairwise.csv"
HEADER = (
    "# 페어와이즈: PTY × 원본값 형식 × 현재시각 × 예보일수 의 모든 값 쌍을 커버하는 최소 조합\n"
    "# 생성: python tests/testkit/pairwise.py  (손으로 고치지 말고 요인을 바꾼 뒤 다시 생성)\n"
    "# 확인_키: 현재 시각의 다음 시각 속성 키 (23시대는 다음 시각이 없어 23시 자체가 '-')\n"
)


def expected(pty, form, now, days):
    snow = pty == "3"
    raw = RAW[(snow, form)]
    low, high = ("3", "5") if snow else ("30", "50")
    number = "3.0" if snow else "5.0"
    state = {"수치": number, "범위": f"{low}.0"}.get(form, STATE[form])
    hourly = {"수치": number, "범위": f"{low}~{high}"}.get(form, HOURLY.get(form))
    hour = int(now.split(":")[0])
    key, value = (f"{hour + 1:02d}시", hourly) if hour < 23 else ("23시", "-")
    return raw, state, raw, key, value


def cases():
    names = list(FACTORS)
    rows = []
    for number, combo in enumerate(AllPairs([FACTORS[n] for n in names]), start=1):
        pty, form, now, days = combo
        raw, state, display, key, value = expected(pty, form, now, days)
        rows.append({"id": f"PW{number:02d}", "pty": pty, "형식": form, "현재시각": now, "예보일수": days,
                     "원본값": raw, "기대_상태": state, "기대_표기": display,
                     "확인_키": key, "기대_속성값": value})
    return rows


def render():
    out = io.StringIO()
    out.write(HEADER)
    writer = csv.DictWriter(out, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(cases())
    return out.getvalue()


if __name__ == "__main__":
    CSV_PATH.write_text(render(), encoding="utf-8")
    print(f"{len(cases())}개 조합을 {CSV_PATH} 에 생성했습니다. (전체 조합: 96)", file=sys.stderr)
