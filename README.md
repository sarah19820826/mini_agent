# Agent 项目结构文档

> 基于 Agent.md 文档整理的完整项目实现

## 项目结构

```
agent-project/
├── main.py                     # 入口文件，交互式运行 agent
├── context_compressor.py       # 上下文压缩模块
├── config/
│   ├── __init__.py
│   └── settings.py             # 配置文件（LLM/循环/压缩/委托参数）
├── agent/
│   ├── __init__.py
│   ├── agent.py                # IdleAgent：顶层 agent，管理工具/记忆/skill/会话
│   ├── loop.py                 # AgentLoop：ReAct 主循环 + 六重保障
│   └── delegate.py             # DelegateManager：子 agent 委托管理
├── tools/
│   ├── __init__.py
│   ├── tool_registry.py        # 工具注册表（注册/查询/过滤）
│   ├── tool_dispatcher.py      # 工具分发器（执行/名称修复/参数修复/进度预览）
│   └── todo_tool.py            # Todo 工具（计划管理，merge/replace 模式）
├── memory/
│   ├── __init__.py
│   └── memory_manager.py       # 记忆管理（add/replace/remove/安全扫描/预取/流式清洗）
├── skill/
│   ├── __init__.py
│   ├── skills_loader.py        # Skill 加载器（四阶段渐进式加载）
│   └── skill_service.py        # Skill 服务（条件注册/工具分发/MCP 联动）
├── utils/
│   ├── __init__.py
│   ├── llm_client.py           # LLM 客户端接口（抽象层）
│   ├── error_classifier.py     # 错误分类器（15+ 错误类型 + 恢复策略）
│   └── async_bridge.py         # 异步桥接（同步上下文执行异步）
└── skills-example/
    └── log-diagnosis/          # 示例 skill
        ├── SKILL.md
        ├── references/
        │   └── error-patterns.md
        └── scripts/
```

## 核心流程

### ReAct 主循环

```
用户请求
  │
  ▼
┌──────────────────────────────────┐
│ ① 迭代预算检查  → 超限则优雅退出   │
│ ② 中断检查        → 用户取消则退出  │
│ ③ 上下文压缩检查   → 75%阈值触发压缩 │
│ ④ 记忆预取注入     → <memory-context> 围栏 │
│ ⑤ THINK: 调用 LLM  → 错误分类+重试    │
│ ⑥ 空响应防护       → 连续2次空则终止   │
│ ⑦ 有 tool_calls？  → 是:ACT  否:DONE  │
└──────────────────────────────────┘
```

### 上下文压缩三步策略

1. **划分保护区** — HEAD(前3条 system+首轮) + TAIL(后6条最近对话) 不动
2. **修剪中间区工具输出** — 3000 字 → 单行摘要
3. **LLM 结构化摘要** — 13 个字段浓缩中间区

降级链：减少尾部 → 删除旧工具结果 → 紧急截断

### Skill 四阶段渐进式加载

| 阶段 | 触发时机 | 开销 |
|------|----------|------|
| Advertise | 启动时扫描 | ~100 tokens/skill |
| Load | LLM 判断匹配 | 500-2000 tokens |
| Read | 指令引用参考资料 | 按需读取 |
| Run | 需要执行脚本 | 30s 超时保护 |

### 子 Agent 委托（Orchestrator-Worker）

```
主 Agent (全部权限)
  │
  ├── 深度检查 → 超限降级为 leaf
  ├── 并发检查 → ≥3 个等待
  ├── 提交 ThreadPoolExecutor
  └── 带超时等待结果
       │
       ├── 子 Agent A (leaf, 受限权限)
       └── 子 Agent B (leaf, 受限权限)
```

**权限隔离**：子 agent 禁止 `delegate_task`（防递归）、`memory`（防并发写入）、`clarify`（无法与用户交互）

## 模块间依赖关系

```
IdleAgent (agent/agent.py)
├── AgentLoop (agent/loop.py)
│   ├── ContextCompressor (context_compressor.py)
│   ├── MemoryManager (memory/memory_manager.py)
│   ├── ToolDispatcher (tools/tool_dispatcher.py)
│   │   ├── ToolRegistry (tools/tool_registry.py)
│   │   └── TodoStore (tools/todo_tool.py)
│   └── ErrorClassifier (utils/error_classifier.py)
├── DelegateManager (agent/delegate.py)
│   └── IdleAgent (递归引用，延迟导入)
├── SkillService (skill/skill_service.py)
│   └── SkillsLoader (skill/skills_loader.py)
└── LLM Client (utils/llm_client.py)
```

## 关键设计

1. **Plan 即工具** — todo 不是模式切换，就是 ReAct 循环中的一个工具调用
2. **条件注册** — 只有 skill 包含资源/脚本时才注册对应工具，减少 token 浪费
3. **错误分类 > 盲目重试** — 15+ 种错误类型，上下文溢出→压缩、限流→等待、认证→终止
4. **压缩防抖** — 平均节省率 < 10% 时跳过压缩，避免无效 LLM 调用
5. **Todo 状态注入** — 压缩后自动恢复未完成计划，防止 agent "失忆"
