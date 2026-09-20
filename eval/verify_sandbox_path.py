# -*- coding: utf-8 -*-
r"""
验证一：沙箱里到底"能做什么、不能做什么"
==========================================
**目的**：把「沙箱限制」这件事说准，避免把 run_python 的路径缺陷
误判成「沙箱不让做 join / 不让读项目内文件」。

**结论预期**（本脚本会实测）：
  · 沙箱**不**禁止读项目内的文件，也**不**禁止跨文件 join
  · 沙箱**只**禁止「项目目录之外的路径」+ 黑名单里的危险用法
  · cwd=sandbox/ 只影响**相对路径解析** —— data/xxx.csv 会找不到，
    用 DATA_DIR（预置变量，指向项目 data/）拼绝对路径就一切正常

★★ 本脚本的判分方式（踩过坑才这么写）：
   每条 CASE 除了「成功/失败」，还必须校验**输出里出现指定字符串**（must_contain）。
   为什么：第一版只判断「没抛异常」就算通过，于是
   join 那条即使算出的数字是错的（没 strip 产品名 -> 4485258）也照样打 ✅。
   **一个不会失败的检查等于没检查。**

**不经模型**，直接调 tools.run_python，所以结果是确定性的。
用法（项目根目录，用装了 pandas 的解释器，例如 .venv）：
    .\.venv\Scripts\python.exe eval\verify_sandbox_path.py
"""
import sys
from pathlib import Path

EVAL = Path(__file__).resolve().parent
ROOT = EVAL.parent
sys.path.insert(0, str(ROOT))

import tools  # noqa: E402

# (名称, 代码, 是否预期成功, 输出必须包含的串, 说明)
CASES = [
    ("(1) 相对路径（模型最初的写法）",
     "import pandas as pd\ndf = pd.read_csv('data/hard/products.csv')\nprint(df.shape)",
     False, ["FileNotFoundError"],
     "预期失败：FileNotFoundError（cwd 是 sandbox/，不是项目根）"),

    ("(2) 用 DATA_DIR 拼绝对路径",
     "import pandas as pd\ndf = pd.read_csv(DATA_DIR + '/hard/products.csv')\n"
     "print(df.shape[0], '行')",
     True, ["8 行"],
     "预期成功：8 行"),

    ("(3) ★ 跨文件 JOIN（关键：证明沙箱不拦 join）",
     "import pandas as pd\n"
     "o = pd.read_csv(DATA_DIR + '/hard/orders_dirty.csv')\n"
     "p = pd.read_csv(DATA_DIR + '/hard/products.csv')\n"
     "o['单价'] = pd.to_numeric(o['单价'].astype(str).str.replace(',', '', regex=False), errors='coerce')\n"
     "o['销售额'] = o['数量'] * o['单价']\n"
     "o['产品'] = o['产品'].astype(str).str.strip()\n"
     "m = o.merge(p, on='产品', how='left')\n"
     "g = m.groupby('类别')['销售额'].sum().sort_values(ascending=False)\n"
     "print(len(m), '行')\nprint(g.index[0], int(g.iloc[0]))",
     True, ["270 行", "电脑 4842055"],
     "预期成功：270 行 · 电脑 4842055（与 hard_set.json 标准答案一致）"),

    ("(3b) 反例：不 strip 产品名就 join（少 356797）【14 行而非 12 行，见文末注】",
     "import pandas as pd\n"
     "o = pd.read_csv(DATA_DIR + '/hard/orders_dirty.csv')\n"
     "p = pd.read_csv(DATA_DIR + '/hard/products.csv')\n"
     "o['单价'] = pd.to_numeric(o['单价'].astype(str).str.replace(',', '', regex=False), errors='coerce')\n"
     "o['销售额'] = o['数量'] * o['单价']\n"
     "m = o.merge(p, on='产品', how='left')\n"
     "n_miss = int(m['类别'].isna().sum())\n"
     "g = m.groupby('类别')['销售额'].sum().sort_values(ascending=False)\n"
     "print('没匹配上的行', n_miss)\nprint(g.index[0], int(g.iloc[0]))",
     True, ["没匹配上的行 14", "电脑 4485258"],
     "预期成功但数字变小：14 行带空格的产品名匹配不上 -> 4485258（这是**错误**答案）"),

    ("(4) 项目目录之外的路径",
     "print(open(r'C:\\Windows\\win.ini').read()[:50])",
     False, ["拒绝执行"],
     "预期被 _guard 拦下"),

    ("(5) 打印 cwd（证明子进程在哪跑）",
     "import os\nprint('cwd =', os.getcwd())",
     True, ["sandbox"],
     "预期成功：cwd 指向 sandbox/"),
]


def main() -> int:
    print("=== 沙箱路径能力实测（直接调 tools.run_python，不经模型）===\n")
    ok = 0
    for name, code, expect_ok, must, note in CASES:
        out = tools.run_python(code)
        blocked = out.startswith("拒绝执行")
        failed = ("Traceback" in out) or ("Error" in out) or blocked
        got_ok = not failed
        missing = [m for m in must if m not in out]
        good = (got_ok == expect_ok) and not missing
        ok += good
        print(f"{'[OK]' if good else '[FAIL]'} {name}")
        print(f"   {note}")
        head = out.strip().splitlines()
        show = " / ".join(x.strip() for x in head[:4])[:240] if head else "(空输出)"
        print(f"   实际 -> {show}")
        if missing:
            print(f"   ★ 校验失败：输出里没找到 {missing}")
        print()

    print(f"=== {ok}/{len(CASES)} 项符合预期 ===")
    print("\n注：脏数据里**带空格的产品名是 14 行**，不是 hard_set.json meta 里写的 12。")
    print("    12 是「注入时改动」的行数；10 行重复行是在其后生成的，")
    print("    其中 2 行原本就带空格 -> 最终文件里带空格的行是 14 行。")
    print("    两处都对，只是口径不同（注入行数 vs 文件现状），别混用。")
    print("\n一句话结论：沙箱**没有**禁止读项目内文件、也**没有**禁止 join；")
    print("它禁止的是「项目外路径」和「黑名单危险用法」。相对路径失败纯粹是 cwd 造成的。")
    return 0 if ok == len(CASES) else 1


if __name__ == "__main__":
    sys.exit(main())