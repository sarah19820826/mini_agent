# Agent 项目原理深度解析

> 基于 `agent-project/` 的完整源码分析，从"为什么这样设计"的角度解析七个核心原理。

---

## 1. ReAct (Reasoning + Acting) 循环原理

### 核心概念
让 LLM 交替进行"思考"（THINK）和"行动"（ACT），而不是一次性给出最终答案。每次迭代：先调用 LLM 决定下一步做什么，如果需要工具则执行工具（ACT），不需要则输出最终答案（DONE）。

### 为什么这样设计
LLM 的本质是"文本续补"——它看到什么就补什么。如果直接把问题丢给它，它只能基于训练数据"猜"答案。但如果让它每次只迈一小步（思考→行动→观察结果→再思考），它就能像人一样**逐步推理**。

解决的问题：
- **长链推理**：复杂任务（如"分析项目结构并写文档"）需要多步操作，一步到位容易出错。
- **工具调用**：LLM 本身无法读文件、搜索代码，需要通过工具"观察"世界。
- **可中断性**：每步都有预算检查，超过 200 次迭代自动优雅退出。

### 项目实现方式
在 `agent/loop.py` 的 `AgentLoop.run()` 方法中，核心循环结构为：

```
while 预算充足:
    检查中断信号
    检查上下文压缩 (75% 阈值)
    注入记忆上下文
    THINK: 调用 LLM
    空响应防护
    if 有 tool_calls:
        ACT: 执行工具调用，结果追加到 messages
        continue  ← 回到循环顶部，再次 THINK
    else:
        DONE: 输出最终答案，return
```

关键设计：LLM 的每次输出（无论是否有 tool_calls）都会被追加到 `messages` 列表中，作为下一次 THINK 的"历史上下文"。这样 LLM 能看到自己之前做了什么、得到了什么结果。

### 生活类比
**就像你做一道复杂的菜**：你不会闭着眼睛把所有调料一股脑倒进去（一次性回答），而是"闻一下→觉得淡了→加盐→再闻→够了"（THINK→ACT→观察→THINK→DONE）。ReAct 就是让 LLM 拥有"闻一下"的能力。

---

## 2. 上下文压缩原理

### 核心概念
当对话历史超过上下文窗口 75% 时，自动压缩中间的历史消息，保留"头"（系统指令+首轮对话）和"尾"（最近 6 条消息），用 LLM 生成结构化摘要来替代中间内容。

### 为什么这样设计
LLM 的上下文窗口是有限的（如 128K tokens）。长对话中，早期的工具输出（几 MB 的文件内容、终端输出）会迅速占满窗口。如果不压缩，agent 会在还剩 25% 空间时"猝死"。

为什么是 75% 阈值？——留 25% 的余量来容纳：
- 压缩后新增的摘要消息
- 后续几轮新对话
- 避免在压缩过程中再次触发压缩

### 三步策略的设计逻辑

| 步骤 | 操作 | 目的 |
|------|------|------|
| 1. 保护区 | HEAD(前3条) + TAIL(后6条) 不压缩 | HEAD 含系统指令（不能丢），TAIL 含最近的上下文（LLM 最需要） |
| 2. 修剪工具输出 | 中间区的工具结果从几千字压到一行摘要 | 工具输出的原始内容信息密度极低，如终端输出 500 行可浓缩为"exit 0, 500 lines" |
| 3. LLM 摘要 | 用 13 个字段结构化浓缩中间区 | 规则摘要丢失语义，LLM 能理解"这个对话在做什么" |

### 防抖机制（平均节省率 < 10% 跳过）
`ContextCompressor` 维护了一个 `_recent_savings` 列表（最近 5 次压缩的节省率）。如果中位节省率 < 10%，说明压缩几乎没省出多少空间——可能是因为中间区本来就不大，或者 LLM 生成的摘要比原文还长（小对话的常见问题）。

**解决的问题**：避免"压缩反而膨胀"的陷阱。调用 LLM 做摘要本身有 token 开销，如果只省了 5% 却花了一次 API 调用，得不偿失。

### 降级链（三级后备）
1. 减少尾部保护区（6 → 3 条）
2. 删除最老的 10 个工具结果
3. 紧急截断（只保留 system + 最后 6 条）

### 生活类比
**就像写读书笔记**：你不会把整本书重新抄一遍，而是——
1. 保留书名和目录不动（保护区 HEAD）
2. 把每章几百页内容概括为一句话（修剪）
3. 写一段整体摘要说明这本书讲了什么（LLM 摘要）
4. 如果摘要写出来比原文还长，干脆就划线标记重点（防抖跳过）

---

## 3. Skill 四阶段渐进式加载原理

### 核心概念
Skill（技能包）不是启动时全部加载到系统提示中，而是分四个渐进阶段按需加载：**Advertise → Load → Read → Run**，每个阶段的 token 开销逐级递增。

### 为什么这样设计
假设你有 20 个 skill，每个 skill 完整指令 1500 tokens。如果启动时全部塞进 system prompt：
- 20 × 1500 = **30,000 tokens** 常驻
- 但用户一次对话通常只用 0-1 个 skill
- 这 30,000 tokens 每轮对话都在白白消耗

### 四个阶段的 token 开销

| 阶段 | 触发时机 | token 开销 | 类比 |
|------|----------|------------|------|
| **Advertise** | 启动时扫描 | ~100 tokens/skill（仅名称+描述） | 餐厅菜单封面——只告诉你有哪些菜 |
| **Load** | LLM 调用 `load_skill` 工具 | 500-2000 tokens（完整指令） | 翻开菜单看具体做法 |
| **Read** | 指令引用参考资料 | 按需读取（如 error-patterns.md） | 查看参考手册的具体章节 |
| **Run** | 需要执行脚本 | 不占 token（执行结果才占） | 实际动手做菜 |

### 本质
这是一种**延迟加载（lazy loading）** + **信息分层**的设计。LLM 首先看到 skill 的广告（名称+描述），判断是否需要；需要时才通过 `load_skill` 工具拉取完整指令；指令中提到要读参考资料时再读取。

**条件注册**：`SkillService` 只在有 skill 包含 resources/scripts 时才注册对应的工具，避免工具列表膨胀。

### 项目实现
- `SkillsLoader._discover_skills()`：启动时扫描所有 `SKILL.md` 文件，只解析 frontmatter（name, description）
- `get_advertise_prompt()`：生成 ~100 tokens/skill 的广告文本，注入 system prompt
- `load_skill()`：返回完整的 SKILL.md body（操作手册）
- `read_skill_resource()` + `run_skill_script()`：带路径遍历保护（`realpath` 检查）和 30s 超时

### 生活类比
**就像工具箱**：
- Advertise = 工具箱外贴的标签（"电工工具"、"木工工具"）
- Load = 打开对应的工具盒，看到里面的工具清单
- Read = 取出工具的说明书
- Run = 实际使用工具

你不会一进门就把所有工具箱打开——只打开你需要的那一个。

---

## 4. Orchestrator-Worker 子智能体委托原理

### 核心概念
主 agent（Orchestrator）将复杂任务分解为独立的子任务，委托给并行运行的子 agent（Worker）执行。子 agent 权限受限，不能再次委托、不能修改记忆、不能与用户交互。

### 为什么这样设计
当任务可以并行处理时（如"分析 A 模块"和"分析 B 模块"），串行执行浪费时间。委托给独立的子 agent 可以：
1. **并行加速**：3 个独立子任务同时执行
2. **隔离故障**：子 agent 超时不影响主 agent
3. **控制资源**：并发限制（≤3）、深度限制（≤2）、超时保护（300s）

### 权限隔离的设计
子 agent 被禁止使用：
- `delegate_task`（leaf 模式）：防止无限递归委托
- `memory`：防止多个子 agent 并发写入记忆文件，造成数据竞争
- `clarify`：子 agent 无法与用户交互，只能向父 agent 返回结果

### 深度限制与并发限制
- **深度限制**（默认 2 层）：主 agent → 子 agent → 孙 agent，到第 3 层降级为 leaf。防止委托链过长导致失控。
- **并发限制**（默认 3 个）：通过 `ThreadPoolExecutor` + `active_count` 计数器控制。超过 3 个时等待有空位。

### 项目实现
`DelegateManager.delegate_task()` 的完整流程：
1. 深度检查 → 超限降级为 leaf
2. 并发检查 → 超限时等待 1s
3. 构建子 agent 身份（注入 `DELEGATE_EXECUTION_DISCIPLINE` + 任务目标 + 工作边界）
4. 在 `ThreadPoolExecutor` 中提交任务
5. 带超时（300s）等待结果
6. 返回 `DelegateResult`（含 success、final_answer、耗时、token 数）

### 生活类比
**就像项目经理**：
- 项目经理（Orchestrator）接到一个大项目
- 把"设计 UI"分给设计师（Worker A），"写后端 API"分给后端开发（Worker B）
- 设计师和后端开发不能再把活分给别人（禁止 delegate）
- 他们不能直接找客户确认需求（禁止 clarify），有问题问项目经理
- 他们不能改公司的规章制度（禁止 memory）

---

## 5. 错误分类与恢复原理

### 核心概念
不对 API 错误盲目重试，而是通过三层分类（HTTP 状态码 → 消息模式 → 异常类型）识别 15+ 种错误类型，每种对应不同的恢复策略。

### 为什么这样设计
简单的"出错了就重试"策略有严重缺陷：
- **认证错误**重试 100 次也没用
- **上下文溢出**重试只会重复溢出
- **限流**重试需要等足够长的时间
- **余额不足**重试是在浪费钱

### 三层分类机制

```
Layer 1: HTTP 状态码
  429 → rate_limit → 等待 30s 重试
  401 → auth → 重试（可能临时 token 过期）
  403 → auth_permanent → 终止
  503 → overloaded → 切换 provider
  400 → 需要 Layer 2 进一步判断

Layer 2: 消息模式匹配（正则表达式）
  "context length" / "too many tokens" → context_overflow → 压缩上下文
  "billing" / "quota exceeded" → billing → 终止
  "model not found" → model_not_found → 终止

Layer 3: 异常类型匹配
  ReadTimeout / ConnectError → timeout → 等待 5s 重试
  其他未知 → unknown → 等待 5s 重试（保守策略）
```

### 恢复策略分类

| 策略 | 错误类型 | 操作 |
|------|----------|------|
| **压缩** | context_overflow | 触发上下文压缩，然后重试 |
| **等待重试** | rate_limit, timeout, server_error | 指数退避 + 随机抖动 |
| **终止** | billing, auth_permanent, model_not_found | 不可恢复，直接报错 |
| **保守重试** | unknown | 默认重试，等待 5s |

### 指数退避 + 抖动
`jittered_backoff(attempt)` = `base_delay × 2^attempt + random(0, 50%)`，上限 120s。
抖动（jitter）防止多个请求同时重试导致"惊群效应"。

### 生活类比
**就像去医院**：
- 挂号排队太长（rate_limit）→ 等一会再来
- 诊室满了（overloaded）→ 换一家医院
- 医生说你需要检查（context_overflow）→ 去做检查（压缩）
- 医保余额不足（billing）→ 回家，等有钱了再说
- 不是所有问题都靠"挂号"（重试）能解决的

---

## 6. 记忆系统原理

### 核心概念
用纯文本文件（`.md`）存储跨会话的记忆，每次对话开始时预取记忆内容，注入 `<memory-context>` 围栏标签中。写入时进行安全扫描，防止 prompt 注入和凭证泄露。

### 为什么用文件存储
- **简单可靠**：不需要数据库，`cat memory.md` 就能查看和编辑
- **版本控制**：可以纳入 git，追踪记忆的变化历史
- **可移植**：复制文件即可迁移记忆
- **低开销**：没有连接池、事务等复杂性

### 安全扫描机制
写入记忆前，对内容进行威胁模式匹配：

```python
_THREAT_PATTERNS = [
    (r"(ignore|disregard|forget)\s+.*instructions", "prompt_injection"),
    (r"(api[_-]?key|secret|password|token)\s*[:=]\s*\S+", "credential_exposure"),
    (r"<memory-context>|</memory-context>", "fence_tag_injection"),
]
```

防止三种攻击：
1. **Prompt 注入**：恶意外部内容让 agent 忽略原有指令
2. **凭证泄露**：防止 API key 等敏感信息被存入记忆
3. **围栏标签注入**：防止恶意注入 `<memory-context>` 标签嵌套，破坏围栏结构

### 记忆预取与围栏注入
每轮对话开始前：
1. 提取最新的用户查询
2. 调用 `MemoryManager.prefetch_all(user_query)` 获取所有记忆
3. 用 `<memory-context>...</memory-context>` 标签包裹
4. 作为特殊的 `role: "user"` 消息注入到 messages

围栏标签的作用：告诉 LLM"这是回忆起来的背景信息，不是新的用户输入"。标签内还包含系统注释：

```
[System note: The following is recalled memory context,
NOT new user input. Treat as authoritative reference data]
```

### 流式清洗（StreamingContextScrubber）
当 agent 流式输出时，`StreamingContextScrubber` 实时过滤掉 `<memory-context>` 标签内容。处理标签跨 delta 边界分裂的情况（如 `<mem` 在第一个 chunk，`ory-context>` 在第二个 chunk）。

### 生活类比
**就像人的大脑**：
- 记忆文件 = 笔记本，写着重要的信息
- 预取 = 每次开会前翻一下笔记本
- 围栏标签 = 在笔记本内容前加上"这是我之前记的"，防止和别人的话混淆
- 安全扫描 = 不让别人往你笔记本里写恶意的东西
- 流式清洗 = 说话时不会把笔记本内容大声念出来

---

## 7. Plan 即工具设计理念

### 核心概念
把"计划/待办事项"（todo/plan）实现为 ReAct 循环中的一个普通工具调用，而不是独立的运行模式。LLM 需要计划时就调用 `todo` 工具，不需要时就不调用。

### 为什么这样设计
传统的 Plan-and-Execute 架构有一个"模式切换"的问题：

```
传统方式：
  进入 Plan 模式 → 生成计划 → 切换到 Execute 模式 → 执行 → 切换回 Plan → ...

本项目的做法：
  ReAct 循环中，LLM 决定调用 todo 工具 → 计划被写入 TodoStore → 继续正常执行
```

优势：
1. **零额外开销**：简单任务不需要计划，LLM 直接执行即可。只有复杂任务（3+ 步骤）才调用 todo。
2. **无缝切换**：不需要在 Plan 和 Execute 之间切换模式，一切都在同一个 ReAct 循环中。
3. **压缩恢复**：上下文压缩后，`TodoStore.format_for_injection()` 自动注入未完成的任务，防止 agent "失忆"。
4. **状态持久**：todo 列表存在内存中，压缩不会丢失（压缩时自动恢复 active items）。

### 两种写入模式
- **replace**（默认）：覆盖整个 todo 列表，适合重新规划
- **merge**：按 id 更新已有项、追加新项，适合增量更新

### 状态注入机制
上下文压缩后，`TodoStore.format_for_injection()` 只输出 `pending` 和 `in_progress` 的任务：
```
[Your active task list was preserved across context compression]
- [ ] 2. Write unit tests (pending)
- [>] 3. Deploy to staging (in_progress)
```
已完成的任务（`[x]`）不注入，避免 LLM 重复做已完成的工作。

### 生活类比
**就像便利贴**：
- 传统 Plan 模式 = 必须先写计划书才能开工（每个任务都要走流程）
- Plan 即工具 = 桌面上有便利贴，复杂任务时随手写一张，简单任务直接做
- 压缩恢复 = 即使把桌子清理干净了，便利贴上的未完成任务还贴在墙上

---

## 附录：MVP 示例代码位置

每个原理都有对应的最小化示例代码，位于 `agent-principles/` 目录下：
- `react_loop.py` — ReAct 循环的极简实现
- `context_compressor.py` — 上下文压缩的三步策略
- `skill_loader.py` — Skill 四阶段渐进式加载
- `delegate.py` — Orchestrator-Worker 委托模式
- `error_classifier.py` — 错误分类与恢复策略
- `memory.py` — 记忆系统与安全检查
- `plan_as_tool.py` — Plan 即工具
