"""
MCP工具懒加载 — 从 SKILL.md 动态读取工具列表

概念:
  MCP Server 有 100 个工具，默认全都不在上下文
  代码扫描 skills/*/SKILL.md，从 YAML frontmatter 的 allowed-tools 字段
  解析每个 Skill 需要的工具子集
  Skill 触发时才动态加载，退出即卸载

运行: python mcp_lazy_load.py
"""

import os
import re
import random

# ============================================================
# 1. MCP 服务器 — 注册了 100 个工具，但默认不加载
# ============================================================
def _make_tools(prefix, names):
    """用真实工具名替代编号占位符"""
    tools = {}
    for name in names:
        full = f"mcp__{prefix}__{name}"
        tools[full] = random.randint(120, 300)
    return tools

GITHUB_TOOLS = [
    "get_pr", "get_pr_diff", "get_pr_comments", "get_workflow",
    "get_file", "get_workflow_log", "rerun_workflow",
    "list_issues", "get_issue", "add_labels", "create_comment",
    "create_pr", "merge_pr", "close_pr", "approve_pr",
    "request_review", "delete_branch", "create_branch",
    "list_prs", "search_code", "get_commit", "compare_commits",
    "create_release", "get_release", "list_releases",
    "add_collaborator", "remove_collaborator",
    "create_webhook", "list_webhooks", "delete_webhook",
    "list_secrets", "create_secret", "delete_secret",
    "get_milestone", "list_milestones", "create_milestone",
    "update_file", "create_repo", "delete_repo",
    "transfer_repo", "update_settings",
    "get_deployment", "create_deployment", "list_deployments",
    "trigger_ci", "cancel_run", "get_runner", "list_runners",
    "get_issue_comment", "update_issue_comment", "delete_issue_comment",
    "add_reaction", "get_team", "list_teams", "create_team",
    "get_user", "list_users", "get_org", "list_orgs",
    "create_gist", "get_gist", "list_gists",
]

JIRA_TOOLS = [
    "get_issue", "create_issue", "update_issue", "delete_issue",
    "list_issues", "search_issues", "assign_issue", "comment_issue",
    "get_sprint", "list_sprints", "create_sprint",
    "get_board", "list_boards",
    "get_project", "list_projects",
    "get_user", "list_users",
    "get_workflow", "list_workflows",
    "add_attachment", "get_attachment",
    "create_version", "list_versions",
    "get_priority", "list_priorities",
]

SLACK_TOOLS = [
    "send_message", "update_message", "delete_message",
    "list_channels", "get_channel", "create_channel",
    "get_user", "list_users",
    "upload_file", "get_file",
    "add_reaction", "list_reactions",
    "get_thread", "list_threads",
    "set_status", "get_status",
]

MCP_REGISTRY = {
    **_make_tools("github", GITHUB_TOOLS),
    **_make_tools("jira", JIRA_TOOLS),
    **_make_tools("slack", SLACK_TOOLS),
}

# ============================================================
# 2. 从 SKILL.md 文件动态解析 Skill 定义
# ============================================================
def parse_skill_md(filepath):
    """解析 SKILL.md 的 YAML frontmatter，提取 name, description, allowed-tools"""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # 提取 --- 之间的 YAML frontmatter
    m = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not m:
        return None

    yaml_text = m.group(1)

    # 简易 YAML 解析（不依赖 pyyaml）
    def get_field(key):
        pat = rf"^{key}:\s*(.+)$"
        match = re.search(pat, yaml_text, re.MULTILINE)
        return match.group(1).strip().strip('"').strip("'") if match else None

    name = get_field("name")
    description = get_field("description")

    # 解析 allowed-tools 列表（支持 YAML 数组语法）
    tools = []
    in_list = False
    for line in yaml_text.split("\n"):
        stripped = line.strip()
        if stripped == "allowed-tools:":
            in_list = True
            continue
        if in_list:
            if stripped.startswith("- "):
                tool = stripped[2:].strip().strip('"').strip("'")
                tools.append(tool)
            elif stripped and not stripped.startswith("#") and ":" in stripped and not stripped.startswith("-"):
                # 下一个顶级字段，退出列表
                in_list = False

    return {"name": name, "description": description, "tools": tools}


def load_skills_from_dir(skills_dir):
    """扫描 skills/*/SKILL.md，构建 Skill 注册表"""
    skills = {}
    if not os.path.isdir(skills_dir):
        return skills

    for entry in os.listdir(skills_dir):
        skill_md = os.path.join(skills_dir, entry, "SKILL.md")
        if os.path.isfile(skill_md):
            parsed = parse_skill_md(skill_md)
            if parsed and parsed["name"]:
                skills[parsed["name"]] = parsed
    return skills


# ============================================================
# 3. 上下文管理器 — 控制工具定义的加载和卸载
# ============================================================
class ContextManager:
    def __init__(self, registry):
        self.registry = registry
        self.loaded_tools = {}
        self.active_skill = None
        self.total_tokens_saved = 0
        self.conversation_rounds = 0

    def load_skill(self, skill_name, skills):
        """加载Skill → 将其 allowed-tools 中的 MCP 工具注入上下文"""
        if skill_name not in skills:
            return False

        if self.active_skill:
            self.unload_skill(skills)

        skill = skills[skill_name]
        self.active_skill = skill_name

        for tool_name in skill["tools"]:
            # 只加载 MCP 工具（跳过 Read, Write, Bash 等内置工具）
            if tool_name in self.registry:
                self.loaded_tools[tool_name] = self.registry[tool_name]

        return True

    def unload_skill(self, skills):
        """卸载Skill → 移除其带入的 MCP 工具定义"""
        if not self.active_skill:
            return

        skill = skills[self.active_skill]
        for tool_name in skill["tools"]:
            self.loaded_tools.pop(tool_name, None)

        self.active_skill = None

    def tick(self):
        """每轮对话记录token消耗"""
        self.conversation_rounds += 1
        loaded_tokens = sum(self.loaded_tools.values())
        all_tokens = sum(self.registry.values())
        saved = all_tokens - loaded_tokens
        self.total_tokens_saved += saved
        return loaded_tokens, saved

    def stats(self):
        return {
            "rounds": self.conversation_rounds,
            "total_tools": len(self.registry),
            "loaded_tools": len(self.loaded_tools),
            "loaded_tokens": sum(self.loaded_tools.values()),
            "all_tokens": sum(self.registry.values()),
            "total_saved": self.total_tokens_saved,
            "active_skill": self.active_skill,
        }


# ============================================================
# 4. 模拟一场对话
# ============================================================
def simulate():
    # 从文件系统读取 Skill 定义
    skills_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills")
    skills = load_skills_from_dir(skills_dir)

    if not skills:
        print("ERROR: No SKILL.md files found in", skills_dir)
        print("Expected: skills/pr-review/SKILL.md, skills/ci-debug/SKILL.md, ...")
        return

    print("=" * 65)
    print("MCP Tool Lazy-Load via Skills")
    print("=" * 65)
    print(f"\nSkills loaded from disk ({len(skills)} found):")
    for name, skill in skills.items():
        mcp_count = sum(1 for t in skill["tools"] if t.startswith("mcp__"))
        print(f"  {name}: {mcp_count} MCP tools  <- skills/{name}/SKILL.md")
    print(f"\nMCP registry: {len(MCP_REGISTRY)} tools total")
    print(f"Token cost if all loaded: {sum(MCP_REGISTRY.values()):,}")
    print()

    ctx = ContextManager(MCP_REGISTRY)

    conversation = [
        ("user", None,  "Hi, what can you do?"),
        ("ctx",  None,  None),
        ("user", "pr-review", "Review PR #42 for me"),
        ("ctx",  "pr-review", None),
        ("llm",  "pr-review", "get_pr(42) -> get_pr_diff(42) -> get_pr_comments(42)"),
        ("llm",  "pr-review", "get_workflow(main) -> get_file('src/app.py')"),
        ("llm",  "pr-review", "PR #42 looks good, 2 minor comments"),
        ("ctx",  None,  None),
        ("user", None,  "Thanks! Now, why is CI failing on main?"),
        ("ctx",  "ci-debug", None),
        ("llm",  "ci-debug", "get_workflow(main) -> get_workflow_log(run_123)"),
        ("llm",  "ci-debug", "CI failed due to flaky test in test_db.py"),
        ("ctx",  None,  None),
        ("user", None,  "OK, also triage this week's issues"),
        ("ctx",  "issue-triage", None),
        ("llm",  "issue-triage", "list_issues(label=bug) -> get_issue(101)"),
        ("llm",  "issue-triage", "Found 5 stale bugs, labeled them"),
        ("ctx",  None,  None),
    ]

    for role, skill, msg in conversation:
        if role == "ctx":
            if skill:
                ctx.load_skill(skill, skills)
                s = ctx.stats()
                print(f"[Skill: {skill}]  "
                      f"loaded {s['loaded_tools']}/{s['total_tools']} MCP tools  "
                      f"({s['loaded_tokens']:,}/{s['all_tokens']:,} tokens in context)")
            else:
                ctx.unload_skill(skills)
                s = ctx.stats()
                print(f"[No Skill]       "
                      f"loaded {s['loaded_tools']}/{s['total_tools']} MCP tools  "
                      f"({s['loaded_tokens']:,}/{s['all_tokens']:,} tokens in context)")
            continue

        if role == "user":
            print(f"\n>>> User: {msg}")
        elif role == "llm":
            print(f"    LLM: {msg}")

        if role != "ctx":
            ctx.tick()

    # 最终统计
    print(f"\n{'=' * 65}")
    print("Session Summary")
    print(f"{'=' * 65}")
    s = ctx.stats()

    without_lazy_total = s["rounds"] * s["all_tokens"]
    with_lazy_total = without_lazy_total - s["total_saved"]

    print(f"""
  Conversation rounds:          {s['rounds']}
  Total MCP tools registered:    {s['total_tools']}

  Without lazy-load:
    Every round: {s['all_tokens']:,} tokens x {s['rounds']} rounds
    Total:       {without_lazy_total:,} tokens

  With lazy-load (Skills):
    Total saved: {s['total_saved']:,} tokens
    Effective:   {with_lazy_total:,} tokens (saved {(s['total_saved']/without_lazy_total*100):.0f}%)
""")

    print("  Tool source (read from SKILL.md):")
    for name, skill in skills.items():
        mcp_tools = [t for t in skill["tools"] if t.startswith("mcp__")]
        tool_tokens = sum(MCP_REGISTRY[t] for t in mcp_tools if t in MCP_REGISTRY)
        print(f"    skills/{name}/SKILL.md -> {len(mcp_tools)} MCP tools, ~{tool_tokens:,} tokens")


if __name__ == "__main__":
    simulate()
