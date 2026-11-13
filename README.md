# TripFlow V1

TripFlow V2 是单用户、单城市、单次旅行优先的中文旅行规划网页端。当前交付包含对话式攻略草稿、地点搜索与收藏、真实路线适配、候选重规划、多 Agent 运行记录、反馈评测和策略门槛；多人协作、自动预订和生产级多租户认证仍不在范围内。

## 快速启动

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
$env:TRIPFLOW_IMPORT_APP="1"
python -m uvicorn tripflow.api:app --reload
```

打开 `http://127.0.0.1:8000/` 使用中文旅行网页端；`/docs` 查看接口文档。首页入口是 `frontend/product.html`，样式和交互分别位于 `product.css`、`product-extra.css` 与 `product.js`，由 FastAPI 直接提供，无构建步骤。

用户界面按「灵感首页—探索地点—我的旅行」组织。首页输入目的地、日期和一日游偏好，Qwen 生成攻略草稿，高德核实候选地点；用户选择地点后才保存为行程。探索页支持城市关键词及授权定位后的周边分类搜索；“我的”聚合收藏地点和行程，并可查看活动与历史版本。`local-traveler` 是 V1 本地用户标识，并非登录认证。当前保存为单日行程；多日拆分、真正的地图可视化和生活服务交易信息属于后续扩展。

核心接口包括：

- `GET /api/v1/pois/search`、`GET /api/v1/pois/{poi_id}`：POI 搜索和确认；实时搜索需要 `AMAP_API_KEY`。
- `POST /api/v1/pois`：保存已确认 POI；`POST /api/v1/users/{user_id}/favorites`：收藏及偏好。
- `POST /api/v1/trips`、`POST /api/v1/trips/{trip_id}/itinerary/generate`：创建旅行和生成行程。
- `PATCH /api/v1/itineraries/{itinerary_id}`：删除/替换/延长活动并创建新版本。
- `GET /api/v1/itineraries/{itinerary_id}/versions`、`POST .../restore`：查看和恢复历史版本。
- `POST /api/v1/itineraries/{itinerary_id}/execution-events`：基础执行状态事件。
- `POST /api/v1/guides/draft`：生成未保存的对话攻略草稿，候选地点需经地图搜索核实。
- `GET /api/v1/pois/nearby`：周边地点搜索；`GET /api/v1/users/{user_id}/profile`：收藏与行程列表。

地点搜索优先尝试 `MEITUAN_MAPS_KEY` 对应的美团地图关键词/周边搜索。接口未授权或不可用时，若已配置高德 Web Service Key，会返回明确标注 `provider=amap` 和 `warning` 的高德结果；不会把高德数据标为美团。美团地图公开搜索响应只包含名称、类别、地址、坐标等 POI 字段，没有图片或商户简介；前端详情据实展示这些字段，图片缺失时显示通用占位。商户照片及更丰富的内容需要另行获得有权限的数据接口。

规划器不把模型或网络结果当作约束真相：日期、时间窗、停留时长、预约、重叠活动、路线不可用等由代码确定性校验。没有 LLM 配置时，服务仍可使用已确认 POI 走确定性路径；没有路线提供方时，行程中的路线会明确标记为 `deterministic_straight_line_estimate`，不伪装成高德数据。高德 Adapter 仍独立使用 `AMAP_API_KEY`、超时/重试配置，并保留 `unknown` 与 `raw_data` 字段；`tests/fixtures` 只用于 Fixture 测试。

可选 Agent 使用 DashScope 官方 OpenAI-compatible API。Key 只从 `QWEN_API_KEY` 或备用名称 `DASHSCOPE_API_KEY` 读取；基础地址从 `QWEN_API_BASE` 或 `DASHSCOPE_BASE_URL` 读取，模型从 `QWEN_MODEL` 或 `DASHSCOPE_MODEL` 读取。`QWEN_TIMEOUT_SECONDS` 和 `QWEN_ENABLED` 控制超时与开关。Qwen 只在确定性行程已生成后返回 JSON Schema 约束摘要/解释，不得修改活动或绕过校验；无 Key、关闭开关或请求失败时使用确定性回退。

## 验证

在未安装开发依赖的环境中可先运行：

```powershell
$env:PYTHONPATH="src;."
python -m unittest discover -s tests -v
python -m compileall -q src tripflow_amap eval tests
python eval/run_eval.py --adapter tripflow_adapter:TripFlowAdapter
```

安装 `[dev]` 后运行 `python -m pytest -q`，并用 `node --check frontend/product.js` 检查页面脚本。手工验收顺序：打开 `/`，输入城市、日期和旅行想法；选择候选地点并保存；到探索页搜索或定位周边地点并收藏；最后到“我的旅行”查看收藏、行程和历史版本。地图和模型 API 失败时页面展示可理解的错误提示。默认自动化测试使用 Fixture，不代表真实高德或 Qwen 请求成功。

V2 业务链路评测使用真实 Service 和规划器，不使用合成业务适配器：

```powershell
python eval/run_v2_business_eval.py
python eval/run_evolution_eval_v2.py --candidate improved --decision approve
python eval/run_evolution_eval_v2.py --candidate regression --decision reject
```

V2 文档：

- [V2 需求与功能说明](docs/TripFlow_V2_需求与功能说明.md)
- [V2 技术实现说明](docs/TripFlow_V2_技术实现说明.md)
- [V1 到 V2 变化与限制](docs/TripFlow_V1_to_V2_变化与限制.md)

Qwen 真实验证需要在当前进程中明确启用 `QWEN_ENABLED=1`，然后执行一次安全的最小 smoke request；默认测试使用 mock，不把 mock 结果记录为真实调用。评测报告中的 `qwen.configured`、`qwen.mode` 和 `qwen_live_validation` 会区分配置状态、回退/结构化模式和是否真实请求。

## V1 文档

- [需求与功能说明](docs/TripFlow_V1_需求与功能说明.md)
- [技术实现说明](docs/TripFlow_V1_技术实现说明.md)

