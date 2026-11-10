# ContractNet 开发路线图

> 基于 2026-11-09 代码审计生成，2026-11-10 更新。

## 完成进度

| 阶段 | 状态 | Commit |
|---|---|---|
| P0 — LLM 执行链路 | ✅ 完成 | `784eb8e` |
| P1 — 运行时基础设施 | ✅ 完成 | `34cece3` |
| P2 — CLI 与评估补全 | ✅ 完成 | `34cece3` |
| P3 — 增强与优化 | ✅ 完成 | `9ffdd8f` |

---

## P0 — 打通 LLM 执行链路（核心阻塞项） ✅

1. **实现 LLM 驱动的 ReAct Agent** — 新建 `react_agent.py`，Think→Act→Observe 循环
2. **将 LLMClient 注入 Planner** — 任务分解从规则兜底升级为 LLM 驱动
3. **将 LLMClient 注入 QualityGate** — 启用 LLM-as-Judge 语义校验
4. **Agent Profile 模型对齐** — 硬编码 model 改为 None，运行时从 env 决定

## P1 — 运行时基础设施 ✅

5. **安装项目并跑通测试** — `pip install -e ".[all]"`，43 测试全通过
6. **Token 统计接线** — Orchestrator 从 Agent 执行日志累加 token
7. **StateStore 降级策略** — 自动尝试 Redis，失败时降级到纯 SQLite

## P2 — CLI 与评估补全 ✅

8. **实现 `contractnet replay`** — 从 StateStore 读取 DAG + artifacts，展示任务时间线
9. **实现 `contractnet eval`** — 导出 JSON 评估报告
10. **补充 Eval Benchmark 用例** — 5 个标准 benchmark（easy/medium/hard 分级）

## P3 — 增强与优化 ✅

11. **Agent 记忆系统** — AgentMemory 接入 BaseAgent，ReActAgent 注入经验上下文
12. **并发模型升级** — ⏸ 暂缓（ThreadPoolExecutor 可用，asyncio 迁移投入产出比低）
13. **Orchestrator 代码清理** — get_status/cancel_task/inject_human_feedback 全部实现
14. **安全审计** — `.env.example` 已添加，sandbox 路径穿越防护已修复

## 后续方向

- asyncio 全链路迁移（当并发成为瓶颈时）
- 跨 Agent 记忆共享（当前 AgentMemory 为每 Agent 独立）
- Human-in-the-loop CLI 交互界面
- Web Dashboard 实时监控集成
- 更多 benchmark 用例和自动评分
