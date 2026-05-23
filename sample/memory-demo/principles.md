# 记忆系统原理

> 核心：**记忆 = 跨对话的持久化上下文**。本质是一个文本文件，每行一条记录。

## 流程总览

```
用户对话 → Agent判断是否值得记忆 → 安全扫描 → 写入文件
    ↑
每轮开始 → 读取文件 → 构建上下文块 → 注入系统提示词
```

---

## 一、存什么（What）

### 两个存储目标

| 目标 | 内容 | 示例 |
|------|------|------|
| `user` | 用户是谁 | "用户是高级Python工程师" |
| `memory` | 环境/项目事实 | "项目用Django 4.2框架" |

### 不存什么

- 可从代码重新推导的信息（文件路径、函数名）
- Git历史中的信息（谁改了啥）
- 临时上下文（当前对话的中间状态）

### 安全扫描（写入前）

```python
# 三条规则，任何匹配直接拒绝
"ignore.*instructions"    →  提示词注入攻击
"api_key|secret|password" →  凭证泄露
"<memory-context>"        →  围栏标签注入
```

---

## 二、何时存（When）

### 立即保存

| 触发条件 | 示例 |
|----------|------|
| 用户纠正你 | "不，我们用的是PostgreSQL，不是MySQL" |
| 用户明确要求 | "记住这个配置" |
| 用户分享偏好 | "我喜欢用type hint" |
| 发现环境事实 | 发现项目用Poetry管理依赖 |
| 了解特殊约定 | "我们PR描述要写测试步骤" |

### 不存

- 显而易见的信息
- 搜索引擎可轻易获取的
- 只对本次对话有意义的

---

## 三、如何取（Retrieve）

### Prefetch 机制

```
每轮对话开始
  → MemoryManager.prefetch_all()
  → 读取 user.md + memory.md
  → 构建 <memory-context> 围栏块
  → 注入到系统提示词
```

### 上下文注入格式

```xml
<memory-context>
## Memory
项目运行在Windows 11上
数据库连接用localhost:5432

## User Profile
用户偏好用Python，不喜欢Go
</memory-context>
```

围栏的作用：让模型知道这是**参考数据**，不是用户的新输入。

---

## 四、如何更新（Update）

### 三种操作

| 操作 | 参数 | 匹配方式 |
|------|------|----------|
| `add` | content | 追加新行 |
| `replace` | old_text + content | 模糊匹配（`in`） |
| `remove` | old_text | 模糊匹配（`in`） |

### 示例

```python
memory.add("用户喜欢用pytest")
# 文件: "用户喜欢用pytest\n"

memory.replace("pytest", "unittest")
# 文件: "用户喜欢用unittest\n"

memory.remove("unittest")
# 文件: (空)
```

### 生命周期

```
add → (replace*) → remove → (gone)
```

---

## 数据结构

```
memory.txt (或 user.md)
├── 第1行: 用户偏好用Python
├── 第2行: 项目运行在Windows 11
└── 第3行: 数据库用PostgreSQL
```

**最简单的记忆系统就是一个文本文件，每行一条。**

---

## 与 Claude Code 记忆系统的对应

| 本项目 | Claude Code 实际系统 |
|--------|---------------------|
| `memory.md` | `~/.claude/projects/.../memory/*.md` |
| `user.md` | 同上，不同文件 |
| 全量读取 | 同，但会截断200行之后 |
| 安全扫描 | 同原理，规则更完善 |
| `prefetch_all()` | 自动加载到系统提示词 |

---

## 运行示例

```bash
python memory_simple.py
```
