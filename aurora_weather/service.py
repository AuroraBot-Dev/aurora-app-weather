"""Open-Meteo 查询；只执行只读 HTTPS 请求，不产生重复业务事件。"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Mapping
from typing import Any, Protocol

import httpx2

from aurora_weather.report import format_report

GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MAX_DAYS = 7
MAX_RESPONSE_BYTES = 2_000_000
CURRENT = (
    "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,"
    "weather_code,wind_speed_10m,wind_direction_10m"
)
DAILY = "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum"


class JsonFetcher(Protocol):
    async def get(self, url: str, params: Mapping[str, str | int | float]) -> dict[str, Any]: ...


class HttpFetcher:
    """固定数据源；拒绝重定向，不自动重试，不使用进程代理或凭据环境。"""

    async def get(self, url: str, params: Mapping[str, str | int | float]) -> dict[str, Any]:
        if url not in {GEO_URL, FORECAST_URL}:
            raise ValueError("天气数据源不受支持")
        try:
            async with httpx2.AsyncClient(timeout=8.0, follow_redirects=False, trust_env=False) as client:
                response = await client.get(url, params=dict(params), headers={"Accept": "application/json"})
                response.raise_for_status()
                if len(response.content) > MAX_RESPONSE_BYTES:
                    raise ValueError("天气接口响应过大")
                payload = response.json()
        except httpx2.HTTPError as error:
            raise ValueError("天气服务暂时不可用，请稍后再查询") from error
        except ValueError as error:
            raise ValueError("天气服务返回了无法读取的数据") from error
        if not isinstance(payload, dict) or payload.get("error"):
            raise ValueError("天气接口返回了错误或非对象数据")
        return payload


class WeatherService:
    """数据获取端口显式注入；测试使用固定 JSON，不读取网络或个人环境。"""

    def __init__(
        self,
        fetcher: JsonFetcher,
        *,
        default_city: str = "北京",
        language: str = "zh",
        aliases: Mapping[str, str] | None = None,
    ) -> None:
        if not default_city.strip() or len(default_city) > 100:
            raise ValueError("默认城市必须非空且不超过 100 字符")
        if language not in {"zh", "en", "ja"}:
            raise ValueError("语言只支持 zh、en、ja")
        self.fetcher = fetcher
        self.default_city = default_city.strip()
        self.language = language
        self.aliases = {"宜兴": "Yixing", **dict(aliases or {})}

    async def get_weather(self, city: str = "", days: int = 1, country_code: str = "") -> dict[str, object]:
        if not isinstance(city, str) or len(city) > 100:
            raise ValueError("城市名称不得超过 100 字符")
        if type(days) is not int or not 1 <= days <= MAX_DAYS:
            raise ValueError("预报天数必须是 1–7 的整数")
        if country_code and (len(country_code) != 2 or not country_code.isascii() or not country_code.isalpha()):
            raise ValueError("国家代码必须为两个英文字母")
        target = " ".join(city.split()) or self.default_city
        async with asyncio.timeout(25.0):
            location = await self._geocode(target, country_code.upper())
            payload = await self.fetcher.get(
                FORECAST_URL,
                {
                    "latitude": location["latitude"],
                    "longitude": location["longitude"],
                    "timezone": "auto",
                    "forecast_days": days,
                    "current": CURRENT,
                    "daily": DAILY,
                    "temperature_unit": "celsius",
                    "wind_speed_unit": "kmh",
                    "precipitation_unit": "mm",
                },
            )
        forecast = _forecast(payload, days)
        display = " · ".join(str(location[key]) for key in ("name", "admin1", "country") if location.get(key))
        return {
            "ok": True,
            "city": target,
            "location": display,
            "coordinates": {"latitude": location["latitude"], "longitude": location["longitude"]},
            "report": format_report(display, forecast),
            "forecast": forecast,
            "source": "Open-Meteo",
            "source_url": "https://open-meteo.com/",
        }

    async def _geocode(self, city: str, country_code: str) -> dict[str, Any]:
        canonical = city[:-1] if city.endswith(("市", "县", "区")) else city
        candidates = list(dict.fromkeys((city, canonical, self.aliases.get(canonical, canonical))))
        for name in candidates:
            params: dict[str, str | int | float] = {
                "name": name,
                "count": 10,
                "language": self.language,
                "format": "json",
            }
            if country_code:
                params["countryCode"] = country_code
            payload = await self.fetcher.get(GEO_URL, params)
            raw = payload.get("results", [])
            if not isinstance(raw, list) or any(not isinstance(item, dict) for item in raw):
                raise ValueError("地理编码数据结构异常")
            results = [item for item in raw if not country_code or item.get("country_code", "").upper() == country_code]
            if results:
                location = dict(results[0])
                _validate_location(location)
                return location
        raise ValueError("未找到城市；请提供更明确的城市名称或国家代码")


def _validate_location(location: dict[str, Any]) -> None:
    for key, limit in (("latitude", 90), ("longitude", 180)):
        value = location.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > limit:
            raise ValueError("地理编码坐标异常")
    if not isinstance(location.get("name"), str) or not location["name"].strip():
        raise ValueError("地理编码缺少地点名称")


def _forecast(payload: dict[str, Any], days: int) -> dict[str, Any]:
    current, daily = payload.get("current"), payload.get("daily")
    if not isinstance(current, dict) or not isinstance(daily, dict):
        raise ValueError("天气接口缺少 current 或 daily")
    if not isinstance(current.get("time"), str) or "temperature_2m" not in current:
        raise ValueError("天气接口缺少当前时间或温度")
    for field in ("time", *DAILY.split(",")):
        if not isinstance(daily.get(field), list) or len(daily[field]) != days:
            raise ValueError("天气接口的逐日数组长度不匹配")
    if not isinstance(payload.get("timezone"), str) or not payload["timezone"]:
        raise ValueError("天气接口缺少时区")
    return {"days": days, "timezone": payload["timezone"], "current": current, "daily": daily}
