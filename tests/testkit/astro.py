"""천문 테스트 공용: skyfield 천체력(de440s.bsp) 불러오기와 건너뛰기 표시."""
import os
import tempfile

import pytest


def load_skyfield():
    """de440s.bsp 를 (CI 에서는 자동 다운로드, 로컬에서는 임시 폴더 캐시에서) 불러온다. 없으면 (None, None)."""
    try:
        from skyfield.api import Loader
        cache = os.path.join(tempfile.gettempdir(), "skyfield_test_cache")
        os.makedirs(cache, exist_ok=True)
        loader = Loader(cache)
        return loader.timescale(), loader("de440s.bsp")
    except Exception:
        return None, None


SF_TS, SF_EPH = load_skyfield()
needs_skyfield = pytest.mark.skipif(SF_EPH is None, reason="skyfield/de440s.bsp 없음")
