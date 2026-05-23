"""MCP Skill 演示 — 大量工具按场景选择使用"""
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "skill"))
from skills_loader import SkillsLoader

SKILLS_DIR = os.path.join(os.path.dirname(__file__), "skills-example")


def demo():
    loader = SkillsLoader([SKILLS_DIR])

    # ===== Phase 1: Advertise =====
    print("=" * 50)
    print("Phase 1: Advertise（启动扫描）")
    print("=" * 50)
    print(loader.get_advertise_prompt())
    print()

    # ===== Phase 2: Load =====
    print("=" * 50)
    print("Phase 2: Load（加载 data-explorer 操作手册）")
    print("=" * 50)
    instructions = loader.load_skill("data-explorer")
    print(instructions)
    print()

    # ===== 查看 frontmatter 声明的工具 =====
    print("=" * 50)
    print("SKILL.md frontmatter 声明的 MCP 工具")
    print("=" * 50)
    skill = loader.skills["data-explorer"]
    print("tools:", skill.metadata.get("tools", []))
    print("mcp_servers:", skill.mcp_servers)
    print()

    # ===== 模拟不同场景 =====
    print("=" * 50)
    print("场景对比：同样 9 个工具，不同用户只用不同的子集")
    print("=" * 50)
    print()

    scenarios = [
        {
            "title": "场景A：用户说'查上个月订单总额'",
            "uses": ["query_aggregate"],
            "skip": ["query_user_profile", "export_csv", "read_excel",
                      "parse_json_file", "fetch_api", "call_graphql",
                      "validate_schema", "generate_chart"],
        },
        {
            "title": "场景B：用户说'把这个JSON文件数据画成图表'",
            "uses": ["parse_json_file", "generate_chart"],
            "skip": ["query_database", "query_aggregate", "query_user_profile",
                      "export_csv", "read_excel", "fetch_api", "call_graphql",
                      "validate_schema"],
        },
        {
            "title": "场景C：用户说'拉API数据导出CSV给我'",
            "uses": ["fetch_api", "export_csv"],
            "skip": ["query_database", "query_aggregate", "query_user_profile",
                      "read_excel", "parse_json_file", "call_graphql",
                      "validate_schema", "generate_chart"],
        },
    ]

    all_tools = skill.metadata.get("tools", [])
    for scenario in scenarios:
        print(f"--- {scenario['title']} ---")
        print(f"  使用: {scenario['uses']}  ({len(scenario['uses'])}/{len(all_tools)} 个工具)")
        print(f"  不加载: {scenario['skip']}  ({len(scenario['skip'])} 个)")
        print()

    # ===== Phase 3: Read 资源文件 =====
    print("=" * 50)
    print("Phase 3: Read（读取数据来源说明）")
    print("=" * 50)
    content = loader.read_skill_resource("data-explorer", "references/data-sources.md")
    print(content)
    print()

    print("=" * 50)
    print("Phase 3: Read（读取输出格式规范）")
    print("=" * 50)
    content2 = loader.read_skill_resource("data-explorer", "references/output-format.md")
    print(content2)
    print()

    # ===== 安全演示 =====
    print("=" * 50)
    print("安全保护：路径遍历")
    print("=" * 50)
    result = loader.read_skill_resource("data-explorer", "../../../etc/passwd")
    print("结果:", result)


if __name__ == "__main__":
    demo()
