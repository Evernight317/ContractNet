# ContractNet

> 契约驱动的多 Agent 协作调度框架

ContractNet 基于分布式系统经典协议（FIPA Contract Net Protocol），实现多 Agent 的动态协作调度：任务自动分解 → Agent 竞标仲裁 → 三层质量门控 → 运行时重规划。

## 当前状态

项目处于 **端到端可用** 阶段。LLM 执行链路已打通，支持从 CLI 提交目标到产出完整 Artifact 的全流程运行。已通过智谱 GLM-4.5 端到端验证（6 任务、6 Artifact、455K tokens、43 测试通过）。

| 模块 | 状态 | 说明 |
|---|---|---|
| `core/types.py` | ✅ 完成 | Task / Contract / Bid / Artifact / TaskDAG 全部定义 |
| `core/planner.py` | ✅ 完成 | LLM 驱动 HTN 分解 + 规则兜底 + 动态重规划 |
| `core/auctioneer.py` | ✅ 完成 | 竞标采集、综合评分、约束放宽、无标处理 |
| `core/orchestrator.py` | ✅ 完成 | 调度主循环 + 并发执行 + token 统计 + 任务取消 |
| `core/quality_gate.py` | ✅ 完成 | 三层校验（Schema + LLM-as-Judge + Impact），robust JSON 解析 |
| `core/conflict_resolver.py` | ✅ 完成 | 5 种冲突检测 + 5 种消解策略 |
| `core/agent.py` | ✅ 完成 | 基类 + 竞标逻辑 + AgentMemory 集成 |
| `core/react_agent.py` | ✅ 完成 | ReAct 循环：Think → Act(tool) → Observe，支持记忆上下文注入 |
| `llm/client.py` | ✅ 完成 | OpenAI 兼容、重试退避、GLM thinking 字段适配 |
| `memory/state_store.py` | ✅ 完成 | SQLite 冷存储 + Redis 热缓存（自动降级） |
| `memory/agent_memory.py` | ✅ 完成 | 执行日志 + 失败模式 + 成功模板 + 性能画像 |
| `tools/sandbox.py` | ✅ 完成 | subprocess 沙箱 + 权限白名单 + 路径穿越防护 |
| `tools/builtins.py` | ✅ 完成 | 6 类预设 Agent + 7 个工具定义 |
| `observability/tracer.py` | ✅ 完成 | OpenTelemetry trace + 指标采集 |
| `observability/dashboard.py` | ✅ 完成 | Streamlit DAG / Trace / Metrics 可视化（页面骨架） |
| `cli.py` | ✅ 完成 | 8 个命令：run / agents / dag / status / replay / eval / conflicts / dashboard |
| `eval/` | ✅ 完成 | metrics + runner + 5 个 benchmark 用例（easy/medium/hard） |
| 测试 | ✅ 通过 | 43 个测试覆盖核心模块，pytest 全绿 |

## 核心特性

- **契约驱动**：Agent 通过能力声明竞标子任务，调度器按成本/置信度仲裁
- **ReAct 执行**：Agent 通过 LLM 多轮推理 + 工具调用执行任务，非硬编码返回
- **动态重规划**：执行失败时自动触发细化分解 / 降级 / 串行化
- **三层质量门控**：Schema 校验 → LLM-as-Judge 语义校验 → 影响冲突检测
- **冲突消解**：文件写冲突 / 接口不一致 / 语义矛盾 / 依赖违规 / 死锁 — 五种策略自动处理
- **Agent 记忆**：跨任务经验积累（成功模板 + 失败模式），注入后续执行上下文
- **全链路可观测**：OpenTelemetry trace + Streamlit Dashboard + 执行回放

## 快速开始

```bash
# 安装（含 dashboard + eval 可选依赖）
pip install -e ".[all]"

# 配置 LLM — 复制模板并填入密钥
cp .env.example .env
# 编辑 .env 设置 CONTRACTNET_API_KEY 和 CONTRACTNET_MODEL

# CLI 提交目标
contractnet run "实现一个带 JWT 认证的 Todo API，包含测试和文档"

# 查看可用 Agent
contractnet agents

# 查看 DAG
contractnet dag

# 回放执行
contractnet replay <goal_id>

# 导出评估报告
contractnet eval <goal_id>

# 启动 Dashboard
contractnet dashboard
```

## 项目结构

```
contractnet/
├── src/contractnet/
│   ├── core/
│   │   ├── types.py              # 全局数据结构 (Task, Contract, Bid, Artifact, TaskDAG)
│   │   ├── contract.py           # 契约管理器
│   │   ├── agent.py              # Agent 基类 + 能力画像 + 竞标逻辑 + AgentMemory
│   │   ├── react_agent.py        # ReAct Agent: Think→Act→Observe 循环
│   │   ├── planner.py            # 任务分解器 (LLM 驱动 HTN + 规则兜底)
│   │   ├── auctioneer.py         # 竞标仲裁器
│   │   ├── orchestrator.py       # 调度器主循环 + 并发 + token 统计
│   │   ├── quality_gate.py       # 三层质量门控 + robust JSON 解析
│   │   └── conflict_resolver.py  # 冲突消解器 (5 种检测 + 5 种策略)
│   ├── llm/
│   │   └── client.py             # OpenAI 兼容 LLM 客户端
│   ├── memory/
│   │   ├── state_store.py        # 全局状态 (Redis + SQLite, 自动降级)
│   │   └── agent_memory.py       # Agent 记忆 (失败模式 + 成功模板)
│   ├── tools/
│   │   ├── sandbox.py            # 工具沙箱 (权限 + 资源限制 + 路径防护)
│   │   └── builtins.py           # 内置工具定义 + 6 类预置 Agent
│   ├── observability/
│   │   ├── tracer.py             # 执行追踪 + 指标采集
│   │   └── dashboard.py          # Streamlit 可视化
│   └── cli.py                    # CLI 入口 (8 个命令)
├── eval/                         # 评估框架 (metrics + runner + 5 benchmarks)
├── tests/                        # 测试 (43 个, 全通过)
├── examples/                     # 示例 (quick_start + eval_demo)
├── .env.example                  # LLM 配置模板
├── TASKS.md                      # 开发路线图
└── pyproject.toml
```

## 执行流程

```
User Goal → Planner (HTN 分解) → DAG
    ↓
Ready Tasks → Contract → Auctioneer (竞标 → 仲裁) → ReAct Agent 执行
    ↓                                            ↓ Think → Act(tool) → Observe
Artifact → Quality Gate (Schema → Semantic → Impact)
    ↓ Pass                          ↓ Fail
State Store                    Re-plan (细化/降级/串行化)
    ↓
Conflict Resolver (检测 → 消解)
    ↓
Final Result (Artifacts + Metrics + Trace)
```

## 数据模型

核心类型定义于 `core/types.py`，全部使用 Pydantic v2：

- **Task** — 子任务单元，含状态机 (PENDING → AUCTIONING → ASSIGNED → RUNNING → REVIEWING → DONE/FAILED/REPLANNED/IMPOSSIBLE)
- **Contract** — 任务契约，含约束 (token 上限、工具白名单、质量阈值)
- **Bid** — Agent 竞标声明 (能力分、预估成本、置信度)
- **Artifact** — 产出物，含版本和文件路径
- **TaskDAG** — 任务有向无环图，支持依赖解析和动态合并
- **Conflict / Resolution** — 冲突与消解策略

## LLM 配置

支持任意 OpenAI 兼容端点，通过 `.env` 文件或环境变量配置：

| 变量 | 说明 | 默认值 |
|---|---|---|
| `CONTRACTNET_API_KEY` | API 密钥（必填） | — |
| `CONTRACTNET_BASE_URL` | 端点 URL | `https://api.openai.com/v1` |
| `CONTRACTNET_MODEL` | 默认模型 | `gpt-4o-mini` |

已测试兼容的端点：

| 提供商 | 端点 | 模型 |
|---|---|---|
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` | `glm-4.5`, `glm-4-plus`, `glm-5`, `glm-5.1` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o`, `gpt-4o-mini` |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |

## CLI 命令

| 命令 | 说明 |
|---|---|
| `contractnet run <goal>` | 提交目标，执行多 Agent 协作 |
| `contractnet agents` | 列出所有预置 Agent |
| `contractnet dag` | 查看任务 DAG |
| `contractnet status` | 查看系统状态 |
| `contractnet replay <goal_id>` | 回放已完成的目标执行 |
| `contractnet eval <goal_id>` | 导出评估报告 (JSON) |
| `contractnet conflicts` | 查看冲突日志 |
| `contractnet dashboard` | 启动 Streamlit Dashboard |

## 开发

```bash
# 安装开发依赖
pip install -e ".[all]"

# 运行测试
pytest

# 运行示例
python examples/quick_start.py

# 代码风格检查（如已安装 ruff）
ruff check src/ tests/
```

## 技术栈

| 层级 | 技术 |
|---|---|
| Agent 基类 | 自研轻量抽象（不依赖 LangChain） |
| LLM 调用 | OpenAI SDK（兼容智谱/DeepSeek 等端点） |
| 契约定义 | Pydantic v2 |
| 状态持久化 | SQLite + Redis（自动降级） |
| 工具沙箱 | subprocess + 权限白名单 + 路径防护 |
| 可观测性 | OpenTelemetry + Streamlit |
| 评估 | pytest + 自研 eval framework + 5 benchmarks |
| Python | >= 3.11 |

## License

MIT
