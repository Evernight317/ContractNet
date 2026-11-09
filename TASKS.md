# ContractNet 开发路线图

> 基于 2026-11-09 代码审计生成。按优先级排序，前置依赖标注于各任务内。

## P0 — 打通 LLM 执行链路（核心阻塞项）

当前 CLI 和 Orchestrator 使用 `StubAgent`（返回硬编码文本），`LLMClient` 已就绪但从未注入。这是项目从"骨架"到"可用"的关键一步。

### 1. 实现 LLM 驱动的 ReAct Agent

- **目标**：继承 `BaseAgent`，实现 `execute()` 中的 Think → Act(tool_call) → Observe 循环
- **依赖**：`llm/client.py`（已完成）、`tools/sandbox.py`（已完成）
- **涉及文件**：新建 `src/contractnet/core/react_agent.py`
- **要点**：
  - 使用 `LLMClient.chat(messages, tools=TOOL_DEFINITIONS)` 多轮对话
  - 工具调用经 `sandbox.execute()` 执行，结果回填为 `tool` role 消息
  - 循环终止条件：`finish_reason == "stop"` 或达到 `deadline_steps`
  - Token 用量从 `LLMResponse.total_tokens` 累加到 `ExecutionRecord`

### 2. 将 LLMClient 注入 Planner

- **目标**：任务分解从规则兜底升级为 LLM 驱动
- **涉及文件**：`src/contractnet/core/planner.py`、`src/contractnet/cli.py`
- **要点**：
  - `_build_orchestrator()` 中创建 `LLMClient()` 实例，传入 `Planner(llm_client=client)`
  - 验证 LLM 返回 JSON 解析、拓扑校验、粒度控制链路

### 3. 将 LLMClient 注入 QualityGate

- **目标**：启用第二层语义校验（LLM-as-Judge）
- **涉及文件**：`src/contractnet/core/quality_gate.py`、`src/contractnet/cli.py`
- **要点**：
  - `judge_client` 建议用与执行 Agent 不同的模型（避免自评偏差）
  - 可暂用同模型，后续配置 `CONTRACTNET_JUDGE_MODEL` 环境变量

### 4. Agent Profile 模型对齐

- **问题**：`builtins.py` 中 6 个预设 Agent 硬编码 `model="gpt-4o"` / `"gpt-4o-mini"`，与 `.env` 的 `glm-4.7-flash` 不一致
- **涉及文件**：`src/contractnet/tools/builtins.py`
- **方案**：Profile 的 `model` 字段改为从 `LLMConfig.from_env()` 读取，或统一设为 `None` 由 Agent 运行时决定

## P1 — 运行时基础设施

### 5. 安装项目并跑通测试

- **问题**：环境未安装 `contractnet` 包和 `pytest`，测试无法运行
- **步骤**：
  - `pip install -e ".[all]"`
  - `pytest -v` 确认现有 8 个测试文件通过
  - 修复因缺少 Redis 导致的 `StateStore` 测试失败（如有）

### 6. Token 统计接线

- **问题**：`Orchestrator._total_tokens` 始终为 0，Agent 执行未上报 token
- **涉及文件**：`src/contractnet/core/orchestrator.py`、`src/contractnet/core/agent.py`
- **方案**：`execute()` 返回 `ExecutionRecord`（含 `tokens_used`），Orchestrator 累加

### 7. StateStore 降级策略

- **问题**：`StateStore` 依赖 Redis，无 Redis 时应优雅降级到纯 SQLite
- **涉及文件**：`src/contractnet/memory/state_store.py`
- **方案**：Redis 连接失败时 warn + fallback，不 crash

## P2 — CLI 与评估补全

### 8. 实现 `contractnet replay`

- **涉及文件**：`src/contractnet/cli.py`、`src/contractnet/observability/tracer.py`
- **方案**：从 StateStore 读取 trace 记录，按时间轴重放执行过程

### 9. 实现 `contractnet eval`

- **涉及文件**：`src/contractnet/cli.py`、`eval/runner.py`
- **方案**：从 `eval/runner.py` 的 `EvalRunner` 生成评估报告，输出 JSON / Markdown

### 10. 补充 Eval Benchmark 用例

- **问题**：`eval/benchmarks/__init__.py` 为空
- **方案**：新增 3-5 个标准 benchmark（如 Todo API、数据分析报告、文档生成），含输入 goal + 预期 artifact schema + 评分维度

## P3 — 增强与优化

### 11. Agent 记忆系统

- **涉及文件**：`src/contractnet/memory/agent_memory.py`（已有 154 行）
- **目标**：将 `FailurePattern` / `SuccessTemplate` 接入 Agent 竞标置信度计算

### 12. 并发模型升级

- **现状**：`ThreadPoolExecutor` 线程池并发
- **目标**：评估迁移到 `asyncio` 的可行性（LLM IO 密集型场景收益大）
- **注意**：`pyproject.toml` 已声明 `pytest-asyncio`，但代码全同步

### 13. Orchestrator 代码清理

- `_execute_task` 中 `dag_status = TaskStatus.RUNNING` 赋值后未使用（死代码）
- `cancel_task` / `inject_human_feedback` 仅有日志，无实际逻辑
- `get_status()` 返回全零快照，未从 DAG 读取真实状态

### 14. 安全审计

- `.env` 包含真实 API Key（已正确被 `.gitignore` 排除，未进入 git 跟踪 ✓）
- 考虑增加 `.env.example` 模板文件
- `tools/sandbox.py` 权限白名单需评审（确认无命令注入风险）

## 建议执行顺序

```
5 (安装环境) → 1 (ReAct Agent) → 4 (模型对齐) → 2 (Planner 注入) → 3 (Judge 注入)
    → 端到端验证（contractnet run 跑通真实 LLM 链路）
    → 6 (Token 统计) → 7 (StateStore 降级)
    → 8, 9, 10 (CLI + Eval 补全)
    → 11, 12, 13, 14 (增强优化)
```

**里程碑**：完成 P0 + P1 后，项目即可端到端运行真实 LLM 多 Agent 协作。
