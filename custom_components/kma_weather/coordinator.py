import json
import logging
import asyncio
import pathlib
import zlib
from datetime import datetime, timedelta, timezone, date
try:
    from skyfield.api import Loader as _SkyLoader, wgs84 as _wgs84
    from skyfield import almanac as _almanac
    _SKYFIELD_OK = True
except ImportError:
    _SKYFIELD_OK = False
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from .api_kma import KMAWeatherAPI
from .const import DOMAIN, CONF_API_KEY, CONF_LOCATION_ENTITY, CONF_PREFIX, convert_grid, haversine, is_korean_coord_loose, safe_float as _safe_float

_LOGGER = logging.getLogger(__name__)

# skyfield 객체 전역 캐시 (프로세스당 1회 로드하여 테스트 속도 및 안정성 확보)
_SF_TS = None
_SF_EPH = None

# ── pause_zones: 모바일 기기 도메인 ─────────────────────────────────────────
_MOBILE_ENTITY_DOMAINS = ("device_tracker", "person")

def _is_mobile_entity(entity_id: str | None) -> bool:
    """location_entity가 device_tracker 또는 person 도메인인지 확인한다."""
    if not entity_id:
        return False
    return entity_id.split(".")[0] in _MOBILE_ENTITY_DOMAINS

# ── 중기예보 구역코드 테이블 (area.json) ────────────────────────────────────
_AREA: dict = {}
_TEMP_ID_COORDS: dict[str, tuple[float, float]] = {}
_EXCLUDE_FROM_NEAREST: frozenset[str] = frozenset()
_LAND_CODE_MAP: list[tuple[str, str]] = []


def _load_area_data() -> None:
    """area.json과 warn_area.json을 동기 로드한다. executor_job에서 실행."""
    global _AREA, _TEMP_ID_COORDS, _EXCLUDE_FROM_NEAREST, _LAND_CODE_MAP, _LAND_CODE_MAP_SORTED, _WARN_AREA
    _AREA = json.loads((pathlib.Path(__file__).parent / "area.json").read_text(encoding="utf-8"))
    _TEMP_ID_COORDS = {k: tuple(v) for k, v in _AREA["temp"].items()}
    _EXCLUDE_FROM_NEAREST = frozenset(_AREA["exclude"])
    _LAND_CODE_MAP = [tuple(x) for x in _AREA["land"]]
    _LAND_CODE_MAP_SORTED = sorted(_LAND_CODE_MAP, key=lambda x: len(x[0]), reverse=True)
    _WARN_AREA = json.loads((pathlib.Path(__file__).parent / "warn_area.json").read_text(encoding="utf-8"))

_LAND_CODE_MAP_SORTED: list[tuple[str, str]] = []
_WARN_AREA: list[list] = []


def _land_code(temp_id: str) -> str | None:
    for prefix, land in _LAND_CODE_MAP_SORTED:
        if temp_id.startswith(prefix):
            return land
    _LOGGER.warning("_land_code: '%s'에 매칭되는 중기예보 구역코드 없음 (area.json 손상 가능성)", temp_id)
    return None


def _calc_reg_ids(lat: float, lon: float) -> tuple[str | None, str | None]:
    """좌표 → (reg_id_temp, reg_id_land)"""
    best_id, best_dist = None, float("inf")
    for tid, (tlat, tlon) in _TEMP_ID_COORDS.items():
        if tid in _EXCLUDE_FROM_NEAREST:
            continue
        d = haversine(lat, lon, tlat, tlon)
        if d < best_dist:
            best_dist, best_id = d, tid
    return (best_id, _land_code(best_id)) if best_id else (None, None)


def _calc_warn_area_code(lat: float, lon: float) -> str | None:
    """좌표 → 특보구역코드"""
    best_code, best_dist = None, float("inf")
    for row in _WARN_AREA:
        d = haversine(lat, lon, row[0], row[1])
        if d < best_dist:
            best_dist, best_code = d, row[2]
    return best_code


class KMAWeatherUpdateCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry):
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        self.entry = entry
        self.api = KMAWeatherAPI(
            session=async_get_clientsession(hass),
            api_key=entry.data.get(CONF_API_KEY),
            hass=hass,
        )
        self._last_lat = self._last_lon = None
        self._daily_date = self._daily_max_temp = self._daily_min_temp = None
        self._wf_am_today = self._wf_pm_today = None
        self._cached_data = None
        self._unsub_timer = None
        self._update_lock = asyncio.Lock()

        self._cached_area_lat: float | None = None
        self._cached_area_lon: float | None = None
        self._cached_nx: int | None = None
        self._cached_ny: int | None = None
        self._cached_reg_id_temp: str | None = None
        self._cached_reg_id_land: str | None = None
        self._cached_warn_area_code: str | None = None

        self._sun_cache_date: date | None = None
        self._sun_cache_lat: float | None = None
        self._sun_cache_lon: float | None = None
        self._sun_times: dict = {}

        self._sf_eph = None
        self._sf_ts  = None
        if _SKYFIELD_OK:
            import os as _os, tempfile as _tf
            _sf_dir   = hass.config.config_dir + "/.skyfield"
            _fallback = _os.environ.get(
                "SKYFIELD_BSP_DIR",
                _os.path.join(_tf.gettempdir(), "skyfield_test_cache"),
            )
            if _os.path.exists(_fallback + "/de440s.bsp"):
                _sf_dir = _fallback
            hass.async_create_task(self._async_init_skyfield(_sf_dir))

        target_entity = entry.data.get(CONF_LOCATION_ENTITY, "default_location")
        safe_key = target_entity.replace(".", "_") if target_entity else entry.entry_id
        self._store = Store(hass, version=1, key=f"{DOMAIN}_{safe_key}_daily_temp")
        self._store_loaded = False

        self._api_call_counts: dict[str, int] = {
            "단기예보": 0, "중기예보": 0,
            "에어코리아_측정소": 0, "에어코리아_대기": 0,
            "기상특보": 0, "꽃가루": 0, "자외선지수": 0,
        }
        self._api_call_date: str | None = None
        self._api_call_store = Store(hass, version=1, key=f"{DOMAIN}_global_api_calls")
        self._api_call_store_loaded = False

        # 꽃가루·자외선지수는 기상청이 배포하는 동일한 행정구역코드 파일
        # (admin_area_map.json)을 쓴다. 완전히 같은 데이터라 캐시도
        # find_pollen_area/find_uv_area가 함께 공유한다 — 매 갱신마다
        # 같은 좌표로 지역을 두 번 계산하지 않는다.
        self._admin_area_data: list[dict] | None = None
        self._admin_cached_area_no: str | None = None
        self._admin_cached_area_name: str = ""
        self._admin_cached_lat: float | None = None
        self._admin_cached_lon: float | None = None

        self._approved_store = Store(hass, version=1, key=f"{DOMAIN}_{safe_key}_approved_apis")
        self._approved_store_loaded = False

        self._station_store = Store(hass, version=1, key=f"{DOMAIN}_{safe_key}_station_cache")
        self._station_store_loaded = False

        # 첫 업데이트(재시작)는 pause_zones를 무시하고 항상 데이터를 가져옴
        self._update_reason = "재시작"

        self._inject_counter()

    async def _async_init_skyfield(self, sf_dir: str) -> None:
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._sync_init_skyfield, sf_dir)
        except Exception as e:
            _LOGGER.warning("skyfield 비동기 초기화 실패: %s", e)

    def _sync_init_skyfield(self, sf_dir: str) -> None:
        global _SF_TS, _SF_EPH
        if not _SKYFIELD_OK:
            return
        if _SF_TS is not None and _SF_EPH is not None:
            self._sf_ts = _SF_TS
            self._sf_eph = _SF_EPH
            return
        try:
            import os as _os
            _os.makedirs(sf_dir, exist_ok=True)
            _loader = _SkyLoader(sf_dir)
            ts  = _loader.timescale()
            eph = _loader("de440s.bsp")
            _SF_TS, _SF_EPH = ts, eph
            self._sf_ts  = ts
            self._sf_eph = eph
            _LOGGER.debug("skyfield de440s.bsp 백그라운드 로드 완료")
        except Exception as e:
            _LOGGER.warning("skyfield 백그라운드 초기화 실패: %s", e)

    def _resolve_area_codes(self, lat: float, lon: float) -> tuple:
        is_moved = False
        if (self._cached_area_lat is not None
                and haversine(self._cached_area_lat, self._cached_area_lon, lat, lon) > 2.0):
            is_moved = True

        if not is_moved and self._cached_area_lat is not None:
            return (
                self._cached_nx, self._cached_ny,
                self._cached_reg_id_temp, self._cached_reg_id_land,
                self._cached_warn_area_code,
            )

        nx, ny = convert_grid(lat, lon)
        reg_id_temp, reg_id_land = _calc_reg_ids(lat, lon)
        warn_area_code = _calc_warn_area_code(lat, lon)

        self._cached_area_lat = lat
        self._cached_area_lon = lon
        self._admin_cached_lat = None
        self._admin_cached_lon = None
        for kind in ("pine", "oak", "grass"):
            self.api._pollen_cache[kind] = {
                "today": None, "tomorrow": None,
                "today_date": None, "tomorrow_date": None,
            }
        if datetime.now(self.api.tz).hour < 11:
            self._wf_am_today = None
        self._wf_pm_today = None
        self._cached_nx = nx
        self._cached_ny = ny
        self._cached_reg_id_temp = reg_id_temp
        self._cached_reg_id_land = reg_id_land
        self._cached_warn_area_code = warn_area_code

        _LOGGER.debug(
            "구역코드 갱신: nx=%s ny=%s reg_temp=%s reg_land=%s warn=%s",
            nx, ny, reg_id_temp, reg_id_land, warn_area_code,
        )
        return nx, ny, reg_id_temp, reg_id_land, warn_area_code

    @property
    def _shared_counts(self) -> dict[str, int]:
        return self.hass.data.setdefault(f"{DOMAIN}_api_call_counts", {
            "단기예보": 0, "중기예보": 0,
            "에어코리아_측정소": 0, "에어코리아_대기": 0,
            "기상특보": 0, "꽃가루": 0, "자외선지수": 0,
            "date": None,
        })

    def _inject_counter(self, reason: str = "자동 업데이트") -> None:
        def _increment(key: str) -> None:
            now_date = datetime.now(self.api.tz).strftime("%Y%m%d")
            shared = self._shared_counts
            if shared.get("date") and shared["date"] != now_date:
                for k in list(shared.keys()):
                    if k not in ("date", "last_reason"):
                        shared[k] = 0
                _LOGGER.debug("API 호출 카운터 자정 초기화: %s → %s", shared["date"], now_date)
                self.hass.async_create_task(self._save_api_calls())
            shared["date"] = now_date
            shared["last_reason"] = reason
            if key in shared:
                shared[key] += 1
            self._api_call_date = now_date
            if key in self._api_call_counts:
                self._api_call_counts[key] = shared[key]
            self.hass.async_create_task(self._notify_api_counter_listeners())
        self.api._call_counter_ref = _increment

    async def _restore_api_calls(self) -> None:
        if self._api_call_store_loaded:
            return
        try:
            stored = await self._api_call_store.async_load()
            if stored:
                tz = getattr(self.api, "tz", timezone(timedelta(hours=9)))
                today = datetime.now(tz).strftime("%Y%m%d")
                if stored.get("date") == today:
                    shared = self._shared_counts
                    if shared.get("date") != today:
                        for key in self._api_call_counts:
                            val = int(stored.get(key, 0))
                            self._api_call_counts[key] = val
                            shared[key] = val
                        shared["date"] = today
                        self._api_call_date = today
                        _LOGGER.debug("API 호출 카운터 복구 성공: %s", self._api_call_counts)
        except Exception as e:
            _LOGGER.debug("API 호출 카운터 복구 실패 (무시): %s", e)
        self._api_call_store_loaded = True

    async def _save_api_calls(self) -> None:
        try:
            await self._api_call_store.async_save({
                "date": self._api_call_date or datetime.now(self.api.tz).strftime("%Y%m%d"),
                **self._api_call_counts,
            })
        except Exception as e:
            _LOGGER.debug("API 호출 카운터 저장 실패: %s", e)

    def api_call_total(self) -> int:
        shared = self._shared_counts
        return sum(v for k, v in shared.items() if k not in ("date", "last_reason"))

    async def _notify_api_counter_listeners(self) -> None:
        try:
            self.async_update_listeners()
            for entry_id, coordinator in self.hass.data.get(DOMAIN, {}).items():
                if coordinator is not self and hasattr(coordinator, "async_update_listeners"):
                    coordinator.async_update_listeners()
        except Exception:
            pass

    def _load_admin_area_map(self) -> None:
        try:
            json_path = pathlib.Path(__file__).parent / "admin_area_map.json"
            with open(json_path, encoding="utf-8") as f:
                self._admin_area_data = json.load(f)
            _LOGGER.debug("행정구역코드 룩업 로드 완료: %d개 읍면동", len(self._admin_area_data))
        except Exception as e:
            _LOGGER.warning("행정구역코드 룩업 로드 실패 (admin_area_map.json 누락?): %s", e)
            self._admin_area_data = None

    async def _find_admin_area(self, lat: float, lon: float) -> tuple[str, str]:
        """
        꽃가루·자외선지수 공용 지역코드(10자리 행정동코드) 룩업.

        두 API는 기상청이 배포하는 동일한 지역코드표(2026-07-01자, admin_area_map.json)를
        쓴다 — 실제로 대조해서 완전히 같은 데이터임을 확인했다. 그래서 파일도
        하나, 좌표→지역 매칭 로직과 캐시도 하나만 두고 find_pollen_area/
        find_uv_area가 이 함수를 그대로 공유한다.
        """
        if (self._admin_cached_lat == lat
                and self._admin_cached_lon == lon
                and self._admin_cached_area_no):
            return self._admin_cached_area_no, self._admin_cached_area_name

        if not self._admin_area_data:
            try:
                await self.hass.async_add_executor_job(self._load_admin_area_map)
            except Exception as e:
                _LOGGER.warning("admin_area_map.json 로드 실패: %s", e)
            if not self._admin_area_data:
                _LOGGER.warning("admin_area_map.json 로드 실패 → 꽃가루/자외선지수 조회 불가")
                return "", ""

        best, best_d = None, float("inf")
        for r in self._admin_area_data:
            d = (r["la"] - lat) ** 2 + (r["lo"] - lon) ** 2
            if d < best_d:
                best_d, best = d, r

        if best:
            self._admin_cached_lat = lat
            self._admin_cached_lon = lon
            self._admin_cached_area_no = best["c"]
            self._admin_cached_area_name = best["n"]
            _LOGGER.debug("행정구역 지역 매칭: (%.4f, %.4f) → %s (%s)", lat, lon, best["n"], best["c"])
            return best["c"], best["n"]

        _LOGGER.warning("행정구역 지역 매칭 실패: (%.4f, %.4f)", lat, lon)
        return "", ""

    async def find_pollen_area(self, lat: float, lon: float) -> tuple[str, str]:
        return await self._find_admin_area(lat, lon)

    async def find_uv_area(self, lat: float, lon: float) -> tuple[str, str]:
        return await self._find_admin_area(lat, lon)

    async def async_setup(self) -> None:
        from homeassistant.helpers.event import async_track_time_change

        async def _scheduled_update(now):
            import sys
            if "pytest" not in sys.modules:
                delay = 10 + (zlib.adler32(str(self.entry.entry_id).encode()) % 21)
                if delay > 0:
                    _LOGGER.debug("[%s] 동시 호출 방지를 위해 %d초 후 업데이트를 시작합니다.", self.entry.data.get(CONF_PREFIX, "kma"), delay)
                    await asyncio.sleep(delay)
            await self.async_refresh()

        self._unsub_timer = async_track_time_change(
            self.hass, _scheduled_update, minute=15, second=0
        )

    def async_teardown(self) -> None:
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None

    async def _restore_approved_apis(self) -> None:
        if self._approved_store_loaded:
            return
        try:
            stored = await self._approved_store.async_load()
            if stored and isinstance(stored.get("approved"), list):
                for key in stored["approved"]:
                    self.api._approved_apis.add(key)
                    self.api._pending_apis.discard(key)
                _LOGGER.debug("승인 API 복구: %s", self.api._approved_apis)
        except Exception as e:
            _LOGGER.debug("승인 API 복구 실패 (무시): %s", e)
        self._approved_store_loaded = True

    async def _save_approved_apis(self) -> None:
        try:
            await self._approved_store.async_save({
                "approved": list(self.api._approved_apis)
            })
        except Exception as e:
            _LOGGER.debug("승인 API 저장 실패 (무시): %s", e)

    async def _restore_daily_temps(self):
        if self._store_loaded:
            return
        stored = await self._store.async_load()
        if stored:
            tz = getattr(self.api, "tz", timezone(timedelta(hours=9)))
            now = datetime.now(tz)
            if stored.get("date") == now.strftime("%Y%m%d"):
                try:
                    self._daily_date = now.date()
                    self._daily_max_temp = float(stored.get("max"))
                    self._daily_min_temp = float(stored.get("min"))
                    self._wf_am_today = stored.get("wf_am")
                    self._wf_pm_today = stored.get("wf_pm")
                    _LOGGER.info("✅ 저장소 데이터 복구 성공")
                except Exception as e:
                    _LOGGER.debug("저장소 데이터 복구 실패 (무시): %s", e)
        self._store_loaded = True

    async def _save_daily_temps(self):
        if self._daily_date:
            await self._store.async_save({
                "date": self._daily_date.strftime("%Y%m%d"),
                "min": self._daily_min_temp,
                "max": self._daily_max_temp,
                "wf_am": self._wf_am_today,
                "wf_pm": self._wf_pm_today,
            })

    async def _restore_station_cache(self):
        """
        재시작 시 에어코리아 측정소 캐시를 복구한다.
        날짜와 무관하게(위치가 안 바뀌었으면 측정소도 그대로이므로) 항상 복구를 시도한다.
        이게 없으면 재시작마다 getNearbyMsrstnList API를 다시 호출하게 되어
        '에어코리아_측정소' 호출 카운터가 실제 위치 이동 없이도 계속 쌓이는 문제가 있었다.
        """
        if self._station_store_loaded:
            return
        try:
            stored = await self._station_store.async_load()
            if stored and stored.get("station"):
                self.api._cached_station = stored.get("station")
                self.api._cached_station_code = stored.get("station_code")
                self.api._cached_station_lat = stored.get("lat")
                self.api._cached_station_lon = stored.get("lon")
                _LOGGER.debug(
                    "에어코리아 측정소 캐시 복구: %s (%.4f, %.4f)",
                    self.api._cached_station,
                    self.api._cached_station_lat or 0.0,
                    self.api._cached_station_lon or 0.0,
                )
        except Exception as e:
            _LOGGER.debug("측정소 캐시 복구 실패 (무시): %s", e)
        self._station_store_loaded = True

    async def _save_station_cache(self):
        if self.api._cached_station:
            try:
                await self._station_store.async_save({
                    "station": self.api._cached_station,
                    "station_code": self.api._cached_station_code,
                    "lat": self.api._cached_station_lat,
                    "lon": self.api._cached_station_lon,
                })
            except Exception as e:
                _LOGGER.debug("측정소 캐시 저장 실패 (무시): %s", e)

    def _update_daily_temperatures(self, forecast_map: dict) -> bool:
        now = datetime.now(self.api.tz)
        today_str, today_date = now.strftime("%Y%m%d"), now.date()
        changed = False

        if self._daily_date != today_date:
            self._daily_date, self._daily_max_temp, self._daily_min_temp = today_date, None, None
            changed = True

        temps = []
        for t_str, s in forecast_map.get(today_str, {}).items():
            raw_tmp = s.get("TMP")
            if raw_tmp is None:
                continue
            parsed = _safe_float(raw_tmp)
            if parsed is None:
                _LOGGER.warning(
                    "TMP 파싱 실패(원본 데이터 이상): 날짜=%s 시각=%s 원본값=%r → 해당 슬롯 제외",
                    today_str, t_str, raw_tmp,
                )
                continue
            temps.append(parsed)
        if temps:
            n_min, n_max = min(temps), max(temps)
            if self._daily_min_temp is None or n_min < self._daily_min_temp:
                self._daily_min_temp, changed = n_min, True
            if self._daily_max_temp is None or n_max > self._daily_max_temp:
                self._daily_max_temp, changed = n_max, True
        return changed

    def _sync_today_forecast(self, weather: dict) -> None:
        today_t_max = self._daily_max_temp
        today_t_min = self._daily_min_temp
        wf_am_today = self._wf_am_today or weather.get("wf_am_today")
        wf_pm_today = self._wf_pm_today or weather.get("wf_pm_today")

        tmrw_t_max = weather.get("TMX_tomorrow")
        tmrw_t_min = weather.get("TMN_tomorrow")
        wf_am_tomorrow = weather.get("wf_am_tomorrow")
        wf_pm_tomorrow = weather.get("wf_pm_tomorrow")

        for entry in weather.get("forecast_daily", []):
            idx = entry.get("_day_index")
            if idx == 0:
                if today_t_max is not None: entry["native_temperature"] = today_t_max
                if today_t_min is not None: entry["native_templow"] = today_t_min
            elif idx == 1:
                if tmrw_t_max is not None: entry["native_temperature"] = tmrw_t_max
                if tmrw_t_min is not None: entry["native_templow"] = tmrw_t_min
                if wf_pm_tomorrow: entry["condition"] = self.api.kor_to_condition(wf_pm_tomorrow)

        for entry in weather.get("forecast_twice_daily", []):
            idx = entry.get("_day_index")
            is_am = entry.get("is_daytime", True)
            if idx == 0:
                if today_t_max is not None: entry["native_temperature"] = today_t_max
                if today_t_min is not None: entry["native_templow"] = today_t_min
                if is_am and wf_am_today: entry["condition"] = self.api.kor_to_condition(wf_am_today)
                elif not is_am and wf_pm_today: entry["condition"] = self.api.kor_to_condition(wf_pm_today)
            elif idx == 1:
                if tmrw_t_max is not None: entry["native_temperature"] = tmrw_t_max
                if tmrw_t_min is not None: entry["native_templow"] = tmrw_t_min
                if is_am and wf_am_tomorrow: entry["condition"] = self.api.kor_to_condition(wf_am_tomorrow)
                elif not is_am and wf_pm_tomorrow: entry["condition"] = self.api.kor_to_condition(wf_pm_tomorrow)

    # ── 메인 업데이트 ───────────────────────────────────────────────────────
    async def _async_update_data(self) -> dict:
        async with self._update_lock:
            try:
                if not _TEMP_ID_COORDS:
                    await self.hass.async_add_executor_job(_load_area_data)
                await self._restore_approved_apis()
                await self._restore_daily_temps()
                await self._restore_api_calls()
                await self._restore_station_cache()

                # pause_zones 판단 전에 현재 이유를 먼저 저장
                _reason = getattr(self, "_update_reason", "자동 업데이트")

                self._inject_counter(_reason)
                self._update_reason = "자동 업데이트"

                curr_lat, curr_lon = self._resolve_location()
                if curr_lat is None:
                    return self._cached_data or {"weather": {}, "air": {}}

                # ── pause_zones: 지정 존 안에 있으면 폴링 중단 ─────────────
                # 자동 업데이트일 때만 적용
                # 재시작/수동 업데이트는 존 안에 있어도 항상 폴링 허용
                # device_tracker/person 기기에만 적용 (zone.* 기기는 무시)
                _location_entity = self.entry.data.get(CONF_LOCATION_ENTITY, "")
                if _reason == "자동 업데이트" and _is_mobile_entity(_location_entity):
                    _pause_zones = self.entry.options.get("pause_zones", [])
                    for _zone_id in _pause_zones:
                        _zone_state = self.hass.states.get(_zone_id)
                        if not _zone_state:
                            _LOGGER.debug("pause_zones: '%s' 엔티티 없음 → 스킵", _zone_id)
                            continue
                        try:
                            _z_lat = float(_zone_state.attributes["latitude"])
                            _z_lon = float(_zone_state.attributes["longitude"])
                            _z_rad = float(_zone_state.attributes.get("radius", 100)) / 1000  # m → km
                        except (KeyError, TypeError, ValueError):
                            _LOGGER.debug("pause_zones: '%s' 속성 오류 → 스킵", _zone_id)
                            continue
                        _dist = haversine(curr_lat, curr_lon, _z_lat, _z_lon)
                        if _dist <= _z_rad:
                            _LOGGER.debug(
                                "pause_zones: '%s' 반경 %.0fm 안 (%.0fm 거리) → 폴링 중단",
                                _zone_id, _z_rad * 1000, _dist * 1000,
                            )
                            return self._cached_data or {"weather": {}, "air": {}}

                # 기기 이동 여부 확인 (기존 테스트와의 호환성을 위해 외부에서 판단)
                is_moved = (
                    self._cached_area_lat is not None and
                    haversine(self._cached_area_lat, self._cached_area_lon, curr_lat, curr_lon) > 2.0
                )

                nx, ny, reg_id_temp, reg_id_land, warn_area_code = self._resolve_area_codes(
                    curr_lat, curr_lon
                )

                pollen_area_no, pollen_area_name = await self.find_pollen_area(curr_lat, curr_lon)
                uv_area_no, uv_area_name = await self.find_uv_area(curr_lat, curr_lon)
                new_data = await self.api.fetch_data(
                    lat=curr_lat, lon=curr_lon,
                    nx=nx, ny=ny,
                    reg_id_temp=reg_id_temp, reg_id_land=reg_id_land,
                    warn_area_code=warn_area_code,
                    pollen_area_no=pollen_area_no,
                    pollen_area_name=pollen_area_name,
                    uv_area_no=uv_area_no,
                    uv_area_name=uv_area_name,
                )
                if not new_data:
                    return self._cached_data

                # ── 단기/중기 미신청 감지 → 캐시 초기화 + 업데이트 중단 ──────
                short_unsub = new_data.get("_short_unsubscribed")
                mid_unsub   = new_data.get("_mid_unsubscribed")
                if short_unsub or mid_unsub:
                    which = "단기예보" if short_unsub else "중기예보"
                    _LOGGER.warning("핵심 API 미신청/중지 감지 [%s] → 캐시 초기화 및 업데이트 중단", which)
                    self.api._cache_forecast_map = {}
                    self.api._cache_mid_ta = {}
                    self.api._cache_mid_land = {}
                    self.api._cache_mid_tm_fc_dt = None
                    self._daily_date = self._daily_max_temp = self._daily_min_temp = None
                    self._wf_am_today = self._wf_pm_today = None
                    shared = self._shared_counts
                    shared["api_중지"] = which
                    empty = {"weather": {}, "air": self._cached_data.get("air", {}) if self._cached_data else {}, "pollen": self._cached_data.get("pollen") if self._cached_data else None, "uv": self._cached_data.get("uv") if self._cached_data else None}
                    self._cached_data = empty
                    self.async_update_listeners()
                    return empty

                weather = new_data.setdefault("weather", {})

                current_today = datetime.now(self.api.tz).date()
                is_new_day = (self._daily_date != current_today)

                if "raw_forecast" in new_data:
                    temp_changed = self._update_daily_temperatures(new_data["raw_forecast"])

                    reason = getattr(self, "_update_reason", "자동 업데이트")
                    is_scheduled = (reason == "자동 업데이트")

                    should_update_summary = is_scheduled or is_moved or is_new_day or (self._wf_pm_today is None)

                    api_am = weather.get("wf_am_today")
                    api_pm = weather.get("wf_pm_today")
                    summary_changed = False

                    if should_update_summary:
                        now_hour = datetime.now(self.api.tz).hour
                        if now_hour < 12:
                            if api_am: self._wf_am_today, summary_changed = api_am, True
                            if api_pm: self._wf_pm_today, summary_changed = api_pm, True
                        else:
                            if api_pm: self._wf_pm_today, summary_changed = api_pm, True
                            if self._wf_am_today is None and api_am:
                                self._wf_am_today, summary_changed = api_am, True

                    if temp_changed or summary_changed:
                        await self._save_daily_temps()

                weather.update({
                    "TMX_today": self._daily_max_temp,
                    "TMN_today": self._daily_min_temp,
                    "wf_am_today": self._wf_am_today,
                    "wf_pm_today": self._wf_pm_today,
                    "last_updated": datetime.now(timezone.utc),
                    "debug_nx": nx,
                    "debug_ny": ny,
                    "debug_lat": curr_lat,
                    "debug_lon": curr_lon,
                    "debug_warn_area_code": warn_area_code,
                })

                self._sync_today_forecast(weather)

                _REALTIME_KEYS = (
                    "TMP", "REH", "WSD", "VEC", "VEC_KOR", "POP", "apparent_temp"
                )
                if self._cached_data:
                    prev_weather = self._cached_data.get("weather", {})
                    for _key in _REALTIME_KEYS:
                        if _key in weather and weather[_key] in (None, "-", ""):
                            prev_val = prev_weather.get(_key)
                            if prev_val not in (None, "-", ""):
                                weather[_key] = prev_val

                sun_times = self._calc_sun_times(curr_lat, curr_lon,
                                                 datetime.now(self.api.tz))
                weather.update(sun_times)

                obs_cond, obs_attrs = self._eval_observation(
                    weather, datetime.now(self.api.tz), curr_lat, curr_lon
                )
                weather["observation_condition"] = obs_cond
                weather["observation_attrs"]     = obs_attrs

                self._cached_data = new_data
                await self._save_approved_apis()
                await self._save_api_calls()
                await self._save_station_cache()
                return new_data

            except Exception as exc:
                _LOGGER.error("업데이트 중 오류: %s", exc)
                return self._cached_data

    # ── 천문 시각 계산 ──────────────────────────────────────────────────────
    def _calc_sun_times(self, lat: float, lon: float, now: datetime) -> dict:
        today = now.date()

        if self._sf_eph is None or self._sf_ts is None:
            return self._sun_times or {}

        try:
            tz     = self.api.tz
            sf_loc = _wgs84.latlon(lat, lon)
            result = {}

            def _fmt(t: datetime) -> str:
                prefix = "오늘" if t.date() == today else "내일"
                return f"{prefix} {t.strftime('%H:%M')}"

            def _ts_range(dd):
                t0 = self._sf_ts.from_datetime(
                    datetime(dd.year, dd.month, dd.day, 0, 0, tzinfo=tz))
                t1 = self._sf_ts.from_datetime(
                    datetime(dd.year, dd.month, dd.day, 23, 59, tzinfo=tz))
                return t0, t1

            f_ss = _almanac.sunrise_sunset(self._sf_eph, sf_loc)
            for offset in (0, 1, 2):
                t0, t1 = _ts_range(today + timedelta(days=offset))
                for t, e in zip(*_almanac.find_discrete(t0, t1, f_ss)):
                    local_t = t.astimezone(tz)
                    if local_t > now:
                        if e and "sunrise" not in result:
                            result["sunrise"] = _fmt(local_t)
                        elif not e and "sunset" not in result:
                            result["sunset"] = _fmt(local_t)
                if "sunrise" in result and "sunset" in result:
                    break

            _TW_MAP = {(2,3):"dawn", (3,2):"dusk", (0,1):"astro_dawn", (1,0):"astro_dusk"}
            f_tw = _almanac.dark_twilight_day(self._sf_eph, sf_loc)
            for offset in (0, 1, 2):
                t0, t1 = _ts_range(today + timedelta(days=offset))
                times, events = _almanac.find_discrete(t0, t1, f_tw)
                prev_e = int(f_tw(t0))
                for t, cur_e in zip(times, events):
                    local_t = t.astimezone(tz)
                    if local_t > now:
                        key = _TW_MAP.get((prev_e, int(cur_e)))
                        if key and key not in result:
                            result[key] = _fmt(local_t)
                    prev_e = int(cur_e)
                if all(k in result for k in ("dawn", "dusk", "astro_dawn", "astro_dusk")):
                    break

            t_now = self._sf_ts.from_datetime(now)
            phase_deg = _almanac.moon_phase(self._sf_eph, t_now).degrees
            result["moon_phase"]        = self._moon_phase_name(phase_deg)
            result["moon_illumination"] = round(
                _almanac.fraction_illuminated(self._sf_eph, "moon", t_now) * 100)

            f_rs = _almanac.risings_and_settings(
                self._sf_eph, self._sf_eph["Moon"], sf_loc)
            next_rise = next_set = None
            for offset in (0, 1, 2):
                t0, t1 = _ts_range(today + timedelta(days=offset))
                for t, e in zip(*_almanac.find_discrete(t0, t1, f_rs)):
                    local_t = t.astimezone(tz)
                    if local_t > now:
                        if e and next_rise is None:
                            next_rise = local_t
                        elif not e and next_set is None:
                            next_set = local_t
                if next_rise and next_set:
                    break
            result["moonrise"] = _fmt(next_rise) if next_rise else None
            result["moonset"]  = _fmt(next_set)  if next_set  else None

            self._sun_cache_date = today
            self._sun_cache_lat  = lat
            self._sun_cache_lon  = lon
            self._sun_times      = result
            _LOGGER.debug("천문 시각 갱신: %s (lat=%.4f, lon=%.4f)", today, lat, lon)

        except Exception as e:
            _LOGGER.warning("천문 시각 계산 실패: %s", e)
            result = self._sun_times

        return result

    @staticmethod
    def _moon_phase_name(deg: float) -> str:
        d = deg % 360
        if   d <  22.5: return "삭"
        elif d <  67.5: return "초승달"
        elif d < 112.5: return "상현달"
        elif d < 157.5: return "준상현달"
        elif d < 202.5: return "보름달"
        elif d < 247.5: return "준하현달"
        elif d < 292.5: return "하현달"
        elif d < 337.5: return "그믐달"
        return "삭"

    _OBS_ORDER = ["관측불가", "불량", "보통", "우수", "최우수"]

    @staticmethod
    def _obs_min(cond_a: str, cond_b: str) -> str:
        order = KMAWeatherUpdateCoordinator._OBS_ORDER
        a_idx = order.index(cond_a) if cond_a in order else 0
        b_idx = order.index(cond_b) if cond_b in order else 0
        return order[min(a_idx, b_idx)]

    def _eval_observation(
        self, weather: dict, now: "datetime", lat: float, lon: float
    ) -> "tuple[str, dict]":
        condition_eng = weather.get("current_condition", "")
        wsd           = weather.get("WSD")
        moon_phase    = weather.get("moon_phase", "")
        illum_raw     = weather.get("moon_illumination", None)
        condition_kor = weather.get("current_condition_kor") or None

        try:
            illum_int = int(illum_raw) if illum_raw is not None else None
        except (TypeError, ValueError):
            illum_int = None
        illum_str = f"{illum_int}%" if illum_int is not None else "-"

        moon_alt_str = "-"
        sun_is_up    = True
        moon_up      = False
        moon_alt_deg = None

        def _fallback_attrs(day_night: str = "-") -> dict:
            return {
                "풍속":    f"{wsd} m/s" if wsd is not None else "-",
                "달_조명율": illum_str,
                "달_고도":  "-",
                "은하수_고도": "-",
                "날씨":    condition_kor or "-",
                "주야간":  day_night,
                "달_위상": moon_phase,
                "판단사유": "-",
            }

        try:
            if self._sf_eph is None or self._sf_ts is None:
                return "분석불가", _fallback_attrs()

            sf_loc = _wgs84.latlon(lat, lon)
            t_now  = self._sf_ts.from_datetime(now)

            sun_astr = (self._sf_eph["Earth"] + sf_loc).at(t_now).observe(self._sf_eph["Sun"])
            sun_alt, _, _ = sun_astr.apparent().altaz()
            sun_is_up = sun_alt.degrees > -18

            moon_astr = (self._sf_eph["Earth"] + sf_loc).at(t_now).observe(self._sf_eph["Moon"])
            moon_alt, _, _ = moon_astr.apparent().altaz()
            moon_alt_deg = moon_alt.degrees
            moon_alt_str = f"{moon_alt_deg:.1f}°"
            moon_up = moon_alt_deg > 7.0

            from skyfield.api import Star as _Star
            _mw_center = _Star(ra_hours=(17 + 45/60 + 40.04/3600),
                               dec_degrees=-(29 + 0/60 + 28.1/3600))
            mw_astr = (self._sf_eph["Earth"] + sf_loc).at(t_now).observe(_mw_center)
            mw_alt, _, _ = mw_astr.apparent().altaz()
            mw_alt_deg = mw_alt.degrees
            mw_alt_str = f"{mw_alt_deg:.1f}°"

        except Exception:
            mw_alt_str = "-"
            return "분석불가", _fallback_attrs()

        day_night = "주간" if sun_is_up else "야간"

        _order = KMAWeatherUpdateCoordinator._OBS_ORDER

        if sun_is_up:
            cond_daytime = "관측불가"
        else:
            cond_daytime = "최우수"

        if condition_eng in {"rainy", "pouring", "snowy", "snowy-rainy", "cloudy"}:
            cond_weather = "관측불가"
        elif condition_eng == "partlycloudy":
            cond_weather = "불량"
        else:
            cond_weather = "최우수"

        if not moon_up or illum_int == 0:
            cond_moon = "최우수"
        elif illum_int is None:
            cond_moon = "최우수"
        elif illum_int <= 25:
            cond_moon = "우수"
        elif illum_int <= 50:
            cond_moon = "보통"
        elif illum_int <= 75:
            cond_moon = "불량"
        else:
            cond_moon = "관측불가"

        wsd_val = _safe_float(wsd)
        if wsd_val is None:
            cond_wind = None
        elif wsd_val < 1.5:
            cond_wind = "우수"
        elif wsd_val < 3.0:
            cond_wind = "최우수"
        elif wsd_val < 5.0:
            cond_wind = "보통"
        elif wsd_val < 8.0:
            cond_wind = "불량"
        else:
            cond_wind = "관측불가"

        all_conds = {
            "주야간":    cond_daytime,
            "날씨":      cond_weather,
            "달 조명율": cond_moon,
        }
        if cond_wind is not None:
            all_conds["풍속"] = cond_wind

        final_cond = min(all_conds.values(), key=lambda c: _order.index(c))
        final_idx  = _order.index(final_cond)

        reasons = [name for name, cond in all_conds.items()
                   if _order.index(cond) == final_idx]

        if cond_daytime == "관측불가" and sun_is_up:
            reasons = ["주야간"]
        elif final_cond == "최우수":
            reasons = []

        obs_reason = ", ".join(reasons) if reasons else "-"

        mw_suffix = ""
        if final_cond in ("최우수", "우수") and not sun_is_up:
            try:
                if mw_alt_deg >= 20:
                    mw_suffix = "(은하수)"
            except Exception:
                pass

        display_cond = f"{final_cond}{mw_suffix}" if mw_suffix else final_cond

        attrs = {
            "풍속":    f"{wsd} m/s" if wsd is not None else "-",
            "달_조명율": illum_str,
            "달_고도":  moon_alt_str,
            "은하수_고도": mw_alt_str,
            "날씨":    condition_kor or "-",
            "주야간":  day_night,
            "달_위상": moon_phase,
            "판단사유": obs_reason,
        }

        return display_cond, attrs

    # ── 날짜 지정 천문 계산 (HA 서비스용) ──────────────────────────────────
    async def calc_astronomical_for_date(
        self, lat: float, lon: float, target_date, eval_dt: "datetime | None" = None
    ) -> dict:
        if self._sf_eph is None or self._sf_ts is None:
            return {"error": "skyfield 라이브러리가 준비되지 않았습니다"}
        try:
            tz = self.api.tz
            sf_loc = _wgs84.latlon(lat, lon)
            result: dict = {}

            def _hm(t) -> str:
                return t.astimezone(tz).strftime("%H:%M")

            t0 = self._sf_ts.from_datetime(
                datetime(target_date.year, target_date.month, target_date.day, 0, 0, tzinfo=tz))
            t1 = self._sf_ts.from_datetime(
                datetime(target_date.year, target_date.month, target_date.day, 23, 59, tzinfo=tz))

            f_ss = _almanac.sunrise_sunset(self._sf_eph, sf_loc)
            sunrise = sunset = None
            for t, e in zip(*_almanac.find_discrete(t0, t1, f_ss)):
                local_t = t.astimezone(tz)
                if e and sunrise is None:
                    sunrise = _hm(local_t)
                elif not e and sunset is None:
                    sunset = _hm(local_t)
            result["sunrise"] = sunrise
            result["sunset"] = sunset

            _TW_MAP = {(2, 3): "dawn", (3, 2): "dusk", (0, 1): "astro_dawn", (1, 0): "astro_dusk"}
            f_tw = _almanac.dark_twilight_day(self._sf_eph, sf_loc)
            prev_e = int(f_tw(t0))
            for t, cur_e in zip(*_almanac.find_discrete(t0, t1, f_tw)):
                local_t = t.astimezone(tz)
                key = _TW_MAP.get((prev_e, int(cur_e)))
                if key and key not in result:
                    result[key] = _hm(local_t)
                prev_e = int(cur_e)

            t_noon = self._sf_ts.from_datetime(
                datetime(target_date.year, target_date.month, target_date.day, 12, 0, tzinfo=tz))
            phase_deg = _almanac.moon_phase(self._sf_eph, t_noon).degrees
            illum = round(_almanac.fraction_illuminated(self._sf_eph, "moon", t_noon) * 100)
            result["moon_phase"] = KMAWeatherUpdateCoordinator._moon_phase_name(phase_deg)
            result["moon_illumination"] = illum

            f_rs = _almanac.risings_and_settings(self._sf_eph, self._sf_eph["Moon"], sf_loc)
            moonrise = moonset = None
            for t, e in zip(*_almanac.find_discrete(t0, t1, f_rs)):
                local_t = t.astimezone(tz)
                if e and moonrise is None:
                    moonrise = _hm(local_t)
                elif not e and moonset is None:
                    moonset = _hm(local_t)
            result["moonrise"] = moonrise
            result["moonset"] = moonset

            weather_for_obs: dict = {
                "moon_illumination": illum,
                "moon_phase": result.get("moon_phase", ""),
            }
            weather_source = "천문만"
            weather_kor: str = "API 조회 불가"

            if "short" in self.api._approved_apis:
                try:
                    nx, ny = convert_grid(lat, lon)
                    now_kst = datetime.now(tz)
                    adj = now_kst - timedelta(minutes=10)
                    valid_hours = [h for h in [2, 5, 8, 11, 14, 17, 20, 23] if h <= adj.hour]
                    base_h = max(valid_hours) if valid_hours else 23
                    base_d = adj.strftime("%Y%m%d") if valid_hours else (adj - timedelta(days=1)).strftime("%Y%m%d")

                    short_data = await self.api._fetch(
                        "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst",
                        {"serviceKey": self.api.api_key, "dataType": "JSON",
                         "base_date": base_d, "base_time": f"{base_h:02d}00",
                         "nx": nx, "ny": ny, "numOfRows": 1500},
                    )
                    items = (short_data or {}).get("response", {}).get("body", {}).get("items", {}).get("item", [])
                    if items:
                        ref_dt = eval_dt or datetime(
                            target_date.year, target_date.month, target_date.day, 12, 0, tzinfo=tz)
                        ref_date_str = ref_dt.strftime("%Y%m%d")
                        ref_time_str = f"{ref_dt.hour:02d}00"

                        forecast_map: dict = {}
                        for it in items:
                            forecast_map.setdefault(
                                it["fcstDate"], {}
                            ).setdefault(it["fcstTime"], {})[it["category"]] = it["fcstValue"]

                        day_data = forecast_map.get(ref_date_str, {})
                        times = sorted(day_data.keys())
                        best_t = next((t for t in times if t >= ref_time_str), times[-1] if times else None)
                        if best_t:
                            slot = day_data[best_t]
                            sky = slot.get("SKY")
                            pty = slot.get("PTY")
                            kor = self.api._get_sky_kor(sky, pty)
                            cond_eng = self.api.kor_to_condition(kor)
                            if cond_eng:
                                weather_for_obs["current_condition"] = cond_eng
                                weather_for_obs["current_condition_kor"] = kor
                                weather_source = "날씨+천문"
                                weather_kor = kor
                            wsd_val = slot.get("WSD")
                            if wsd_val is None:
                                for t_key in sorted(day_data.keys()):
                                    v = day_data[t_key].get("WSD")
                                    if v is not None:
                                        wsd_val = v
                                        break
                            if wsd_val is not None:
                                weather_for_obs["WSD"] = wsd_val
                            _LOGGER.debug(
                                "천문 액션 단기예보 조회 성공: (%s, %s) → %s (%s)",
                                lat, lon, kor, ref_dt.strftime("%Y%m%d %H:%M")
                            )
                except Exception as e:
                    _LOGGER.warning("천문 액션 단기예보 조회 실패 (날씨 무시): %s", e)
            else:
                _LOGGER.debug("단기예보 API 미승인 → 달 조명율+달 고도+태양고도만으로 관측 조건 평가")

            obs_dt = eval_dt or datetime(
                target_date.year, target_date.month, target_date.day, 12, 0, tzinfo=tz)
            obs_cond, obs_attrs = self._eval_observation(weather_for_obs, obs_dt, lat, lon)
            try:
                from skyfield.api import Star as _Star
                _mw_center = _Star(ra_hours=(17 + 45/60 + 40.04/3600),
                                   dec_degrees=-(29 + 0/60 + 28.1/3600))
                t_eval = self._sf_ts.from_datetime(obs_dt)
                sf_loc_action = _wgs84.latlon(lat, lon)
                mw_astr = (self._sf_eph["Earth"] + sf_loc_action).at(t_eval).observe(_mw_center)
                mw_alt_action, _, _ = mw_astr.apparent().altaz()
                result["milkyway_altitude"] = round(mw_alt_action.degrees, 1)
            except Exception:
                result["milkyway_altitude"] = None

            result["observation_condition"] = obs_cond
            result["observation_attrs"]     = obs_attrs
            result["weather_source"]        = weather_source
            result["weather_condition"]     = weather_kor
            return result

        except Exception as e:
            _LOGGER.error("날짜별 천문 계산 실패: %s", e)
            return {"error": str(e)}

    # ── 위치 결정 ───────────────────────────────────────────────────────────
    def _resolve_location(self) -> tuple:
        entity_id = self.entry.data.get(CONF_LOCATION_ENTITY, "")
        state = self.hass.states.get(entity_id) if entity_id else None
        if state:
            lat_attr = state.attributes.get("latitude")
            lon_attr = state.attributes.get("longitude")
            if lat_attr is not None and lon_attr is not None:
                try:
                    lat, lon = float(lat_attr), float(lon_attr)
                    if is_korean_coord_loose(lat, lon):
                        self._last_lat, self._last_lon = lat, lon
                        return lat, lon
                except Exception:
                    pass
        if self._last_lat is not None:
            return self._last_lat, self._last_lon
        try:
            lat, lon = float(self.hass.config.latitude), float(self.hass.config.longitude)
            if is_korean_coord_loose(lat, lon):
                return lat, lon
        except Exception:
            pass
        return None, None
