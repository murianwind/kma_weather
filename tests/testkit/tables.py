"""데이터 드리븐 테스트용 표 읽기 도구 (CSV / YAML)."""
import csv
from pathlib import Path

import pytest
import yaml

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def read_csv(name):
    """tests/data/<name> CSV 를 행 단위 딕셔너리 목록으로 읽는다 (# 로 시작하는 줄은 주석)."""
    with open(DATA_DIR / name, encoding="utf-8", newline="") as handle:
        lines = [line for line in handle if not line.lstrip().startswith("#")]
    return list(csv.DictReader(lines))


def read_yaml(name):
    return yaml.safe_load((DATA_DIR / name).read_text(encoding="utf-8"))


def table_params(rows, label):
    """행을 pytest.param 으로 만든다. 테스트 id 는 '<id>-<label(행)>' 으로 표에서 바로 찾을 수 있다."""
    return [pytest.param(row, id=f"{row['id']}-{label(row)}") for row in rows]


def number_or_text(token):
    """표의 셀 값: 숫자로 읽히면 float, 아니면 문자열 그대로."""
    try:
        return float(token)
    except ValueError:
        return token
