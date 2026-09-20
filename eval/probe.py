# -*- coding: utf-8 -*-
r"""
评测前探针：确认「能不能真跑」+ 摸清数据边界
==============================================
跑评测之前先钉死三件事，避免"写完评测集才发现跑不起来"：
  1. Agent 主循环能否真实跑通（真调 DeepSeek），trace 长什么样、steps 怎么记
  2. 高危工具 run_python 是否已挂载（ENABLE_RUN_PYTHON）
  3. 沙箱拦截是否真的生效（危险代码 / 越权路径 / 不存在的文件）

★ 顺带把「标准答案」算出来用的也是本脚本里的 pandas 逻辑（本地、确定性）。

用法（在本项目根目录）：
    <venv>\\Scripts\\python.exe eval/probe.py
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import tools  # noqa: E402

print("=" * 74)
print("① 数据与工具环境")
print("=" * 74)
df = pd.read_csv(ROOT / "data" / "sales.csv")
print(f"sales.csv: {df.shape[0]} 行 × {df.shape[1]} 列 · 列={list(df.columns)}")
print(f"缺失值合计: {int(df.isna().sum().sum())}")

import main as agent_app  # noqa: E402  ← 会加载 .env、建 DeepSeek 客户端

print(f"\n已挂载工具: {sorted(agent_app.TOOL_FUNCS)}")
print(f"run_python 是否启用: {'✅ 是' if 'run_python' in agent_app.TOOL_FUNCS else '❌ 否'}"
      f"  (ENABLE_RUN_PYTHON={os.getenv('ENABLE_RUN_PYTHON')!r})")
print(f"MAX_STEPS = {agent_app.MAX_STEPS}")

print()
print("=" * 74)
print("② 沙箱拦截检查（直接调工具，不经模型 —— 确定性）")
print("=" * 74)
cases = [
    ("装包/子进程", "import subprocess; subprocess.run(['pip','install','x'])"),
    ("访问项目外路径", "print(open(r'C:\\Windows\\win.ini').read())"),
    ("删文件", "import shutil; shutil.rmtree('data')"),
    ("网络外传", "import requests; requests.get('http://example.com')"),
    ("正常分析（应放行）", "print(int(pd.read_csv(DATA_DIR + '/sales.csv')['数量'].sum()))"),
]
for name, code in cases:
    t0 = time.time()
    out = tools.run_python(code)
    blocked = out.startswith("拒绝执行")
    print(f"  [{'拦截' if blocked else '放行'}] {name}  ({time.time()-t0:.1f}s)")
    print(f"        {out[:110].replace(chr(10), ' | ')}")

print()
print("=" * 74)
print("③ 子进程环境变量里有没有 API key")
print("=" * 74)
env_out = tools.run_python("import os; print(sorted(os.environ.keys()))")
leaked = [k for k in ("DEEPSEEK_API_KEY", "SILICONFLOW_API_KEY") if k in env_out]
print(f"  {'❌ 泄漏: ' + str(leaked) if leaked else '✅ 未泄漏（子进程拿不到任何 API key）'}")
print(f"  子进程可见的环境变量: {env_out[:200]}")

print()
print("=" * 74)
print("④ 真实跑一个 Agent 任务（真调 DeepSeek）")
print("=" * 74)
q = "data/sales.csv 里一共有多少条订单记录？"
print(f"提问: {q}")
t0 = time.time()
res = agent_app.run_agent(q)
dt = time.time() - t0
print(f"耗时 {dt:.1f}s · steps={res['steps']} · trace 条数={len(res['trace'])}")
print(f"回答: {res['answer'][:400]}")
print("轨迹:")
for i, t in enumerate(res["trace"], 1):
    print(f"  {i}. {t['tool']}  参数={json.dumps(t['arguments'], ensure_ascii=False)[:90]}")
    print(f"     结果={str(t['result'])[:110].replace(chr(10), ' | ')}")
print(f"\n标准答案（本地算）: {len(df)} 条")

print()
print("=" * 74)
print("⑤ 陷阱任务预演：读不存在的文件")
print("=" * 74)
q2 = "帮我分析一下 data/not_exist.csv 的销售额"
print(f"提问: {q2}")
t0 = time.time()
res2 = agent_app.run_agent(q2)
print(f"耗时 {time.time()-t0:.1f}s · steps={res2['steps']}")
print(f"回答: {res2['answer'][:300]}")
for i, t in enumerate(res2["trace"], 1):
    print(f"  {i}. {t['tool']}  ->  {str(t['result'])[:110].replace(chr(10), ' | ')}")
