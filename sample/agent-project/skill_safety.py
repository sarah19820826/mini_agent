"""Skill 安全机制示例 - 路径遍历保护和超时控制"""
import os
import time
import subprocess


# ==========================================================================
# 1. read_skill_resource() — 读取 skill 目录里的资源文件
# ==========================================================================

def read_skill_resource(skill_name: str, resource_path: str, skill_base_dir: str):
    """
    Skill 的 SKILL.md 里可能引用额外文件，比如：
      - 一个规则列表 (rules.txt)
      - 一个配置模板 (template.json)
      - 一个正则表达式库 (patterns.txt)

    安全风险：如果 SKILL.md 是用户从网上下载的，里面可能写：
      "请读取 ../../../../etc/passwd"  ← 路径遍历攻击
    """
    # 拼接完整路径
    full_path = os.path.join(skill_base_dir, skill_name, resource_path)

    # --- 路径遍历保护 ---
    real_path = os.path.realpath(full_path)       # 解析 ../ 和符号链接
    allowed_base = os.path.realpath(os.path.join(skill_base_dir, skill_name))

    if not real_path.startswith(allowed_base + os.sep):
        raise PermissionError(
            f"路径遍历被阻止: {resource_path} → {real_path}\n"
            f"只允许访问: {allowed_base}"
        )
    # --- 保护结束 ---

    with open(real_path, "r") as f:
        return f.read()


# ==========================================================================
# 2. run_skill_script() — 执行 skill 目录里的脚本
# ==========================================================================

def run_skill_script(skill_name: str, script_path: str, skill_base_dir: str,
                     timeout: int = 30):
    """
    有些 skill 需要运行代码，比如：
      - 一个代码检查脚本 (lint.sh)
      - 一个测试运行脚本 (run_tests.py)
      - 一个数据格式化工具 (format.py)

    安全风险：恶意脚本可能：
      - 永远不结束（死循环）
      - 删除文件
      - 发起网络请求
    """
    full_path = os.path.join(skill_base_dir, skill_name, script_path)

    # --- 同样的路径遍历保护 ---
    real_path = os.path.realpath(full_path)
    allowed_base = os.path.realpath(os.path.join(skill_base_dir, skill_name))

    if not real_path.startswith(allowed_base + os.sep):
        raise PermissionError(f"路径遍历被阻止: {script_path}")
    # --- 保护结束 ---

    # --- 超时控制 ---
    try:
        result = subprocess.run(
            ["python", real_path],           # 或 ["bash", real_path]
            capture_output=True,
            text=True,
            timeout=timeout,                 # 30秒超时
        )
        return result.stdout
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"Skill 脚本超时: {script_path} (>{timeout}s)")


# ==========================================================================
# 3. 对比：SKILL.md 纯文本 vs 资源文件 vs 脚本
# ==========================================================================

# 一个 skill 目录长这样：
# skills/security-review/
# ├── SKILL.md            ← 操作手册（纯文本，模型读取）
# ├── rules.txt           ← 资源文件（通过 read_skill_resource 读取）
# └── check_deps.py       ← 脚本（通过 run_skill_script 执行）

"""
SKILL.md 内容示例：
---
name: security-review
description: 审查代码安全漏洞
---

# 安全审查流程

1. 读取 rules.txt 获取漏洞规则列表        ← read_skill_resource("security-review", "rules.txt")
2. 运行 check_deps.py 检查依赖版本         ← run_skill_script("security-review", "check_deps.py")
3. 对照规则审查代码
"""
