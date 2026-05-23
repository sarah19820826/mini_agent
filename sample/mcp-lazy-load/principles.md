# Skill 作为 MCP 工具的懒加载器

> 核心：**MCP 工具默认不在上下文，Skill 触发时才动态加载它需要的那一小部分。**
>
> Skill = 工具配置文件 + 操作手册。调用即加载，用完即"卸载"。

---

## 一、问题：MCP 工具太多，占用大量 token

一个 MCP 服务器可能暴露 50~200 个工具。每个工具的描述、参数 schema 大约占用 150~300 tokens。

### 无懒加载（全部常驻上下文）

```
系统提示词:
  ...
  [MCP Tools - github]        ← 200 个工具定义，约 40,000 tokens
    get_pr: 获取PR详情...
    create_pr: 创建PR...
    merge_pr: 合并PR...
    delete_repo: 删除仓库...    ← 99% 的对话用不到，但每轮都在消耗 token
    list_secrets: 列出密钥...
    ... (省略 195 个)
  [MCP Tools - jira]          ← 80 个工具定义，约 16,000 tokens
  [MCP Tools - slack]          ← 30 个工具定义，约 6,000 tokens
  ...
总计: 300+ 工具, ~60,000 tokens 常驻
```

一**次都没用过的工具**，每轮对话都在白白烧 token。

### 有懒加载（Skill 按需带入）

```
系统提示词:
  ...
  [Available Skills]          ← 仅名称+描述，~100 tokens/skill
    pr-review: Review PR, loads 5 tools
    ci-debug: Debug CI, loads 3 tools
    issue-triage: Triage issues, loads 4 tools
    release-cut: Cut release, loads 3 tools
    ...

当用户说 "review PR #42":
  → Skill pr-review 被触发
  → 加载 5 个 MCP 工具定义到上下文 (~1,000 tokens)
  → 其他 195 个工具定义不在上下文 ← 省了 ~39,000 tokens

当对话切回普通模式:
  → 5 个工具定义被移除
  → 上下文恢复到轻量状态
```

---

## 二、机制：Skill 四阶段 + MCP 工具绑定

### 本质：把工具定义"藏"在 Skill 内部

```
Skill 定义:
  SKILL.md:
    ---
    name: pr-review
    description: Review PR...        ← 阶段1 Advertise: 始终在上下文 (轻量)
    allowed-tools:                   ← 阶段2 Load: Skill触发时生效
      - mcp__github__get_pr          ← 工具定义仅此时进入上下文
      - mcp__github__get_pr_diff
      - mcp__github__get_pr_comments
      - mcp__github__get_workflow
      - mcp__github__get_file
    ---
    # PR Review 操作手册...           ← 阶段3 Read: 详细指令
```

### 生命周期

```
用户: "review PR #42"
        │
        ▼
┌─ 匹配 Skill ─────────────────────────────────────┐
│ 从 20 个 Skill 的 advertise 中匹配 "review PR"    │
│ pr-review 命中                                     │
└────────────────────────────────────────────────────┘
        │
        ▼
┌─ Load Skill ─────────────────────────────────────┐
│ 1. 加载 SKILL.md body (操作手册)                   │
│ 2. 解析 allowed-tools                             │
│ 3. 从 MCP 服务器注册表中提取 5 个工具定义           │
│ 4. 注入到当前上下文                                │
│                                                   │
│ 此时上下文中的 MCP 工具: 5 个 (不是 200 个)        │
└────────────────────────────────────────────────────┘
        │
        ▼
┌─ 执行 ───────────────────────────────────────────┐
│ LLM 使用 5 个工具完成 PR review                    │
│ get_pr → get_pr_diff → get_pr_comments → ...      │
└────────────────────────────────────────────────────┘
        │
        ▼
┌─ 退出 Skill ─────────────────────────────────────┐
│ 1. 移除 5 个 MCP 工具定义                          │
│ 2. 上下文恢复到 Skill 调用前状态                    │
│                                                   │
│ 此时上下文中的 MCP 工具: 0 个 (轻量)               │
└────────────────────────────────────────────────────┘
```

### 关键点

- **工具定义的生命周期 = Skill 的生命周期**
- Skill 加载 → 工具定义进入上下文
- Skill 退出 → 工具定义移出上下文
- 不是"权限限制"，是**存在性控制** — 工具定义根本不在 LLM 的视野内

---

## 三、一个请求对应一个 Skill 的工具集

### 场景：GitHub MCP 服务器有 200 个工具

| 用户请求 | 匹配 Skill | 加载工具数 | 屏蔽工具数 |
|----------|-----------|-----------|-----------|
| "review PR #42" | `pr-review` | 5 | 195 |
| "CI 为什么挂了" | `ci-debug` | 3 | 197 |
| "整理这周的 issues" | `issue-triage` | 4 | 196 |
| "发布 v2.1" | `release-cut` | 3 | 197 |
| "帮我改个文件名" | 无 Skill (直接用 Bash) | 0 | 200 |

每次对话只加载**当前任务需要的**那一小撮工具。

---

## 四、Token 节省计算

假设 200 个 MCP 工具，每个工具定义约 200 tokens：

| 模式 | 常驻 token | 按需峰值 | 10 轮对话总消耗 |
|------|-----------|---------|---------------|
| 全量加载 | 40,000/轮 | 40,000 | 10 × 40k = **400,000** |
| Skill 懒加载 | 0/轮 | ~1,000 (Skill 触发时) | 9 × 0 + 1 × 1k = **1,000** |

实际中可能有多轮在 Skill 内，但整体节省比例巨大。

---

## 五、与 `allowed-tools` 白名单的区别

| 维度 | 白名单 (`allowed-tools`) | 懒加载 (本文) |
|------|-------------------------|-------------|
| 解决的问题 | **安全**: Skill 不能调用未授权工具 | **效率**: 工具定义不占用 token |
| 工具定义 | 仍在上下文中（被标记为不可用） | **不在上下文中**（根本不可见） |
| 核心机制 | 调用时拦截 | 加载时过滤 |
| 效果 | 调不了 | **看不见也调不了** |
| 类比 | 门禁卡（能看见房间，进不去） | 房间压根不存在于地图上 |

两者**配合使用**效果最好：懒加载减少 token 消耗，白名单提供纵深防御。

---

## 六、实际在 Claude Code 中的表现

当前 Claude Code 的实现中，MCP 工具是在系统提示词中全量注册的。Skill 的 `allowed-tools` 做的是调用层拦截。

但**概念上**，Skill 的渐进式加载（Advertise → Load → Read → Run）本身就是这个模式：

- Advertise 阶段：只有 Skill 名称和一行描述（~100 tokens）
- Load 阶段：完整指令 + 工具声明进入上下文
- 退出 Skill：指令和工具的上下文影响解除

这为未来实现真正的 MCP 工具懒加载提供了基础架构 — Skill 框架已经支持了按需加载的信息分层。

---

## 运行示例

```bash
python mcp_lazy_load.py
```
