# 天气 MCP App

包名：`im.polaris.weather`。查询 Open-Meteo 当前天气和 1–7 天预报，不调用模型、不依赖 Host 内部模块。

## 工具

`get_weather(city="", days=1, country_code="")`：

- city：城市名称，空值使用默认城市，最多 100 字符。
- days：严格整数 1–7，不默默截断越界输入。
- country_code：可选 ISO 两字母国家代码，如 CN，用于减少同名城市歧义。
- 返回 ok、city、location、coordinates、report、forecast、source、source_url。
- 地理编码使用首个符合国家筛选的候选；结果中明确返回实际地点和坐标，不能保证仅凭城市名完全消除歧义。
- 支持城市末尾“市/县/区”及宜兴→Yixing 的查询候选。
- 温度为摄氏度、风速 km/h、降水 mm；时区由数据源返回，报告保留时间与来源。
- 不存在的城市、请求超时、错误 JSON、缺失数据均明确失败，不把空数据伪装成天气。
- 不自动重试，不跟随重定向，不接收任意 URL，不读取环境代理或密钥。

只进行只读 HTTPS 查询；event_mode 为 disabled，不把查询回执再发送为主动事件。
不提供天气预警订阅、图片、session_id、emit_event 或平台生命周期接口。

## 配置和数据源

只读取 `AURORA_WEATHER_DEFAULT_CITY`（默认北京）和 `AURORA_WEATHER_LANGUAGE`（zh/en/ja，默认 zh）。
使用公共 Open-Meteo 地址，不需要 API Key。公共接口有使用额度和用途限制，
商用部署请先查看服务条款；本 App 不自动切换商业接口。

- [天气 API 文档](https://open-meteo.com/en/docs)
- [地理编码文档](https://open-meteo.com/en/docs/geocoding-api)
- [服务条款](https://open-meteo.com/en/terms)

测试使用固定 HTTP 端口返回值，不把样例天气称作真实观测。
例子：`get_weather(city="北京", days=1, country_code="CN")`。
最终领域 ID：`aur.mcp.im.polaris.weather.get_weather`。

## 运行与接入

需要 Python 3.12–3.14 和官方 MCP Python SDK 2.x。在 App 目录运行：

```powershell
uv run python mcp_server.py
```

也可以使用已安装依赖的 Python 直接运行入口。本机 AuroraBot 的个人
`config/apps.toml` 已使用 `D:/AuroraBot/.venv/Scripts/python.exe`，
因此不会因为 App 有自己的 pyproject.toml 而意外切换环境。移动仓库后需同步更新个人启动路径。
测试：在 App 目录运行 `uv run --group dev pytest -q -p no:cacheprovider`。
主仓库的 `aurora check` 不包含被忽略的 extensions，需要单独运行这些测试。

Host 通过 tools/list 获取定义，不读取 manifest.yaml 或 config.example.json；
这两个文件不负责启动配置。个人配置只放在 config，不修改主仓库 config.example。
Agent 必须在 config/agents.toml 的 tools 中获得对应 `aur.mcp.<package>.*`。
仅 builtin.worker 被授予本组业务工具，root 可以委派给它。

stdout 只输出 MCP JSON-RPC；日志走 stderr。工具返回 CallToolResult 的文本和 structuredContent。
Server 声明 `org.aurorabot/tool-contract: {"version":1}`：
参数/业务拒绝为 failed；无法确认写入结果时返回 unknown，不能自动重试。
SDK 和 Host 自动协商协议，代码不手写握手或伪装协议版本。
