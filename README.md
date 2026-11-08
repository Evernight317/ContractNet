# ContractNet

> 契约驱动的多 Agent 协作调度框架

ContractNet 基于分布式系统经典协议（FIPA Contract Net Protocol），实现多 Agent 的动态协作调度：任务自动分解 → Agent 竞标仲裁 → 三层质量门控 → 运行时重规划。

## 核心特性

- **契约驱动**：Agent 通过能力声明竞标子任务，调度器按成本/置信度仲裁
- **动态重规划**：执行失败时自动触发细化分解 / 降级 / 串行化
- **三层质量门控**：Schema 校验 → LLM-as-Judge 语义校验 → 影响冲突检测
- **冲突消解**：文件写冲突 / 接口不一致 / 语义矛盾 / 死锁 — 五种策略自动处理
- **全链路可观测**：OpenTelemetry trace + Streamlit 实时 Dashboard + 执行回放

## 快速开始

```bash
# 安装
pip install -e ".[all]"

# CLI 提交目标
contractnet run "实现一个带 JWT 认证的 Todo API，包含测试和文档"

# 查看可用 Agent
contractnet agents

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
│   │   ├── agent.py              # Agent 基类 + 能力画像
│   │   ├── planner.py            # 任务分解器 (LLM 驱动 HTN)
│   │   ├── auctioneer.py         # 竞标仲裁器
│   │   ├── orchestrator.py       # 调度器主循环
│   │   ├── quality_gate.py       # 三层质量门控
│   │   └── conflict_resolver.py  # 冲突消解器
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
├── eval/                         # 评估框架
├── tests/                        # 测试
├── examples/                     # 示例
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

## 开发

```bash
# 安装开发依赖
pip install -e ".[all]"

# 运行测试
pytest

# 运行示例
python examples/quick_start.py
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

## License

MIT
