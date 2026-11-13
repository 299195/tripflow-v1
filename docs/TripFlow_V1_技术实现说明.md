# TripFlow V1 技术实现说明

## 1. 总体架构

```text
浏览器 product.html/product.js/CSS
        ↓
FastAPI api.py
        ↓
TripFlowService
   ├─ DeterministicPlanner（约束执行）
   ├─ QwenAgent（建议与解释）
   ├─ MeituanMaps（地点搜索优先）
   ├─ AmapAdapter（POI/路线与 fallback）
   └─ SQLite Persistence
```

V1 采用“确定性执行 + LLM 建议”的混合架构。大模型不能直接写入最终行程状态，也不能绕过时间、预约和路线校验。

## 2. 目录职责

- `src/tripflow/api.py`：FastAPI 路由、参数校验、供应商选择和错误映射。
- `src/tripflow/service.py`：旅行、收藏、行程、版本和执行事件业务编排。
- `src/tripflow/planner.py`：时间窗口、停留时长、预约冲突和路线估算。
- `src/tripflow/schemas.py`：API 输入输出模型。
- `src/tripflow/qwen_agent.py`：Qwen OpenAI-compatible 调用、JSON 校验和 fallback。
- `src/tripflow/meituan.py`：美团地图文本/附近搜索适配器。
- `src/tripflow/domain/`：实体、枚举、状态机、版本和领域异常。
- `src/tripflow/persistence/`：SQLite 连接和持久化。
- `tripflow_amap/`：高德 POI、地点解析、路线和 HTTP 传输适配器。
- `frontend/`：当前中文产品页面。
- `tests/`：单元、契约、流程、外部适配器和前端资源测试。
- `eval/`：场景评测入口；`tripflow_adapter.py` 是评测与业务的适配层。

## 3. 领域模型

- `SavedPlace`：地点快照、来源、坐标和展示字段。
- `Trip`：用户、城市、日期、标题和旅行状态。
- `Constraint`：时间窗口、停留时长、预约和不可用地点。
- `Itinerary`：当前行程及其活动。
- `Activity`：地点、顺序、开始/结束时间和活动状态。
- `ItineraryVersion`：可审计的快照版本，恢复会产生新版本。
- `ExecutionEvent`：开始、到达、完成、跳过和备注等事件。

领域层定义 Trip、Itinerary、Activity 的状态转移和非法转移异常。V1 已建立模型和版本边界，但执行事件尚未驱动自动状态更新或重规划。

## 4. API

### 系统与攻略

- `GET /health`
- `GET /`
- `POST /api/v1/guides/draft`

### 地点与用户

- `GET /api/v1/pois/search`
- `GET /api/v1/pois/nearby`
- `GET /api/v1/pois/{poi_id}`
- `POST /api/v1/pois`
- `POST /api/v1/users/{user_id}/favorites`
- `GET /api/v1/users/{user_id}/profile`

### 旅行与行程

- `POST /api/v1/trips`
- `POST /api/v1/trips/{trip_id}/itinerary/generate`
- `GET /api/v1/itineraries/{itinerary_id}`
- `PATCH /api/v1/itineraries/{itinerary_id}`
- `GET /api/v1/itineraries/{itinerary_id}/versions`
- `POST /api/v1/itineraries/{itinerary_id}/restore`
- `POST /api/v1/itineraries/{itinerary_id}/execution-events`

响应中的 `provider` 标记 `meituan`、`amap` 或 `local`；`warnings` 传递 fallback、字段缺失和外部服务异常。

## 5. 外部服务

### 美团地图

配置 `MEITUAN_MAPS_KEY` 后，搜索和附近搜索优先调用美团地图 Web 服务。适配器只读取已知的地点 ID、名称、类型、地址、距离、城市和经纬度字段。图片、简介、评分、价格和交易字段不作为 V1 的稳定契约。

美团鉴权或请求失败时，API 追加 warning 并回退高德；供应商切换对前端可见。

### 高德地图

配置 `AMAP_API_KEY`。高德适配器负责 POI 文本搜索、地点解析和路线查询，是地点与路线能力的 fallback。密钥只通过环境变量传入。

### Qwen

配置 `QWEN_API_KEY` 后，`QwenAgent` 调用 DashScope OpenAI 兼容接口，要求严格 JSON，并处理超时、空结果、解析异常和 schema 不匹配。失败时返回 `basic` 模式的确定性攻略。Qwen 只提供建议和解释，不负责硬约束执行。

## 6. 规划与评测

规划器先规范化 POI 和约束，再保护固定预约，按顺序分配开始时间、停留时间和地点间移动时间，最后生成冲突、替换建议和版本快照。V1 上限为 8 个停靠点。

`eval/run_eval.py` 通过 `tripflow_adapter.py` 驱动路线规划、预约冲突、路线失败、延误和地点替换场景。评测结果 `reports/latest.json` 是运行产物，仓库只保留 `reports/BASELINE_TEMPLATE.md`。

## 7. 持久化与安全

- SQLite 数据库首次启动时自动创建，`*.db` 被 Git 忽略。
- 收藏使用用户与 POI 的唯一约束保证幂等。
- 版本采用快照，恢复不会删除历史记录。
- `.env`、日志、缓存、数据库、构建产物和评测 JSON 不提交。
- 前端不接收供应商密钥。
- V1 没有生产级身份认证、权限隔离和多租户安全。

## 8. 验证命令

```powershell
python -m pytest -q
python -m compileall -q src tripflow_amap eval tests
node --check frontend/product.js
python eval/run_eval.py
uvicorn tripflow.api:app --host 127.0.0.1 --port 8000
```

## 9. 后续演进边界

V1 只保留多 Agent 和自进化的演进接口：未来可以增加检索 Agent、约束审查 Agent、路线验证 Agent、执行事件触发的重规划 Agent、用户反馈/轨迹经验库和离线评测驱动的策略版本。但这些能力当前不应被描述为已经自动运行。

