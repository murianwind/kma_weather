import logging
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.const import UnitOfTemperature, PERCENTAGE, UnitOfSpeed, UnitOfPrecipitationDepth, EntityCategory
try:
    # HA 2025.x 이후: 신규 상수. 구버전 HA에는 없을 수 있어 문자열로 폴백한다
    # (CONCENTRATION_PARTS_PER_MILLION은 2027.8에 제거 예정이라 쓰지 않음).
    from homeassistant.const import UnitOfRatio
    _PPM_UNIT = UnitOfRatio.PARTS_PER_MILLION
except ImportError:
    _PPM_UNIT = "ppm"
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.core import callback
from datetime import date
from .const import DOMAIN, CONF_PREFIX, CONF_EXPIRE_DATE
from .api_kma import KMAWeatherAPI

_LOGGER = logging.getLogger(__name__)

# [이름, 단위, 아이콘, device_class, entity_id접미, entity_category]
SENSOR_TYPES = {
    "TMP":                ["현재온도",        UnitOfTemperature.CELSIUS,          "mdi:thermometer",             SensorDeviceClass.TEMPERATURE, "temperature",          None],
    "REH":                ["현재습도",        PERCENTAGE,                          "mdi:water-percent",           SensorDeviceClass.HUMIDITY,    "humidity",             None],
    "WSD":                ["현재풍속",        UnitOfSpeed.METERS_PER_SECOND,       "mdi:weather-windy",           SensorDeviceClass.WIND_SPEED,  "wind_speed",           None],
    "VEC_KOR":            ["현재풍향",        None,                                "mdi:compass",                 None,                          "wind_direction",       None],
    "POP":                ["강수확률",        PERCENTAGE,                          "mdi:umbrella-outline",        None,                          "precipitation_prob",   None],
    "precip_amount":      ["현재 예상 강수량", UnitOfPrecipitationDepth.MILLIMETERS, "mdi:weather-pouring",        SensorDeviceClass.PRECIPITATION, "precip_amount",      None],
    "apparent_temp":      ["체감온도",        UnitOfTemperature.CELSIUS,          "mdi:thermometer-lines",       SensorDeviceClass.TEMPERATURE, "apparent_temperature", None],
    "rain_start_time":    ["강수시작시간",     None,                                "mdi:clock-outline",           None,                          "rain_start",           None],
    "current_condition_kor": ["현재날씨",    None,                                "mdi:weather-cloudy",          None,                          "condition",            None],
    "pm10Value":          ["미세먼지 농도",   "µg/m³",                             "mdi:blur",                    SensorDeviceClass.PM10,        "pm10",                 None],
    "pm10Grade":          ["미세먼지 등급",   None,                                "mdi:check-circle-outline",    None,                          "pm10_grade",           None],
    "pm25Value":          ["초미세먼지 농도", "µg/m³",                             "mdi:blur-linear",             SensorDeviceClass.PM25,        "pm25",                 None],
    "pm25Grade":          ["초미세먼지 등급", None,                                "mdi:check-circle-outline",    None,                          "pm25_grade",           None],
    "o3Value":            ["오존 농도",       _PPM_UNIT,                           "mdi:weather-sunny-alert",     SensorDeviceClass.OZONE,       "o3",                   None],
    "o3Grade":            ["오존 등급",       None,                                "mdi:check-circle-outline",    None,                          "o3_grade",             None],
    "address":            ["현재 위치",       None,                                "mdi:map-marker",              None,                          "location",             EntityCategory.DIAGNOSTIC],
    "last_updated":       ["업데이트 시간",   None,                                "mdi:update",                  SensorDeviceClass.TIMESTAMP,   "last_updated",         EntityCategory.DIAGNOSTIC],
    "api_expire":         ["API 잔여일수",    "일",                                "mdi:key-alert",               None,                          "api_expire",           EntityCategory.DIAGNOSTIC],
    "TMX_today":          ["오늘최고온도",    UnitOfTemperature.CELSIUS,          "mdi:thermometer-chevron-up",  SensorDeviceClass.TEMPERATURE, "today_temp_max",       None],
    "TMN_today":          ["오늘최저온도",    UnitOfTemperature.CELSIUS,          "mdi:thermometer-chevron-down",SensorDeviceClass.TEMPERATURE, "today_temp_min",       None],
    "wf_am_today":        ["오늘오전날씨",    None,                                "mdi:weather-partly-cloudy",   None,                          "today_condition_am",   None],
    "wf_pm_today":        ["오늘오후날씨",    None,                                "mdi:weather-cloudy",          None,                          "today_condition_pm",   None],
    "TMX_tomorrow":       ["내일최고온도",    UnitOfTemperature.CELSIUS,          "mdi:thermometer-chevron-up",  SensorDeviceClass.TEMPERATURE, "tomorrow_temp_max",    None],
    "TMN_tomorrow":       ["내일최저온도",    UnitOfTemperature.CELSIUS,          "mdi:thermometer-chevron-down",SensorDeviceClass.TEMPERATURE, "tomorrow_temp_min",    None],
    "wf_am_tomorrow":     ["내일오전날씨",    None,                                "mdi:weather-partly-cloudy",   None,                          "tomorrow_condition_am",None],
    "wf_pm_tomorrow":     ["내일오후날씨",    None,                                "mdi:weather-cloudy",          None,                          "tomorrow_condition_pm",None],
    "warning":            ["기상특보",        None,                                "mdi:alert-outline",           None,                          "warning",              None],
    "dawn":               ["다음 새벽",         None,   "mdi:weather-moonset",             None,  "dawn",               None],
    "sunrise":            ["다음 일출",          None,   "mdi:weather-sunset-up",           None,  "sunrise",            None],
    "sunset":             ["다음 일몰",          None,   "mdi:weather-sunset-down",         None,  "sunset",             None],
    "dusk":               ["다음 황혼",          None,   "mdi:weather-sunset",              None,  "dusk",               None],
    "astro_dawn":         ["다음 천문관측 종료",  None,   "mdi:telescope",                   None,  "astro_dawn",         None],
    "astro_dusk":         ["다음 천문관측 시작",  None,   "mdi:telescope",                   None,  "astro_dusk",         None],
    "moon_phase":         ["달 위상",            None,   "mdi:moon-waning-gibbous",         None,  "moon_phase",         None],
    "moon_illumination":  ["달 조명율",          PERCENTAGE, "mdi:brightness-percent",      None,  "moon_illumination",  None],
    "moonrise":           ["다음 월출",          None,   "mdi:weather-moonset-up",          None,  "moonrise",           None],
    "moonset":            ["다음 월몰",          None,   "mdi:weather-moonset-down",        None,  "moonset",            None],
    "observation_condition": ["천문 관측 조건",  None,   "mdi:telescope",                   None,  "observation_condition", None],
    "pollen":             ["꽃가루 농도",      None,                                "mdi:flower-pollen-outline",   None,                          "pollen",               None],
    "uv_value":           ["자외선지수",      None,                                "mdi:sun-wireless-outline",    None,                          "uv_value",              None],
    "uv_grade":           ["자외선지수 등급", None,                                "mdi:check-circle-outline",    None,                          "uv_grade",              None],
    "api_calls_today":    ["오늘 API 호출 수", "회",                                "mdi:counter",                 None,                          "api_calls_today",      EntityCategory.DIAGNOSTIC],
}

# ── API별 센서 그룹 ───────────────────────────────────────────────────────────
# None: API 신청 여부와 무관하게 항상 등록
# 키 문자열: 해당 API가 승인됐을 때만 등록
SENSOR_API_GROUPS: dict[str | None, list[str]] = {
    None: [
        "api_expire", "last_updated", "address", "api_calls_today",
        "dawn", "sunrise", "sunset", "dusk",
        "astro_dawn", "astro_dusk",
        "moon_phase", "moon_illumination", "moonrise", "moonset",
        "observation_condition",
    ],
    "short": [
        "TMP", "REH", "WSD", "VEC_KOR", "POP", "apparent_temp", "precip_amount",
        "rain_start_time", "current_condition_kor",
        "TMX_today", "TMN_today", "wf_am_today", "wf_pm_today",
        "TMX_tomorrow", "TMN_tomorrow", "wf_am_tomorrow", "wf_pm_tomorrow",
    ],
    "air": [
        "pm10Value", "pm10Grade", "pm25Value", "pm25Grade", "o3Value", "o3Grade",
    ],
    "warning": [
        "warning",
    ],
    "pollen": [
        "pollen",
    ],
    "uv": [
        "uv_value", "uv_grade",
    ],
}


def _eligible_sensor_types(coordinator) -> list[str]:
    """현재 승인된 API 기준으로 등록해야 할 센서 타입 목록을 반환한다."""
    approved = coordinator.api._approved_apis
    types: list[str] = list(SENSOR_API_GROUPS.get(None, []))
    for api_key, sensor_types in SENSOR_API_GROUPS.items():
        if api_key is not None and api_key in approved:
            types.extend(sensor_types)
    return types


async def async_setup_entry(hass, entry, async_add_entities):
    """센서 엔티티 등록 (승인된 API 기준 동적 등록)"""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    prefix = entry.options.get(CONF_PREFIX, entry.data.get(CONF_PREFIX, "kma"))

    if not hasattr(coordinator, "_registered_sensor_types"):
        coordinator._registered_sensor_types = set()

    def _make_sensors(types: list[str]) -> list:
        return [
            KMACustomSensor(coordinator, st, prefix, entry)
            for st in types
            if st not in coordinator._registered_sensor_types and st in SENSOR_TYPES
        ]

    initial_types = _eligible_sensor_types(coordinator)
    initial_entities = _make_sensors(initial_types)
    for e in initial_entities:
        coordinator._registered_sensor_types.add(e._type)
    async_add_entities(initial_entities)

    @callback
    def _check_new_sensors():
        eligible = _eligible_sensor_types(coordinator)
        new_types = [t for t in eligible if t not in coordinator._registered_sensor_types]
        if not new_types:
            return
        new_entities = _make_sensors(new_types)
        for e in new_entities:
            coordinator._registered_sensor_types.add(e._type)
        if new_entities:
            _LOGGER.info("새 API 승인 감지: 센서 %d개 추가 (%s)", len(new_entities),
                         ", ".join(e._type for e in new_entities))
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_check_new_sensors))


class KMACustomSensor(CoordinatorEntity, RestoreEntity, SensorEntity):
    """기상청 커스텀 센서 클래스"""
    _attr_has_entity_name = True

    def __init__(self, coordinator, sensor_type, prefix, entry):
        super().__init__(coordinator)
        self._type = sensor_type
        self._entry = entry

        details = SENSOR_TYPES[sensor_type]
        self.entity_id = f"sensor.{prefix}_{details[4]}"
        self._attr_name = details[0]
        self._attr_native_unit_of_measurement = details[1]
        self._attr_icon = details[2]
        self._attr_device_class = details[3]
        self._attr_unique_id = f"{entry.entry_id}_{sensor_type}"
        self._attr_entity_category = details[5]

        if sensor_type == "api_calls_today":
            self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        elif sensor_type == "uv_value":
            # 자외선지수는 공식 단위가 없는 순수 수치 지수라 unit은 비워뒀지만,
            # 숫자값이므로 히스토리 그래프 대상이 되려면 state_class는 필요하다.
            self._attr_state_class = SensorStateClass.MEASUREMENT
        elif details[1] is not None and sensor_type not in ("api_expire",):
            self._attr_state_class = SensorStateClass.MEASUREMENT

        if sensor_type == "precip_amount":
            # 속성이 시각 키(00시~23시) 회전 윈도우라서, 상태값과 각 시간대 값이
            # 모두 이전과 같으면 회전 후 dict도 동일해져(파이썬 dict 비교는 순서
            # 무시) HA가 상태 기록을 스킵하고 속성 시간이 밀리지 않는 문제가 있음.
            # force_update로 매 갱신마다 기록을 강제해 속성 회전을 보장한다.
            self._attr_force_update = True

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Murianwind",
            model="KMA Weather Service",
        )

    _MOON_PHASE_ICONS = {
        "삭":       "mdi:moon-new",
        "초승달":   "mdi:moon-waxing-crescent",
        "상현달":   "mdi:moon-first-quarter",
        "준상현달": "mdi:moon-waxing-gibbous",
        "보름달":   "mdi:moon-full",
        "준하현달": "mdi:moon-waning-gibbous",
        "하현달":   "mdi:moon-last-quarter",
        "그믐달":   "mdi:moon-waning-crescent",
    }

    _OBSERVATION_ICONS_BY_REASON = {
        "강수":     "mdi:weather-rainy",
        "흐림":     "mdi:weather-cloudy",
        "주간":     "mdi:weather-sunny",
        "":         None,
        "분석불가": "mdi:help-circle-outline",
    }
    _OBSERVATION_ICONS_BY_CONDITION = {
        "최우수":   "mdi:star-shooting",
        "우수":     "mdi:star",
        "보통":     "mdi:star-half-full",
        "불량":     "mdi:moon-waning-gibbous",
        "관측불가": "mdi:telescope",
        "분석불가": "mdi:help-circle-outline",
    }

    _POLLEN_ICONS = {
        "좋음":     "mdi:flower-pollen-outline",
        "보통":     "mdi:flower-pollen",
        "나쁨":     "mdi:face-mask",
        "매우나쁨": "mdi:biohazard",
    }

    _WEATHER_COND_ICONS: dict[str, str] = {
        "맑음":     "mdi:weather-sunny",
        "구름많음": "mdi:weather-partly-cloudy",
        "흐림":     "mdi:weather-cloudy",
        "비":       "mdi:weather-rainy",
        "비/눈":    "mdi:weather-snowy-rainy",
        "눈":       "mdi:weather-snowy",
        "소나기":   "mdi:weather-pouring",
        "빗방울":   "mdi:weather-rainy",
        "눈날림":   "mdi:weather-snowy",
    }
    _WEATHER_COND_TYPES = frozenset({
        "current_condition_kor", "wf_am_today", "wf_pm_today",
        "wf_am_tomorrow", "wf_pm_tomorrow",
    })

    @property
    def icon(self) -> str:
        if self.coordinator.data:
            w = self.coordinator.data.get("weather", {})
            # 날씨 상태값 기반 아이콘
            if self._type in self._WEATHER_COND_TYPES:
                val = w.get(self._type)
                if val and val in self._WEATHER_COND_ICONS:
                    return self._WEATHER_COND_ICONS[val]
                return self._attr_icon
            if self._type == "moon_phase":
                phase = w.get("moon_phase")
                if phase and phase in self._MOON_PHASE_ICONS:
                    return self._MOON_PHASE_ICONS[phase]

            elif self._type == "observation_condition":
                attrs = w.get("observation_attrs", {})
                weather_state = attrs.get("날씨", "")
                day_night = attrs.get("주야간", "야간")
                cond = w.get("observation_condition", "")
                if day_night == "주간":
                    return "mdi:weather-sunny"
                if weather_state in ("rainy", "pouring", "snowy", "snowy-rainy", "cloudy", "강수", "흐림"):
                    return self._OBSERVATION_ICONS_BY_REASON.get(
                        "강수" if weather_state in ("rainy","pouring","snowy","snowy-rainy") else "흐림",
                        self._attr_icon
                    )
                return self._OBSERVATION_ICONS_BY_CONDITION.get(cond, self._attr_icon)

            elif self._type == "pollen":
                pollen = self.coordinator.data.get("pollen")
                if not pollen:
                    return self._attr_icon
                worst = pollen.get("worst")
                if worst is None:
                    return self._attr_icon
                return self._POLLEN_ICONS.get(worst, self._attr_icon)

        return self._attr_icon

    @property
    def available(self) -> bool:
        """API 미신청/중지 시 unavailable 반환."""
        if not super().available:
            return False
        if not self.coordinator.data:
            return False
        if self._type in ("api_expire", "api_calls_today"):
            return True

        # SENSOR_API_GROUPS에서 API별 센서 목록 파생 → 중복 정의 없음
        for api_key, sensor_types in SENSOR_API_GROUPS.items():
            if api_key is not None and self._type in sensor_types:
                if api_key == "pollen":
                    return self.coordinator.data.get("pollen") is not None
                if api_key == "warning":
                    w = self.coordinator.data.get("weather", {})
                    return w.get("warning") is not None
                return api_key in self.coordinator.api._approved_apis

        return True

    async def async_added_to_hass(self) -> None:
        """HA 재시작 후 이전 상태 복원."""
        await super().async_added_to_hass()
        if self.coordinator.data:
            return  # 이미 데이터 있으면 복원 불필요
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in ("unknown", "unavailable"):
            self._attr_native_value = last_state.state

    @property
    def native_value(self):
        if self._type == "api_expire":
            exp = self._entry.options.get(CONF_EXPIRE_DATE) or self._entry.data.get(CONF_EXPIRE_DATE)
            try:
                return (date.fromisoformat(exp) - date.today()).days
            except (ValueError, TypeError):
                return None

        if self._type == "api_calls_today":
            return self.coordinator.api_call_total()

        if not self.coordinator.data:
            return None

        w = self.coordinator.data.get("weather", {})
        a = self.coordinator.data.get("air", {})

        if self._type == "pollen":
            pollen = self.coordinator.data.get("pollen")
            if pollen is None:
                # 미신청/만료 → unavailable
                return None
            worst = pollen.get("worst")
            if worst is None:
                # 데이터 없음 (rc=99 등) → unknown
                return None
            return worst

        if self._type in ("uv_value", "uv_grade"):
            uv = self.coordinator.data.get("uv")
            if uv is None:
                # 미신청/만료 → unavailable
                return None
            if self._type == "uv_grade":
                return uv.get("grade")
            v = uv.get("value")
            if v in (None, "-", ""):
                return None
            try:
                f_val = float(v)
                return int(f_val) if f_val == int(f_val) else f_val
            except (ValueError, TypeError):
                return None

        if self._type == "TMN_today":
            val = self.coordinator._daily_min_temp
        elif self._type == "TMX_today":
            val = self.coordinator._daily_max_temp
        else:
            val = w.get(self._type) if self._type in w else a.get(self._type)

        if val in [None, "-", ""]:
            return None

        unit = self._attr_native_unit_of_measurement
        if unit is not None:
            try:
                f_val = float(val)
                return int(f_val) if f_val == int(f_val) else f_val
            except (ValueError, TypeError):
                return None

        return val

    @property
    def extra_state_attributes(self):
        # ── API 호출 카운터 센서: coordinator.data 유무와 무관하게 항상 반환 ────
        if self._type == "api_calls_today":
            # 전체 기기 합산 공유 카운터 사용
            counts = self.coordinator._shared_counts
            attrs = {
                "단기예보":        counts.get("단기예보", 0),
                "중기예보":        counts.get("중기예보", 0),
                "에어코리아_측정소": counts.get("에어코리아_측정소", 0),
                "에어코리아_대기":  counts.get("에어코리아_대기", 0),
                "기상특보":        counts.get("기상특보", 0),
                "꽃가루":          counts.get("꽃가루", 0),
                "자외선지수":       counts.get("자외선지수", 0),
                "집계일":          counts.get("date") or "-",
                "마지막_호출_이유": counts.get("last_reason") or "-",
            }
            api_중지 = counts.get("api_중지")
            if api_중지:
                attrs["API_중지_감지"] = f"{api_중지} 미신청 또는 중지됨"
            return attrs

        if not self.coordinator.data:
            return None

        w = self.coordinator.data.get("weather", {})
        a = self.coordinator.data.get("air", {})

        # ── location 센서 (address) ──────────────────────────────────────────
        if self._type == "address":
            attrs: dict = {}

            # 단기예보 API 승인 시에만 격자 좌표 표시
            approved = self.coordinator.api._approved_apis
            if "short" in approved:
                nx = w.get("debug_nx")
                ny = w.get("debug_ny")
                if nx is not None:
                    attrs["short_term_nx"] = nx
                if ny is not None:
                    attrs["short_term_ny"] = ny
                # coordinator 캐시에서 중기예보 구역코드 읽기
                reg_temp = getattr(self.coordinator, "_cached_reg_id_temp", None)
                reg_land = getattr(self.coordinator, "_cached_reg_id_land", None)
                if reg_temp:
                    attrs["reg_id_temp"] = reg_temp
                if reg_land:
                    attrs["reg_id_land"] = reg_land

            # 에어코리아 API 승인 시에만 측정소명 표시
            if "air" in approved:
                station = a.get("station")
                if station:
                    attrs["air_korea_station"] = station

            # 좌표는 항상 표시 (천문 계산에도 필요, API 무관)
            lat = w.get("debug_lat")
            lon = w.get("debug_lon")
            if lat is not None:
                attrs["latitude"] = lat
            if lon is not None:
                attrs["longitude"] = lon

            # 기상특보 API 승인 시에만 특보구역코드 표시
            if "warning" in approved:
                warn_code = w.get("debug_warn_area_code")
                if warn_code:
                    attrs["warn_area_code"] = warn_code

            # 꽃가루 API 승인 시에만 꽃가루 조회 지역 표시
            if "pollen" in approved:
                pollen = self.coordinator.data.get("pollen") or {}
                area_name = pollen.get("area_name")
                area_no   = pollen.get("area_no")
                if area_name:
                    loc = f"{area_name}({area_no})" if area_no else area_name
                    attrs["pollen_location"] = loc

            return attrs if attrs else None

        # ── 꽃가루 센서 ──────────────────────────────────────────────────────
        if self._type == "pollen":
            pollen = self.coordinator.data.get("pollen")
            if pollen is None:
                return None  # 미신청/만료
            def _disp(v):
                return v if v is not None else "알 수 없음"
            attrs = {
                "소나무":    _disp(pollen.get("pine")),
                "참나무":    _disp(pollen.get("oak")),
                "잡초류":    _disp(pollen.get("grass")),
                "발표 시각": pollen.get("announcement", "-"),
            }
            return attrs

        # ── 자외선지수 센서 ──────────────────────────────────────────────────
        if self._type in ("uv_value", "uv_grade"):
            uv = self.coordinator.data.get("uv")
            if not uv:
                return None
            attrs = {"발표 시각": uv.get("announcement", "-")}
            area_name = uv.get("area_name")
            if area_name:
                attrs["지역"] = area_name
            hourly = uv.get("hourly") or {}
            if self._type == "uv_grade":
                # 등급 센서는 숫자 지수가 아니라 각 시간대의 등급(낮음/보통/...)을 보여준다
                hourly = {k: KMAWeatherAPI._get_uv_grade(v) for k, v in hourly.items()}
            attrs.update(hourly)
            return attrs

        # ── 관측 조건 센서 ───────────────────────────────────────────────────
        if self._type == "observation_condition":
            return w.get("observation_attrs") or {}

        # ── 현재 예상 강수량 센서: 오늘 하루(00시~23시) 시간대별 강수량 (평탄화) ────────
        if self._type == "precip_amount":
            hourly = w.get("hourly_precipitation_mm") or {}
            display = w.get("precip_amount_display")
            attrs = dict(hourly)
            if display:
                attrs["표기"] = display
            return attrs or None

        return None
