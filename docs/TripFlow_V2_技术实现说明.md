# TripFlow V2 技术实现说明

## 1. 架构

```text
Browser
  └─ FastAPI V1/V2 API
       ├─ TripFlowService
       │    ├─ Replanner（只生成候选快照）
       │    ├─ DeterministicPlanner（最终硬约束校验）
       │    ├─ CachedRouteProvider → AmapRouteProvider → AmapAdapter
       │    └─ SQLite 事务与版本快照
       ├─ TripFlowAgentCoordinator
       │    ├─ intent
       │    ├─ place_verifier
       │    └─ plan_reviewer
       └─ FeedbackLedger / StrategyRegistry / EvolutionEvaluator
```

Agent 只产生结构化建议。行程状态只能由 Service 在事务中写入，避免模型直接改变活动、路线或版本。

## 2. 路线实现

`AmapRouteProvider` 将已有 `AmapAdapter.route()` 转换成规划器 `RouteResult`。规划器保留：

- `source`
- `mode`
- `distance_meters`
- `duration_minutes`
- `raw_summary`
- `fetched_at`
- `estimated`

`CachedRouteProvider` 使用 `route_cache` 表按起点、终点和交通方式缓存结果，并设置过期时间。高德失败时由 provider 生成 `estimate:straight_line_after_amap_failure`，同时保留错误摘要。

当 `AMAP_API_KEY` 存在时，Service 自动创建路线 provider；否则保持离线估算模式。真实线上调用应单独执行冒烟测试，不能和 fixture 结果合并。

## 3. 重规划与事务

`Replanner` 接收当前活动快照和执行事件，产生最多三个候选快照：

- 延误后顺延。
- 移除关闭或跳过的地点。
- 使用用户提供的替代地点。

`preview_replan` 只写入 `replan_proposals`，不修改 activities。`confirm_replan` 校验：

1. proposal 存在且仍为 pending。
2. proposal 基础版本等于当前版本。
3. option 属于该 proposal。
4. 幂等键未被其他确认占用。

通过后在事务中删除并写入活动快照、创建新版本、更新 proposal 状态。任一步失败时事务回滚。恢复旧版本仍通过已有版本快照机制创建新版本。

## 4. Agent 运行时

`TripFlowAgentCoordinator` 使用共享结构化 state 执行三个节点：

```text
intent → place_verifier → plan_reviewer
```

每个节点输出独立 artifact，并写入 `agent_runs`：

- `correlation_id`
- `agent_name`
- `status`
- `policy_version`
- `input_json`
- `output_json`
- `error`
- `started_at` / `finished_at`

当前内置节点在模型不可用时执行确定性 fallback；未来可通过 `model_runner` 注入结构化模型调用。节点不能获得数据库写入权限，Service 是唯一状态提交者。

## 5. 数据库迁移

`002_v2_execution.sql` 新增：

- `route_cache`：路线缓存。
- `agent_runs`：Agent 轨迹。
- `replan_proposals`：候选方案与确认状态。
- `feedback_events`：用户反馈。
- `strategy_releases`：策略生命周期。

V1 表结构保持兼容，迁移通过 `schema_migrations` 幂等执行。

## 6. 自进化评测

### 数据流

```text
feedback_events
       ↓
FeedbackLedger
       ↓
EvaluationSample
       ↓
baseline/candidate strategy runner
       ↓
HardConstraintGate
       ↓
human approve/reject
```

实现文件：

- `src/tripflow/feedback.py`
- `src/tripflow/strategy.py`
- `src/tripflow/evolution_eval.py`
- `eval/run_evolution_eval_v2.py`

评测记录硬约束违规数、硬约束通过率、接受率、效用、延迟、成本和评测错误数。候选策略不能通过硬约束门槛时，审批会抛错；拒绝或批准都需要明确决策。

运行：

```powershell
python eval/run_evolution_eval_v2.py --candidate improved --decision approve
python eval/run_evolution_eval_v2.py --candidate regression --decision reject
python eval/run_v2_business_eval.py
```

## 7. 测试与证据边界

- 单元和集成测试验证领域、路线映射、重规划、反馈和前端资源。
- `run_v2_business_eval.py` 的 40 个场景实际调用 Service 和规划器，但使用本地确定性数据，`external_api=false`。
- 高德、美团和 Qwen 真实冒烟调用应单独记录；离线测试不代表外部服务已成功。
- 不把合成 adapter 或模型自评结果作为真实线上质量指标。

