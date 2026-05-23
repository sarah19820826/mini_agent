"""记忆系统完整流程示例 - 模拟一轮完整对话"""

class MemorySystem:
    """记忆系统：两个文件，每个文件每行一条记录"""

    def __init__(self):
        # 用列表模拟文件，实际项目用磁盘文件
        self.user_store = []    # 用户信息
        self.memory_store = []  # 项目信息

    # ---------- 存 ----------

    def add(self, target, content):
        if target == "user":
            self.user_store.append(content)
        else:
            self.memory_store.append(content)

    def replace(self, target, keyword, new_content):
        store = self.user_store if target == "user" else self.memory_store
        for i, line in enumerate(store):
            if keyword in line:
                store[i] = new_content
                return

    def remove(self, target, keyword):
        store = self.user_store if target == "user" else self.memory_store
        while any(keyword in line for line in store):
            store = [l for l in store if keyword not in l]
        if target == "user":
            self.user_store = store
        else:
            self.memory_store = store

    # ---------- 取 ----------

    def prefetch(self):
        """每轮对话开始时调用，构建注入提示词的上下文"""
        parts = []
        if self.user_store:
            parts.append("## 用户信息\n" + "\n".join(self.user_store))
        if self.memory_store:
            parts.append("## 项目记忆\n" + "\n".join(self.memory_store))
        if not parts:
            return "(无记忆)"
        return "\n\n".join(parts)

    def print_state(self):
        """打印当前状态（仅用于演示）"""
        print(f"  [user]  {self.user_store or '(空)'}")
        print(f"  [mem]   {self.memory_store or '(空)'}")


def print_separator(title):
    print(f"\n{'='*60}")
    print(f" {title}")
    print(f"{'='*60}")


def main():
    memory = MemorySystem()

    # ==================================================================
    # 第1轮对话：初次见面，发现用户偏好
    # ==================================================================
    print_separator("第1轮：初次见面")
    print()
    print(">>> 用户: 帮我看看这个Python项目的代码质量")
    print("    用户: 我喜欢简洁的代码，不要多余的抽象")
    print()
    print("[Agent思考]")
    print("  → 用户分享了编码偏好，值得记忆（未来每次写代码都要参考）")
    print("  → 触发: memory.add(target='user', content='偏好简洁代码，不要多余抽象')")
    print()

    # 存
    memory.add("user", "偏好简洁代码，不要多余抽象")
    print("[记忆状态]")
    memory.print_state()

    print()
    print("[Agent回复]")
    print("  好的，我会保持代码简洁。让我检查一下...")
    print()
    print("--- Agent 实际调用 ---")
    print('memory.add(target="user", content="偏好简洁代码，不要多余抽象")')

    # ==================================================================
    # 第2轮对话：发现项目技术栈
    # ==================================================================
    print_separator("第2轮：发现技术栈")
    print()
    print(">>> 用户: 我们用FastAPI做的接口，在app/api/下面")
    print()
    print("[Agent思考]")
    print("  → 这是项目事实，后续工作会反复用到")
    print("  → 触发: memory.add(target='memory', content='API接口用FastAPI，位于app/api/')")
    print()

    memory.add("memory", "API接口用FastAPI，位于app/api/")
    print("[记忆状态]")
    memory.print_state()

    print()
    print("--- 注入到提示词的内容（prefetch） ---")
    print(memory.prefetch())

    # ==================================================================
    # 第3轮对话：用户纠正信息
    # ==================================================================
    print_separator("第3轮：纠正信息")
    print()
    print(">>> 用户: 不对，我们不是FastAPI，是Flask，在src/routes/下面")
    print()
    print("[Agent思考]")
    print("  → 用户在纠正记忆中的错误信息")
    print("  → 触发: memory.replace(target='memory', keyword='FastAPI', ...)")
    print()

    memory.replace("memory", "FastAPI", "API接口用Flask，位于src/routes/")
    print("[记忆状态]")
    memory.print_state()

    print()
    print("--- 注入到提示词的内容（prefetch） ---")
    print(memory.prefetch())

    # ==================================================================
    # 第4轮对话：信息过时，删除
    # ==================================================================
    print_separator("第4轮：信息过时，删除")
    print()
    print(">>> 用户: 我们迁移到Django了，之前的Flask信息不用记了")
    print("    用户: 新项目结构在djangoapp/下")
    print()
    print("[Agent思考]")
    print("  → Flask信息已过期，删除")
    print("  → Django是新事实，添加")
    print("  → 触发: memory.remove + memory.add")
    print()

    memory.remove("memory", "Flask")
    memory.add("memory", "项目用Django，位于djangoapp/")
    print("[记忆状态]")
    memory.print_state()

    print()
    print("--- 注入到提示词的内容（prefetch） ---")
    print(memory.prefetch())

    # ==================================================================
    # 总结：完整生命周期
    # ==================================================================
    print_separator("总结：一条记忆的生命周期")
    print("""
    对话第1轮                          对话第3轮                          对话第4轮
    ┌──────────┐                  ┌──────────┐                  ┌──────────┐
    │  add     │   发现新信息     │  replace │   纠正/更新      │  remove  │
    │  (写入)  │ ──────────────→ │  (替换)  │ ──────────────→ │  (删除)  │
    └──────────┘                  └──────────┘                  └──────────┘

    每轮对话开始:  prefetch() → 读取全部 → 注入提示词
    每轮对话结束:  判断是否存 → 安全扫描 → 写入存储

    文件内容演变:
      第2轮: ["API接口用FastAPI，位于app/api/"]
      第3轮: ["API接口用Flask，位于src/routes/"]       ← 替换
      第4轮: ["项目用Django，位于djangoapp/"]           ← 删除旧 + 添加新
    """)


if __name__ == "__main__":
    main()
