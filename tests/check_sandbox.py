# -*- coding: utf-8 -*-
"""
验证 run_python 的「子进程沙箱」是否生效
========================================
要验证的点：**子进程的环境变量里不应该出现任何 API key**。

原理：tools.run_python 用 subprocess 起独立进程，并且只传进去一个精简的
环境变量集合（不包含 DEEPSEEK_API_KEY / SILICONFLOW_API_KEY）。
所以就算被执行的代码想把密钥读出来外传，它也拿不到。

运行：
    python tests/check_sandbox.py
"""
import sys
from pathlib import Path

# 让 import tools 能定位到项目根目录
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tools  # noqa: E402

print("=== 检查 run_python 的子进程环境变量 ===")
out = tools.run_python("import os; print(sorted(os.environ.keys()))")
print(out)

SECRETS = ("DEEPSEEK_API_KEY", "SILICONFLOW_API_KEY")
leaked = [k for k in SECRETS if k in out]

if leaked:
    print(f"\n❌ 失败：子进程环境里泄漏了 {leaked}")
    sys.exit(1)

print("\n✅ 通过：子进程拿不到 API key，沙箱生效。")

print("\n=== 顺带检查 _guard 能否拦住危险代码 ===")
cases = [
    ("装包",            "import subprocess; subprocess.run(['pip','install','x'])"),
    ("访问项目外路径",  "print(open(r'C:\\Windows\\win.ini').read())"),
    ("删文件",          "import shutil; shutil.rmtree('data')"),
]
ok = True
for name, code in cases:
    res = tools.run_python(code)
    blocked = res.startswith("拒绝执行")
    print(f"  {'✅' if blocked else '❌'} {name}：{res[:60]}")
    ok = ok and blocked

sys.exit(0 if ok else 1)
