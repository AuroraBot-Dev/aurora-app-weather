from __future__ import annotations

import asyncio
from copy import deepcopy

import httpx2
import pytest
from mcp.client.client import Client

from aurora_weather.server import create_server
from aurora_weather.service import FORECAST_URL, GEO_URL, HttpFetcher, WeatherService

GEO = {
    "results": [
        {
            "name": "北京",
            "latitude": 39.9,
            "longitude": 116.4,
            "country": "中国",
            "country_code": "CN",
            "admin1": "北京",
        }
    ]
}
FORECAST = {
    "timezone": "Asia/Shanghai",
    "current": {
        "time": "2026-09-04T12:00",
        "temperature_2m": 26.0,
        "weather_code": 2,
        "relative_humidity_2m": 60,
        "wind_speed_10m": 8.0,
    },
    "daily": {
        "time": ["2026-09-04"],
        "weather_code": [2],
        "temperature_2m_max": [29.0],
        "temperature_2m_min": [21.0],
        "precipitation_sum": [0.0],
    },
}


class FakeFetcher:
    def __init__(self, geo: dict | None = None, forecast: dict | None = None) -> None:
        self.geo = deepcopy(GEO if geo is None else geo)
        self.forecast = deepcopy(FORECAST if forecast is None else forecast)
        self.calls = []

    async def get(self, url: str, params: dict) -> dict:
        self.calls.append((url, dict(params)))
        return deepcopy(self.geo if url == GEO_URL else self.forecast)


def test_offline_weather_and_request_parameters() -> None:
    async def scenario() -> None:
        fetcher = FakeFetcher()
        result = await WeatherService(fetcher).get_weather("北京", 1, "CN")
        assert result["ok"] and result["forecast"]["current"]["temperature_2m"] == 26.0
        assert "Open-Meteo" in result["report"] and "26℃" in result["report"]
        assert [url for url, _ in fetcher.calls] == [GEO_URL, FORECAST_URL]
        assert fetcher.calls[0][1]["countryCode"] == "CN"
        assert fetcher.calls[1][1]["temperature_unit"] == "celsius"

    asyncio.run(scenario())


@pytest.mark.parametrize("days", [0, 8, True, 1.5])
def test_invalid_days_have_no_network(days: object) -> None:
    fetcher = FakeFetcher()
    with pytest.raises(ValueError):
        asyncio.run(WeatherService(fetcher).get_weather("北京", days))
    assert not fetcher.calls


def test_missing_city_and_bad_weather() -> None:
    with pytest.raises(ValueError, match="未找到"):
        asyncio.run(WeatherService(FakeFetcher(geo={})).get_weather("不存在"))
    with pytest.raises(ValueError, match="缺少"):
        asyncio.run(WeatherService(FakeFetcher(forecast={})).get_weather("北京"))


def test_http_errors_are_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken(_self: object, *_args: object, **_kwargs: object) -> None:
        raise httpx2.ConnectError("must-not-leak-token-or-url")

    monkeypatch.setattr(httpx2.AsyncClient, "get", broken)
    with pytest.raises(ValueError, match="暂时不可用") as info:
        asyncio.run(HttpFetcher().get(GEO_URL, {"name": "北京"}))
    assert "must-not-leak" not in str(info.value)


def test_mcp2_schema_and_result() -> None:
    async def scenario() -> None:
        fetcher = FakeFetcher()
        async with Client(create_server(WeatherService(fetcher)), mode="auto") as client:
            assert client.protocol_version == "2026-07-28"
            tools = (await client.list_tools()).tools
            assert [tool.name for tool in tools] == ["get_weather"]
            result = await client.call_tool("get_weather", {"city": "北京", "days": 1})
            assert not result.is_error and result.structured_content["source"] == "Open-Meteo"
            bad = await client.call_tool("get_weather", {"city": "北京", "days": 8})
            assert bad.is_error
            assert len(fetcher.calls) == 2

    asyncio.run(scenario())
