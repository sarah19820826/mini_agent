"""分析 import 来源 — 标准库、第三方、本地模块。"""
import sys, ast


# 常用标准库前缀（够用就好）
STDLIB_PREFIXES = {
    "os", "sys", "json", "re", "pathlib", "typing", "collections", "itertools",
    "functools", "subprocess", "importlib", "abc", "dataclasses", "enum",
    "logging", "unittest", "copy", "io", "math", "time", "datetime",
    "hashlib", "hmac", "secrets", "socket", "http", "urllib", "email",
    "csv", "xml", "configparser", "argparse", "tempfile", "shutil",
    "glob", "fnmatch", "pickle", "struct", "threading", "multiprocessing",
    "asyncio", "contextlib", "textwrap", "string", "uuid", "base64",
}


def classify_import(name: str) -> str:
    top = name.split(".")[0]
    if top in STDLIB_PREFIXES:
        return "标准库"
    # 本地模块判断：没有点号且不在标准库中
    if "." not in name:
        return "本地/第三方"
    return "第三方"


def analyze(filepath: str) -> str:
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    tree = ast.parse(content, filename=filepath)
    stdlib = []
    third_party = []
    local = []
    star_imports = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                cat = classify_import(name)
                if cat == "标准库":
                    stdlib.append(name)
                elif cat == "本地/第三方":
                    local.append(name)
                else:
                    third_party.append(name)

        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            # from module import *
            for alias in node.names:
                if alias.name == "*":
                    star_imports.append(f"  from {node.module} import *  (第{node.lineno}行)")
            cat = classify_import(node.module)
            if cat == "标准库":
                stdlib.append(node.module)
            elif cat == "本地/第三方":
                local.append(node.module)
            else:
                third_party.append(node.module)

    lines = [f"=== {filepath} 导入分析 ==="]
    lines.append(f"标准库: {', '.join(sorted(set(stdlib))) or '(无)'}")
    lines.append(f"第三方: {', '.join(sorted(set(third_party))) or '(无)'}")
    lines.append(f"本地模块: {', '.join(sorted(set(local))) or '(无)'}")

    if star_imports:
        lines.append("警告 — import * 发现:")
        lines.extend(star_imports)

    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python analyze_imports.py <文件路径>", file=sys.stderr)
        sys.exit(1)
    print(analyze(sys.argv[1]))
