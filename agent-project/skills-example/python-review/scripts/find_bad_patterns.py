"""查找危险代码模式 — eval/exec/os.system/裸except/sql拼接。"""
import sys, ast


def scan(filepath: str) -> str:
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    tree = ast.parse(content, filename=filepath)
    findings = []

    for node in ast.walk(tree):
        # eval() / exec()
        if isinstance(node, ast.Call):
            func = node.func
            name = ""
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr

            if name in ("eval", "exec"):
                findings.append(f"  第{node.lineno}行: 使用了 {name}()，存在代码注入风险")
            elif name == "system" and isinstance(func, ast.Attribute):
                if isinstance(func.value, ast.Name) and func.value.id == "os":
                    findings.append(
                        f"  第{node.lineno}行: 使用了 os.system()，建议改用 subprocess.run()"
                    )

        # 裸 except:
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            findings.append(
                f"  第{node.lineno}行: 裸 except:，会捕获 KeyboardInterrupt 等，建议写具体异常类型"
            )

    if findings:
        return f"=== {filepath} 危险模式扫描 ===\n共发现 {len(findings)} 个问题:\n" + "\n".join(findings)
    return f"=== {filepath} 危险模式扫描 ===\n未发现已知危险模式。"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python find_bad_patterns.py <文件路径>", file=sys.stderr)
        sys.exit(1)
    print(scan(sys.argv[1]))
