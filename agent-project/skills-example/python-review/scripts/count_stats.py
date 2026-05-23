"""基础统计 — 行数、函数数、类数、导入数。"""
import sys, ast


def analyze(filepath: str) -> str:
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    lines = content.split("\n")
    total = len(lines)
    code = sum(1 for l in lines if l.strip() and not l.strip().startswith("#"))
    blank = sum(1 for l in lines if not l.strip())

    tree = ast.parse(content, filename=filepath)
    functions = sum(1 for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
    classes = sum(1 for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
    imports = sum(1 for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)))

    return (
        f"=== {filepath} 基础统计 ===\n"
        f"总行数: {total}  (代码: {code}  空行: {blank}  注释: {total - code - blank})\n"
        f"函数: {functions}  类: {classes}  导入: {imports}"
    )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python count_stats.py <文件路径>", file=sys.stderr)
        sys.exit(1)
    print(analyze(sys.argv[1]))
