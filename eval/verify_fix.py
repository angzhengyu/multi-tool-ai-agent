# -*- coding: utf-8 -*-
r"""
验证二：缺陷 1 的修复（方案 A）是否真的生效
=============================================
方案 A = **只改工具描述 + 失败时追加提示**，沙箱一个字节没放宽。
本脚本验证 4 件事（全部不经模型，确定性）：

  (1) 新描述**确实**出现在 main.TOOLS_SCHEMA 里（模型能看到）
  (2) 失败（FileNotFoundError）时**确实**追加了提示
  (3) 成功时**不会**误报提示（避免污染正常输出）
  (4) 项目外路径**仍然**被 _guard 拦下（修复没有把安全口子开了）

★ 为什么必须有 (3)：如果提示逻辑写错（比如无条件追加），
   模型每次都会看到一段无关警告，反而增加噪音。
★ 为什么必须有 (4)：这是"修复缺陷"与"放宽沙箱"的分界线。

用法（项目根目录，用装了 pandas 的解释器，例如 .venv）：python eval/verify_fix.py
"""
import sys
from pathlib import Path

EVAL = Path(__file__).resolve().parent
ROOT = EVAL.parent
sys.path.insert(0, str(ROOT))

import main as agent_app  # noqa: E402
import tools  # noqa: E402

HINT_MARK = "[提示]"          # 提示的起始标记（写死在 tools.py 里）
NEEDLES = ["DATA_DIR", "sandbox"]

results = []


def check(name, passed, detail):
    results.append(passed)
    print(f"{'[OK]' if passed else '[FAIL]'} {name}")
    print(f"   -> {detail}")


def main() -> int:
    print("=== 缺陷 1 修复（方案 A）验证 ===\n")

    # (1) 描述里是否写了 cwd / DATA_DIR
    schema = None
    for s in agent_app.TOOLS_SCHEMA:
        if s["function"]["name"] == "run_python":
            schema = s["function"]
            break
    if schema is None:
        check("(1) run_python 已在 schema 中", False,
              "未找到 run_python（是不是没设 ENABLE_RUN_PYTHON=1？）")
        return 1
    desc = schema["description"]
    miss = [n for n in NEEDLES if n not in desc]
    check("(1) 工具描述里明确写了 DATA_DIR 与 sandbox/", not miss,
          "描述齐全" if not miss else f"描述里缺：{miss}")
    print(f"   描述原文（前 160 字）：{desc[:160]}...\n")

    # (2) 失败时必须追加提示
    out_fail = tools.run_python("import pandas as pd\ndf = pd.read_csv('data/sales.csv')")
    has_fnf = "FileNotFoundError" in out_fail
    has_hint = HINT_MARK in out_fail and "DATA_DIR" in out_fail
    check("(2) 相对路径失败 -> FileNotFoundError", has_fnf,
          "确实报错了" if has_fnf else f"没报 FileNotFoundError：{out_fail[:120]}")
    check("(2) 失败时确实追加了「相对路径」提示", has_hint,
          "提示已出现" if has_hint else f"提示缺失：{out_fail[-160:]}")
    print(f"   提示原文：{out_fail[-150:].strip()}\n")

    # (3) 成功时不能误报
    out_ok = tools.run_python("df = pd.read_csv(DATA_DIR + '/sales.csv')\nprint(df.shape[0], '行')")
    ok_row = out_ok.strip().startswith("240")
    no_false_hint = HINT_MARK not in out_ok
    check("(3) 用 DATA_DIR 读文件 -> 成功且读到 240 行", ok_row,
          out_ok.strip().splitlines()[0] if out_ok.strip() else "(空)")
    check("(3) 成功时不会误报提示（无噪音）", no_false_hint,
          "无提示" if no_false_hint else "★ 误报了提示，需要修")

    # (4) 安全边界没被放宽
    out_block = tools.run_python("print(open(r'C:\\Windows\\win.ini').read()[:50])")
    check("(4) 项目外路径仍被沙箱拦截（修复没开安全口子）",
          out_block.startswith("拒绝执行"), out_block[:100])

    n_ok = sum(1 for r in results if r)
    print(f"\n=== {n_ok}/{len(results)} 项通过 ===")
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())