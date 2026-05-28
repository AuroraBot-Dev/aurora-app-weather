from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from src.platform.contracts import AppEvent

if TYPE_CHECKING:
    from src.platform.application_api import PlatformAPI


@dataclass(frozen=True, slots=True)
class _GeoLocation:
    name: str
    latitude: float
    longitude: float
    country: str = ""
    admin1: str = ""
    timezone: str = ""

    def display_name(self) -> str:
        parts = [self.name]
        if self.admin1 and self.admin1 not in parts:
            parts.append(self.admin1)
        if self.country and self.country not in parts:
            parts.append(self.country)
        return " · ".join([p for p in parts if p])


_WMO_WEATHER_CODE_ZH: dict[int, str] = {
    0: "晴",
    1: "大部晴朗",
    2: "多云",
    3: "阴",
    45: "雾",
    48: "雾凇",
    51: "毛毛雨（小）",
    53: "毛毛雨（中）",
    55: "毛毛雨（大）",
    56: "冻毛毛雨（小）",
    57: "冻毛毛雨（大）",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "冻雨（小）",
    67: "冻雨（大）",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "米雪",
    80: "阵雨（小）",
    81: "阵雨（中）",
    82: "阵雨（大）",
    85: "阵雪（小）",
    86: "阵雪（大）",
    95: "雷暴",
    96: "雷暴伴小冰雹",
    99: "雷暴伴大冰雹",
}

_DEFAULT_CITY_ALIASES: dict[str, str] = {
    "宜兴": "Yixing",
}

_CITY_SUFFIXES: tuple[str, ...] = (
    "经济技术开发区",
    "经济开发区",
    "开发区",
    "高新区",
    "新区",
    "工业园区",
    "产业园区",
    "园区",
    "市",
    "县",
    "区",
    "镇",
    "乡",
)


class WeatherApplication:
    def __init__(
        self,
        default_city: str = "北京",
        language: str = "zh",
        emit_event: bool = True,
        request_timeout_seconds: float = 8.0,
        city_aliases: dict[str, str] | None = None,
    ) -> None:
        self._api: PlatformAPI | None = None
        self._default_city = _clean_city_text(default_city) or "北京"
        self._language = language.strip() or "zh"
        self._emit_event = emit_event
        self._timeout_seconds = max(1.0, float(request_timeout_seconds))
        merged_aliases: dict[str, str] = dict(_DEFAULT_CITY_ALIASES)
        if isinstance(city_aliases, dict):
            for key, value in city_aliases.items():
                k = _canonical_city_key(str(key))
                v = str(value).strip()
                if k and v:
                    merged_aliases[k] = v
        self._city_aliases = merged_aliases

    def _bind(self, api: "PlatformAPI") -> None:
        self._api = api
        api.log("info", f"绑定天气应用: package={api.package}, data_dir={api.data_dir}")

    def manifest_path(self) -> Path:
        return Path(__file__).with_name("manifest.yaml")

    async def on_start(self) -> None:
        api = self._require_api()
        api.log("info", f"Weather application started: default_city={self._default_city}")

    async def on_stop(self) -> None:
        self._require_api().log("info", "Weather application stopped")

    async def on_tick(self) -> None:
        return

    async def get_weather(
        self,
        city: str = "",
        days: int = 1,
        session_id: str = "",
        emit_event: bool | None = None,
    ) -> dict[str, object]:
        api = self._require_api()
        requested_city = _clean_city_text(city)
        default_city = _clean_city_text(self._default_city)
        target_city = requested_city or default_city
        if not target_city:
            return {"ok": False, "error": "city 不能为空"}

        target_days = int(days or 1)
        target_days = max(1, min(7, target_days))

        try:
            location = await self._geocode_city(target_city)
        except (LookupError, OSError, TypeError, ValueError) as exc:
            api.log("warning", f"天气查询失败(地理编码): city={target_city} err={exc}")
            return {"ok": False, "error": f"地理编码失败: {exc}"}

        try:
            forecast = await self._fetch_forecast(location, target_days)
        except (OSError, TypeError, ValueError) as exc:
            api.log("warning", f"天气查询失败(天气接口): city={target_city} err={exc}")
            return {"ok": False, "error": f"天气接口请求失败: {exc}"}

        report = self._format_report(location, forecast)
        should_emit = self._emit_event if emit_event is None else bool(emit_event)
        if should_emit:
            api.emit_event(
                AppEvent(
                    source=api.package,
                    type="weather.reported",
                    session_id=session_id,
                    summary=location.display_name(),
                    payload={
                        "city": target_city,
                        "location": {
                            "name": location.name,
                            "country": location.country,
                            "admin1": location.admin1,
                            "latitude": location.latitude,
                            "longitude": location.longitude,
                            "timezone": location.timezone,
                        },
                        "forecast": forecast,
                        "report": report,
                    },
                )
            )

        return {
            "ok": True,
            "city": target_city,
            "location": location.display_name(),
            "report": report,
            "forecast": forecast,
        }

    async def _geocode_city(self, city: str) -> _GeoLocation:
        cleaned = _clean_city_text(city)
        if not cleaned:
            raise LookupError("city 不能为空")

        canonical = _canonical_city_key(cleaned)
        candidates: list[str] = []
        candidates.append(cleaned)
        cleaned_no_space = cleaned.replace(" ", "")
        if cleaned_no_space and cleaned_no_space not in candidates:
            candidates.append(cleaned_no_space)
        if canonical and canonical not in candidates:
            candidates.append(canonical)
        canonical_no_space = canonical.replace(" ", "") if canonical else ""
        if canonical_no_space and canonical_no_space not in candidates:
            candidates.append(canonical_no_space)
        alias = self._city_aliases.get(canonical, "") if canonical else ""
        if alias and alias not in candidates:
            candidates.append(alias)

        results: list[dict[str, Any]] = []
        tried: list[str] = []
        for candidate in candidates:
            if not candidate:
                continue
            tried.append(candidate)
            results = await self._geocode_results(candidate)
            if results:
                break
        if not results:
            raise LookupError(f"未找到城市: {cleaned} (tried={', '.join(tried)})")

        first = results[0]
        latitude = float(first.get("latitude"))
        longitude = float(first.get("longitude"))
        name = cleaned if _has_cjk(cleaned) else (str(first.get("name", "")).strip() or cleaned)
        country = str(first.get("country", "")).strip()
        admin1 = str(first.get("admin1", "")).strip()
        timezone = str(first.get("timezone", "")).strip()
        return _GeoLocation(
            name=name,
            latitude=latitude,
            longitude=longitude,
            country=country,
            admin1=admin1,
            timezone=timezone,
        )

    async def _geocode_results(self, query_name: str) -> list[dict[str, Any]]:
        query = urlencode(
            {
                "name": query_name,
                "count": 10,
                "language": self._language,
                "format": "json",
            }
        )
        url = f"https://geocoding-api.open-meteo.com/v1/search?{query}"
        payload = await self._fetch_json(url)
        raw_results = payload.get("results", [])
        results = [item for item in raw_results if isinstance(item, dict)]
        results.sort(key=_rank_geocode_result, reverse=True)
        return results

    async def _fetch_forecast(self, location: _GeoLocation, days: int) -> dict[str, Any]:
        query = urlencode(
            {
                "latitude": location.latitude,
                "longitude": location.longitude,
                "timezone": "auto",
                "forecast_days": days,
                "current": ",".join(
                    [
                        "temperature_2m",
                        "relative_humidity_2m",
                        "apparent_temperature",
                        "precipitation",
                        "weather_code",
                        "wind_speed_10m",
                        "wind_direction_10m",
                    ]
                ),
                "daily": ",".join(
                    [
                        "weather_code",
                        "temperature_2m_max",
                        "temperature_2m_min",
                        "precipitation_sum",
                    ]
                ),
            }
        )
        url = f"https://api.open-meteo.com/v1/forecast?{query}"
        payload = await self._fetch_json(url)
        current = payload.get("current", {})
        daily = payload.get("daily", {})
        if not isinstance(current, dict) or not isinstance(daily, dict):
            raise ValueError("天气接口响应格式异常")

        return {
            "days": int(days),
            "timezone": str(payload.get("timezone", "")),
            "current": dict(current),
            "daily": dict(daily),
        }

    def _format_report(self, location: _GeoLocation, forecast: dict[str, Any]) -> str:
        current = forecast.get("current", {}) if isinstance(forecast.get("current"), dict) else {}
        daily = forecast.get("daily", {}) if isinstance(forecast.get("daily"), dict) else {}

        current_temp = current.get("temperature_2m")
        current_apparent = current.get("apparent_temperature")
        current_humidity = current.get("relative_humidity_2m")
        current_precip = current.get("precipitation")
        current_wind = current.get("wind_speed_10m")
        current_wind_dir = current.get("wind_direction_10m")
        current_code = current.get("weather_code")

        current_desc = self._describe_code(current_code)
        current_time = str(current.get("time", "")).strip()

        dates = daily.get("time", [])
        maxs = daily.get("temperature_2m_max", [])
        mins = daily.get("temperature_2m_min", [])
        precips = daily.get("precipitation_sum", [])
        codes = daily.get("weather_code", [])

        def _num(value: object, digits: int = 1) -> str:
            try:
                return f"{float(value):.{digits}f}"
            except (TypeError, ValueError):
                return "?"

        def _day_label(index: int) -> str:
            if index == 0:
                return "今日"
            if index == 1:
                return "明天"
            if index == 2:
                return "后天"
            return f"{index}天后"

        try:
            forecast_days = int(forecast.get("days") or 1)
        except (TypeError, ValueError):
            forecast_days = 1
        forecast_days = max(1, min(7, forecast_days))

        def _list_item(items: object, index: int) -> object:
            if isinstance(items, list) and index < len(items):
                return items[index]
            return None

        lines = [f"{location.display_name()}"]
        if current_time:
            lines.append(f"时间: {current_time}")
        lines.append(
            "当前: "
            f"{current_desc} "
            f"{_num(current_temp)}℃"
            f" 体感{_num(current_apparent)}℃"
            f" 湿度{_num(current_humidity, 0)}%"
            f" 降水{_num(current_precip)}mm"
            f" 风速{_num(current_wind)}km/h"
            f" 风向{_num(current_wind_dir, 0)}°"
        )
        for index in range(forecast_days):
            date = _list_item(dates, index)
            code = _list_item(codes, index)
            temp_min = _list_item(mins, index)
            temp_max = _list_item(maxs, index)
            precip = _list_item(precips, index)
            if date is None and code is None and temp_min is None and temp_max is None and precip is None:
                continue
            label = _day_label(index)
            date_text = f"({date})" if date else ""
            desc = self._describe_code(code)
            lines.append(
                f"{label}{date_text}: "
                f"{desc} "
                f"{_num(temp_min)}~{_num(temp_max)}℃"
                f" 降水{_num(precip)}mm"
            )
        return "\n".join(lines).strip()

    @staticmethod
    def _describe_code(code: object) -> str:
        try:
            code_int = int(code)
        except (TypeError, ValueError):
            return "未知"
        return _WMO_WEATHER_CODE_ZH.get(code_int, f"未知({code_int})")

    async def _fetch_json(self, url: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._fetch_json_sync, url)

    def _fetch_json_sync(self, url: str) -> dict[str, Any]:
        request = Request(
            url,
            headers={
                "User-Agent": "AuroraBot/WeatherApplication",
                "Accept": "application/json",
            },
            method="GET",
        )
        for attempt in range(2):
            try:
                with urlopen(request, timeout=self._timeout_seconds) as response:
                    raw = response.read()
                break
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                if attempt < 1:
                    time.sleep(0.4)
                    continue
                raise OSError(f"HTTP 请求失败: {exc}") from exc
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"JSON 解析失败: {exc}") from exc
        return payload if isinstance(payload, dict) else {}

    def _require_api(self) -> "PlatformAPI":
        if self._api is None:
            raise RuntimeError("WeatherApplication is not bound to PlatformAPI")
        return self._api


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _clean_city_text(raw: str) -> str:
    text = (raw or "").strip().replace("\u3000", " ")
    text = " ".join(text.split())
    return text


def _strip_city_suffixes(text: str) -> str:
    current = _clean_city_text(text)
    while True:
        removed = False
        for suffix in _CITY_SUFFIXES:
            if current.endswith(suffix) and len(current) > len(suffix):
                current = current[: -len(suffix)].strip()
                removed = True
                break
        if not removed:
            break
    return current


def _canonical_city_key(raw: str) -> str:
    return _strip_city_suffixes(raw)


def _normalize_city_name(raw: str) -> str:
    return _canonical_city_key(raw)


def _rank_geocode_result(item: dict[str, Any]) -> tuple[int, int, float]:
    feature = str(item.get("feature_code", "")).strip().upper()
    feature_score = {
        "PPLC": 120,
        "PPLA": 110,
        "PPLA1": 105,
        "PPLA2": 100,
        "PPLA3": 95,
        "PPLA4": 90,
        "PPL": 80,
        "PPLL": 70,
        "PPLS": 60,
    }.get(feature, 0)
    try:
        population = int(item.get("population") or 0)
    except (TypeError, ValueError):
        population = 0
    try:
        elev = float(item.get("elevation") or 0.0)
    except (TypeError, ValueError):
        elev = 0.0
    return (feature_score, population, -abs(elev))
