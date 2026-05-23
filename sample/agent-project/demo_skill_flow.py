"""Skill 完整流程演示 — 按用户问题类型按需加载"""
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "skill"))
from skills_loader import SkillsLoader

SKILLS_DIR = os.path.join(os.path.dirname(__file__), "skills-example")
TARGET_FILE = os.path.join(os.path.dirname(__file__), "main.py")


def demo():
    loader = SkillsLoader([SKILLS_DIR])

    # ===== Phase 1: Advertise — 启动扫描 =====
    print("=" * 50)
    print("Phase 1: Advertise")
    print("=" * 50)
    print(loader.get_advertise_prompt())
    print()

    # ===== Phase 2: Load — 加载操作手册 =====
    print("=" * 50)
    print("Phase 2: Load（加载 SKILL.md 操作手册）")
    print("=" * 50)
    print(loader.load_skill("python-review"))
    print()

    # ===== 模拟场景：用户说"帮我做安全审查" =====
    print("=" * 50)
    print("场景：用户说'帮我做安全审查'")
    print("LLM 读到手册，知道需要：")
    print("  1. 运行 count_stats.py（必须）")
    print("  2. 读取 security-rules.md（按需）")
    print("  3. 运行 find_bad_patterns.py（按需）")
    print()

    # Phase 3: Read — 只加载安全规则
    print("─" * 50)
    print("Phase 3: Read（只加载安全规则，不加载命名和质量）")
    print("─" * 50)
    print(loader.read_skill_resource("python-review", "references/security-rules.md"))
    print()

    # Phase 4: Run — 运行两个脚本
    print("─" * 50)
    print("Phase 4: Run（运行统计脚本 + 危险模式扫描）")
    print("─" * 50)
    print(loader.run_skill_script("python-review", "scripts/count_stats.py", [TARGET_FILE]))
    print()
    print(loader.run_skill_script("python-review", "scripts/find_bad_patterns.py", [TARGET_FILE]))
    print()

    # ===== 模拟另一个场景：用户说"检查 import 有没有问题" =====
    print("=" * 50)
    print("另一场景：用户说'检查 import 有没有问题'")
    print("LLM 只加载 quality-rules.md + 运行 analyze_imports.py")
    print("─" * 50)
    print(loader.read_skill_resource("python-review", "references/quality-rules.md"))
    print()
    print(loader.run_skill_script("python-review", "scripts/analyze_imports.py", [TARGET_FILE]))
    print()

    # ===== 安全演示 =====
    print("=" * 50)
    print("安全保护：路径遍历攻击")
    print("=" * 50)
    result = loader.read_skill_resource("python-review", "../../../etc/passwd")
    print("结果:", result)


if __name__ == "__main__":
    demo()
