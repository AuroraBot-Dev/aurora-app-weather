# 天气应用 (aurora-app-weather)

**包名**: `im.polaris.weather`

**版本**: 0.1.0

**最低 Brain 版本**: >=4.1.0

提供天气查询能力：输入城市名称，返回实时天气与今日概览。数据源使用 Open-Meteo（无需 API Key）。

---

## 指令

### `get_weather` -- 查询天气

查询指定城市的实时天气与今日概览（城市为空时使用启动参数 `default_city`）。

| 参数         | 类型    | 必填 | 说明                                           |
| ------------ | ------- | ---- | ---------------------------------------------- |
| `city`       | string  | 否   | 城市名称（可为空，使用默认城市）               |
| `days`       | number  | 否   | 预报天数（1-7）                                |
| `session_id` | string  | 否   | 可选会话 ID（用于事件回溯）                    |
| `emit_event` | boolean | 否   | 是否发出 `weather.reported` 事件（为空用配置） |

| 返回字段   | 类型    | 说明                                        |
| ---------- | ------- | ------------------------------------------- |
| `ok`       | boolean | 是否查询成功                                |
| `city`     | string  | 实际使用的城市入参                          |
| `location` | string  | 解析后的地点显示名                          |
| `report`   | string  | 可直接对用户展示的天气文本                  |
| `forecast` | object  | 结构化天气数据（包含 `current` 与 `daily`） |
| `error`    | string  | 错误信息（`ok=false` 时）                   |

---

## 事件

| 事件类型           | 触发时机                                              |
| ------------------ | ----------------------------------------------------- |
| `weather.reported` | 执行 `get_weather` 且 `emit_event=true`（含配置默认） |

---

## 配置

应用启动参数（对应 `WeatherApplication.__init__`）：

| 参数                      | 类型    | 默认值 | 说明                                             |
| ------------------------- | ------- | ------ | ------------------------------------------------ |
| `default_city`            | string  | 北京   | `city` 为空时使用的默认城市                      |
| `language`                | string  | zh     | 地理编码接口语言（影响候选城市返回）             |
| `emit_event`              | boolean | true   | 未显式传入 `emit_event` 时的默认事件开关         |
| `request_timeout_seconds` | number  | 8.0    | HTTP 请求超时时间（秒）                          |
| `city_aliases`            | object  | 见示例 | 城市别名映射，用于把中文名映射到可查询的英文名等 |

示例（也可参考同目录的 `config.example.json`）：

```yaml
apps:
  aurora-app-weather:
    enabled: true
    startup:
      default_city: 北京
      language: zh
      emit_event: true
      request_timeout_seconds: 8.0
      city_aliases:
        宜兴: Yixing
```
