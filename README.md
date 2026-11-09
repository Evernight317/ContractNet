# ContractNet

> 契约驱动的多 Agent 协作调度框架

ContractNet 基于分布式系统经典协议（FIPA Contract Net Protocol），实现多 Agent 的动态协作调度：任务自动分解 → Agent 竞标仲裁 → 三层质量门控 → 运行时重规划。

## 当前状态

项目处于 **骨架完成 + 核心待联通** 阶段。架构设计与模块边界已清晰，核心数据结构和调度主循环可运行，但 LLM 执行链路尚未打通。

| 模块 | 状态 | 说明 |
|---|---|---|
| `core/types.py` | ✅ 完成 | Task / Contract / Bid / Artifact / TaskDAG 全部定义 |
| `core/planner.py` | ⚠️ 半完成 | 规则兜底可用；LLM 分解接口就绪但未注入 client |
| `core/auctioneer.py` | ✅ 完成 | 竞标采集、综合评分、约束放宽、无标处理 |
| `core/orchestrator.py` | ⚠️ 半完成 | 主循环可跑，但用的是 StubAgent，无真实执行 |
| `core/quality_gate.py` | ⚠️ 半完成 | Schema 层可用；Semantic 层需 judge_client |
| `core/conflict_resolver.py` | ✅ 完成 | 5 种冲突检测 + 5 种消解策略 |
| `core/agent.py` | ⚠️ 半完成 | 基类 + 竞标逻辑完整；`execute()` 为抽象方法，无 ReAct 实现 |
| `llm/client.py` | ✅ 完成 | OpenAI 兼容、重试退避、GLM thinking 适配 |
| `memory/state_store.py` | ⚠️ 半完成 | SQLite 可用；Redis Pub/Sub 依赖运行实例 |
| `tools/sandbox.py` | ✅ 完成 | subprocess 沙箱 + 权限白名单 |
| `tools/builtins.py` | ✅ 完成 | 6 类预设 Agent + 7 个工具定义 |
| `observability/tracer.py` | ✅ 完成 | OpenTelemetry trace + 指标采集 |
| `observability/dashboard.py` | ✅ 完成 | Streamlit DAG / Trace / Metrics 可视化 |
| `cli.py` | ⚠️ 半完成 | 8 个命令；`replay` / `eval` 为占位 |
| `eval/` | ⚠️ 半完成 | metrics + runner 框架就绪，无 benchmark 用例 |
| 测试 | ⚠️ 基础 | 8 个测试文件覆盖核心模块，但环境未安装 |

## 核心特性

- **契约驱动**：Agent 通过能力声明竞标子任务，调度器按成本/置信度仲裁
- **动态重规划**：执行失败时自动触发细化分解 / 降级 / 串行化
- **三层质量门控**：Schema 校验 → LLM-as-Judge 语义校验 → 影响冲突检测
- **冲突消解**：文件写冲突 / 接口不一致 / 语义矛盾 / 依赖违规 / 死锁 — 五种策略自动处理
- **全链路可观测**：OpenTelemetry trace + Streamlit 实时 Dashboard + 执行回放

## 快速开始

```bash
# 安装（含 dashboard + eval 可选依赖）
pip install -e ".[all]"

# 配置 LLM — 编辑 .env
# CONTRACTNET_API_KEY=your_key
# CONTRACTNET_BASE_URL=https://open.bigmodel.cn/api/paas/v4
# CONTRACTNET_MODEL=glm-4.7-flash

# CLI 提交目标
contractnet run "实现一个带 JWT 认证的 Todo API，包含测试和文档"

# 查看可用 Agent
contractnet agents

# 查看 DAG
contractnet dag

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
│   │   ├── agent.py              # Agent 基类 + 能力画像 + 竞标逻辑
│   │   ├── planner.py            # 任务分解器 (LLM 驱动 HTN)
│   │   ├── auctioneer.py         # 竞标仲裁器
│   │   ├── orchestrator.py       # 调度器主循环
│   │   ├── quality_gate.py       # 三层质量门控
│   │   └── conflict_resolver.py  # 冲突消解器
│   ├── llm/
│   │   └── client.py             # OpenAI 兼容 LLM 客户端
│   ├── memory/
│   │   ├── state_store.py        # 全局状态 (Redis + SQLite)
│   │   └── agent_memory.py       # Agent 局部记忆
│   ├── tools/
│   │   ├── sandbox.py            # 工具沙箱 (权限 + 资源限制)
│   │   └── builtins.py           # 内置工具定义 + 预置 Agent
│   ├── observability/
│   │   ├── tracer.py             # 执行追踪 + 指标采集
│   │   └── dashboard.py          # Streamlit 可视化
│   └── cli.py                    # CLI 入口
├── eval/                         # 评估框架 (metrics + runner)
├── tests/                        # 测试 (8 个核心模块测试)
├── examples/                     # 示例 (quick_start + eval_demo)
└── pyproject.toml
```

## 执行流程

```
User Goal → Planner (HTN 分解) → DAG
    ↓
Ready Tasks → Contract → Auctioneer (竞标 → 仲裁) → Agent 执行
    ↓
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

支持任意 OpenAI 兼容端点，通过环境变量或 `.env` 配置：

| 变量 | 说明 | 默认值 |
|---|---|---|
| `CONTRACTNET_API_KEY` | API 密钥（必填） | — |
| `CONTRACTNET_BASE_URL` | 端点 URL | `https://api.openai.com/v1` |
| `CONTRACTNET_MODEL` | 默认模型 | `gpt-4o-mini` |

当前 `.env` 配置：智谱 GLM-4.7-flash（`client.py` 已处理 GLM thinking 字段禁用）。

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
| LLM 调用 | OpenAI / Anthropic SDK 直调 |
| 契约定义 | Pydantic v2 |
| 消息总线 | Redis Pub/Sub |
| 状态持久化 | SQLite + Redis |
| 工具沙箱 | subprocess + 权限白名单 |
| 可观测性 | OpenTelemetry + Streamlit |
| 评估 | pytest + 自研 eval framework |
| Python | >= 3.11 |

## License

MIT
