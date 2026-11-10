<p align="center">
  <h1 align="center">ContractNet</h1>
  <p align="center">契约驱动的多 Agent 协作调度框架</p>
  <p align="center">
    <img src="https://img.shields.io/badge/python-3.11+-blue" alt="Python">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
    <img src="https://img.shields.io/badge/tests-43%20passed-brightgreen" alt="Tests">
    <img src="https://img.shields.io/badge/status-end--to--end%20usable-orange" alt="Status">
  </p>
</p>

---

## 概述

ContractNet 基于分布式系统经典协议（FIPA Contract Net Protocol），实现多 Agent 的动态协作调度。用户提交高层目标后，系统自动完成任务分解、Agent 竞标仲裁、ReAct 执行、三层质量校验和冲突消解，无需手动编排 Agent 交互。

```
用户目标 → Planner (HTN 分解) → Task DAG
                                        ↓
                    Contract → Auctioneer (竞标仲裁) → ReAct Agent 执行
                                        ↓                              ↗ Think → Act → Observe
                    Artifact → Quality Gate (Schema → Semantic → Impact)
                          ↓ Pass                    ↓ Fail
                    State Store              Re-plan (细化 / 降级 / 串行化)
                          ↓
                    Conflict Resolver (检测 → 消解)
                          ↓
                    Final Result (Artifacts + Metrics + Trace)
```

## 核心能力

| 能力 | 说明 |
|---|---|
| **契约驱动调度** | Agent 通过能力声明竞标子任务，Auctioneer 按能力/成本/置信度综合评分仲裁 |
| **ReAct 执行引擎** | Agent 通过 LLM 多轮推理 + 工具调用（文件读写、代码执行、测试运行）完成任务 |
| **三层质量门控** | Layer 1: JSON Schema 校验 → Layer 2: LLM-as-Judge 语义校验 → Layer 3: 冲突影响检测 |
| **动态重规划** | 任务失败时自动选择策略：重试 / 细化分解 / 降级模型 / 串行化 / 约束放宽 |
| **冲突消解** | 5 种检测（文件写冲突 / 接口不一致 / 语义矛盾 / 依赖违规 / 死锁）+ 5 种消解策略 |
| **Agent 记忆** | 跨任务经验积累：成功模板复用 + 失败模式预警，注入后续执行上下文 |
| **可观测性** | OpenTelemetry trace 追踪 + Streamlit Dashboard + 执行回放 |

## 快速开始

### 安装

```bash
git clone https://github.com/Evernight317/ContractNet.git
cd ContractNet
pip install -e ".[all]"
```

### 配置 LLM

```bash
cp .env.example .env
# 编辑 .env，填入你的 API Key
```

支持任意 OpenAI 兼容端点：

| 提供商 | `CONTRACTNET_BASE_URL` | 推荐模型 |
|---|---|---|
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` | `glm-4.5`, `glm-5.1` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o`, `gpt-4o-mini` |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |

### 运行

```bash
# 提交目标 — 从分解到产出全自动
contractnet run "实现一个带 JWT 认证的 Todo API，包含测试和文档"

# 查看任务 DAG
contractnet dag

# 回放执行过程
contractnet replay <goal_id>

# 导出评估报告
contractnet eval <goal_id>

# 启动可视化 Dashboard
contractnet dashboard
```

## CLI 命令一览

| 命令 | 说明 |
|---|---|
| `contractnet run <goal>` | 提交目标，启动多 Agent 协作执行 |
| `contractnet agents` | 列出所有预置 Agent 类型和能力 |
| `contractnet dag` | 查看当前任务 DAG（依赖关系和状态） |
| `contractnet status` | 查看系统实时状态 |
| `contractnet replay <goal_id>` | 回放已完成的目标执行 |
| `contractnet eval <goal_id>` | 导出 JSON 评估报告（任务/Artifact/质量分） |
| `contractnet conflicts` | 查看冲突检测和消解日志 |
| `contractnet dashboard` | 启动 Streamlit Web Dashboard |

## 预置 Agent

| Agent | 任务类型 | 可用工具 |
|---|---|---|
| Coder | `code`, `design` | file_read, file_write, code_run, list_dir |
| Tester | `test` | file_read, code_run, test_run, list_dir |
| Doc Writer | `doc` | file_read, file_write, list_dir |
| Analyst | `analysis` | data_read, code_run, file_read, file_write |
| Reviewer | `review` | file_read, list_dir |
| General | `*`（通用） | file_read, file_write, code_run, list_dir |

Agent 通过 `CapabilityProfile` 声明能力，竞标时 Auctioneer 根据任务类型匹配度、工具覆盖、历史性能综合评分。

## 项目结构

```
ContractNet/
├── src/contractnet/
│   ├── core/
│   │   ├── types.py              # 全局数据结构 (Pydantic v2)
│   │   ├── contract.py           # 契约管理器
│   │   ├── agent.py              # Agent 基类 + 竞标逻辑 + AgentMemory
│   │   ├── react_agent.py        # ReAct Agent: Think→Act→Observe 循环
│   │   ├── planner.py            # LLM 驱动 HTN 任务分解 + 动态重规划
│   │   ├── auctioneer.py         # 竞标仲裁器 (综合评分 + 约束放宽)
│   │   ├── orchestrator.py       # 调度主循环 + 并发执行 + token 统计
│   │   ├── quality_gate.py       # 三层质量门控 + robust JSON 解析
│   │   └── conflict_resolver.py  # 冲突消解 (5 检测 + 5 策略)
│   ├── llm/
│   │   └── client.py             # OpenAI 兼容客户端 (重试退避 + GLM 适配)
│   ├── memory/
│   │   ├── state_store.py        # 全局状态 (SQLite + Redis 自动降级)
│   │   └── agent_memory.py       # Agent 记忆 (成功模板 + 失败模式)
│   ├── tools/
│   │   ├── sandbox.py            # 工具沙箱 (权限白名单 + 路径防护)
│   │   └── builtins.py           # 7 个工具定义 + 6 类预置 Agent
│   ├── observability/
│   │   ├── tracer.py             # OpenTelemetry trace + 指标采集
│   │   └── dashboard.py          # Streamlit 可视化
│   └── cli.py                    # CLI 入口 (8 个命令)
├── eval/
│   ├── metrics.py                # 评估指标定义
│   ├── runner.py                 # 评估执行器 (LLM-aware)
│   └── benchmarks/               # 5 个标准 benchmark (easy/medium/hard)
├── tests/                        # 43 个测试，全通过
├── examples/                     # 快速开始 + 评估演示
├── .env.example                  # LLM 配置模板
├── TASKS.md                      # 开发路线图
└── pyproject.toml
```

## 数据模型

核心类型定义于 `core/types.py`，全部使用 Pydantic v2：

- **Task** — 子任务单元，含 9 态状态机 (PENDING → AUCTIONING → ASSIGNED → RUNNING → REVIEWING → DONE / FAILED / REPLANNED / IMPOSSIBLE)
- **Contract** — 任务契约，含约束 (token 上限、工具白/黑名单、质量阈值、步数上限)
- **Bid** — Agent 竞标声明 (能力分、预估成本、置信度、执行计划)
- **Artifact** — 产出物，含版本号、文件路径、质量分
- **TaskDAG** — 任务有向无环图，支持依赖解析、动态合并、死锁检测
- **Conflict / Resolution** — 5 种冲突类型 + 5 种消解策略

## 评估框架

内置 5 个标准 benchmark，覆盖不同难度：

| Benchmark | 难度 | 目标 |
|---|---|---|
| Fibonacci Function | easy | Python 函数 + 测试 + 文档 |
| Todo API with JWT | medium | 全栈 API（认证 + CRUD + 测试 + 文档） |
| Sales Data Analysis | medium | 数据分析 + 报告生成 |
| Bug Fix Pipeline | hard | Bug 诊断 + 修复 + 回归测试 |
| Code Refactor | hard | 大规模重构 + 测试保持 |

```bash
# 通过 eval runner 运行 benchmark
python examples/eval_demo.py
```

## 开发

```bash
# 安装开发依赖
pip install -e ".[all]"

# 运行测试
pytest -v

# 运行示例
python examples/quick_start.py

# 代码风格检查
ruff check src/ tests/
```

## 技术栈

| 层级 | 技术选型 |
|---|---|
| Agent 框架 | 自研轻量抽象（不依赖 LangChain） |
| LLM 调用 | OpenAI SDK（兼容智谱 / DeepSeek / 任意 OpenAI 兼容端点） |
| 数据模型 | Pydantic v2 |
| 状态持久化 | SQLite（冷存储）+ Redis（热缓存，可选自动降级） |
| 工具沙箱 | subprocess 隔离 + 权限白名单 + 路径穿越防护 |
| 可观测性 | OpenTelemetry + Streamlit |
| 评估 | pytest + 自研 eval framework + 5 benchmarks |
| 并发模型 | ThreadPoolExecutor（asyncio 迁移为后续方向） |
| Python | >= 3.11 |

## 路线图

详见 [TASKS.md](TASKS.md)。P0-P3 已全部完成，后续方向：

- Web Dashboard 实时监控集成（接入 StateStore + Tracer 真实数据）
- 跨 Agent 记忆共享（全局经验层）
- Human-in-the-loop CLI 交互界面
- Benchmark 自动评分（LLM-as-Judge 或规则校验 artifact 内容）
- asyncio 全链路迁移

## License

MIT
