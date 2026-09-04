"""把结构化天气数据渲染为带明确单位的中文文本。"""

from __future__ import annotations

from typing import Any

_CODES = {
    0: "晴",
    1: "大部晴朗",
    2: "多云",
    3: "阴",
    45: "雾",
    48: "雾凇",
    51: "小毛毛雨",
    53: "中毛毛雨",
    55: "大毛毛雨",
    56: "小冻毛毛雨",
    57: "大冻毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "小冻雨",
    67: "大冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "米雪",
    80: "小阵雨",
    81: "中阵雨",
    82: "大阵雨",
    85: "小阵雪",
    86: "大阵雪",
    95: "雷暴",
    96: "雷暴伴小冰雹",
    99: "雷暴伴大冰雹",
}


def describe_code(value: object) -> str:
    return _CODES.get(value, "未知天气") if type(value) is int else "未知天气"


def _number(value: object) -> str:
    return f"{value:g}" if type(value) in (int, float) else "未知"


def format_report(location: str, forecast: dict[str, Any]) -> str:
    current, daily = forecast["current"], forecast["daily"]
    lines = [
        location,
        f"时间：{current['time']}（{forecast['timezone']}）",
        f"当前：{describe_code(current.get('weather_code'))} {_number(current.get('temperature_2m'))}℃",
        f"湿度：{_number(current.get('relative_humidity_2m'))}% 风速：{_number(current.get('wind_speed_10m'))}km/h",
    ]
    for index, day in enumerate(daily["time"]):
        lines.append(
            f"{day}：{describe_code(daily['weather_code'][index])} "
            f"{_number(daily['temperature_2m_min'][index])}～{_number(daily['temperature_2m_max'][index])}℃ "
            f"降水 {_number(daily['precipitation_sum'][index])}mm"
        )
    lines.append("数据来源：Open-Meteo")
    return "\n".join(lines)
