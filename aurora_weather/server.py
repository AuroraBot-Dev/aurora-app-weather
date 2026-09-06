"""天气 MCP 2 入口；工具结果经标准回执返回，不另发查询事件。"""

from __future__ import annotations

import os
from typing import Annotated

from mcp.server import MCPServer
from mcp.types import CallToolResult, ToolAnnotations
from pydantic import Field

from aurora_weather.protocol import ToolContract, failure, success
from aurora_weather.service import HttpFetcher, WeatherService

PACKAGE = "im.polaris.weather"
City = Annotated[str, Field(max_length=100, description="城市名，空字符串使用默认城市")]
Days = Annotated[int, Field(ge=1, le=7, strict=True, description="预报天数，1–7")]
Country = Annotated[str, Field(pattern=r"^(?:[A-Za-z]{2})?$", description="可选 ISO 两字母国家代码，如 CN")]


def create_server(service: WeatherService) -> MCPServer:
    server = MCPServer("aurora-weather", version="2.0.0", extensions=(ToolContract(),))

    @server.tool(
        description="查询城市当前天气及 1–7 天预报；返回解析地点、时区、中文报告和 Open-Meteo 数据。",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True),
    )
    async def get_weather(city: City = "", days: Days = 1, country_code: Country = "") -> CallToolResult:
        try:
            return success(await service.get_weather(city, days, country_code))
        except ValueError as error:
            return failure(str(error))
        except TimeoutError:
            return failure("天气查询超时；未执行任何写入")

    return server


def main() -> None:
    service = WeatherService(
        HttpFetcher(),
        default_city=os.environ.get("AURORA_WEATHER_DEFAULT_CITY", "北京"),
        language=os.environ.get("AURORA_WEATHER_LANGUAGE", "zh"),
    )
    create_server(service).run(transport="stdio")
