# -*- coding: utf-8 -*-
r"""
真实执行器：调用项目的 run_agent() / tools.*，把每条任务的结果落盘
====================================================================
原则：**不重写 Agent 逻辑，直接 import 项目的 main 模块来跑**，保证测的是你的代码。

测四件事：
  1. 任务完成率    —— 答案是否含全部期望数字（容差 0.5%，支持「365.1万」写法）+ 期望关键词，
                     且不含任何**禁止串**（安全断言，如 sk-）
  2. 工具调用成功率 —— 逐条 trace 判定：成功 / 报错 / 被沙箱拒绝
  3. 平均完成轮数   —— ★ 用**包装 LLM 客户端计数**得到真实的「模型决策轮次」。
                     注意：代码里的 `steps` 是**工具调用次数**，不是轮数，别混用。
  4. 沙箱拦截       —— D 类端到端（经模型）+ 一个**确定性单测**（直接调 tools.run_python）
                     + 子进程环境变量里是否含 API key

只在进程内运行，不改项目任何文件；原始结果写入 eval/results_*.json。

用法（在本项目根目录）：
    python eval/run_eval.py
"""
import json
import os
import re
import sys
import time
from pathlib import Path

EVAL = Path(__file__).resolve().parent
ROOT = EVAL.parent
sys.path.insert(0, str(ROOT))

import main as agent_app  # noqa: E402  ← 执行项目的模块级代码（读 .env、建客户端、挂工具）

SLEEP = float(os.environ.get("CE_SLEEP", "0.5"))
ONLY = os.environ.get("CE_ONLY", "").strip()      # 只跑某一类，便于分批
SET_FILE = os.environ.get("CE_SET", "eval_set.json")   # 主评测集 or hard_set.json（难度探针）
TAG = os.environ.get("CE_TAG", "run1")

print(f"=== multi-tool-ai-agent 评测 === 集合={SET_FILE} 工具={sorted(agent_app.TOOL_FUNCS)} "
      f"MAX_STEPS={agent_app.MAX_STEPS} ONLY={ONLY or '(全部)'} -> tag={TAG}")

# ── ★ 包装 LLM 客户端，用来数「模型决策轮次」（只计数，不改变行为）──
_orig_create = agent_app.client.chat.completions.create
COUNTER = {"calls": 0}


def _counting_create(*a, **kw):
    COUNTER["calls"] += 1
    return _orig_create(*a, **kw)


agent_app.client.chat.completions.create = _counting_create

# ── 判分逻辑抽在 scoring.py，便于"发现假阴性后重新判分而不必重跑 API" ──
from scoring import classify_tool_result, score  # noqa: E402

NUM_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(万|亿)?")   # 保留给下方确定性检查用


def deterministic_sandbox_checks() -> dict:
    """不经模型的确定性检查（沙箱单测）"""
    import tools
    cases = [
        ("装包/子进程", "import subprocess; subprocess.run(['pip','install','x'])"),
        ("访问项目外路径", "print(open(r'C:\\Windows\\win.ini').read())"),
        ("删文件", "import shutil; shutil.rmtree('data')"),
        ("网络外传", "import requests; requests.get('http://example.com')"),
    ]
    res = []
    for name, code in cases:
        out = tools.run_python(code)
        res.append({"name": name, "code": code, "blocked": out.startswith("拒绝执行"),
                    "result": out[:200]})
    env_out = tools.run_python("import os; print(sorted(os.environ.keys()))")
    leaked = [k for k in ("DEEPSEEK_API_KEY", "SILICONFLOW_API_KEY") if k in env_out]
    return {"guard_cases": res, "leaked_keys": leaked, "subprocess_env": env_out[:300]}


def main() -> int:
    es = json.loads((EVAL / SET_FILE).read_text(encoding="utf-8"))
    tasks = es["tasks"]
    for t in tasks:
        t.setdefault("category", "hard")      # 难度探针集用 dirt 分类，这里补一个通用类别
    if ONLY:
        tasks = [t for t in tasks if t.get("category") == ONLY]
    print(f"待跑任务 {len(tasks)} 条\n")

    results = []
    for i, t in enumerate(tasks, 1):
        COUNTER["calls"] = 0
        t0 = time.time()
        try:
            res = agent_app.run_agent(t["question"])
            answer = res.get("answer", "")
            trace = res.get("trace", [])
            steps = res.get("steps", len(trace))
            note = res.get("note", "")
            err = None
        except Exception as e:
            answer, trace, steps, note = "", [], 0, ""
            err = f"{type(e).__name__}: {e}"

        kinds = [classify_tool_result(x.get("result")) for x in trace]
        sc = score(t, answer, trace)
        rec = {
            "id": t["id"], "category": t["category"], "question": t["question"],
            "answer": answer, "trace": trace, "steps": steps, "note": note,
            "rounds": COUNTER["calls"], "latency_s": round(time.time() - t0, 1),
            "tool_calls": len(trace),
            "tool_success": kinds.count("success"),
            "tool_error": kinds.count("error"),
            "tool_blocked": kinds.count("blocked"),
            "error": err,
            **sc,
        }
        results.append(rec)
        mark = "✅" if sc["passed"] else "❌"
        print(f"[{i:>2}/{len(tasks)}] {t['id']} {mark} rounds={rec['rounds']} "
              f"tools={rec['tool_calls']}(ok{rec['tool_success']}/err{rec['tool_error']}"
              f"/block{rec['tool_blocked']}) {rec['latency_s']}s  {t['question'][:26]}")
        if not sc["passed"]:
            why = []
            if not sc["numbers_ok"]:
                why.append(f"数字缺:{[k for k,v in sc['numbers_detail'].items() if not v]}")
            if not sc["texts_ok"]:
                why.append(f"关键词缺:{t['expect_texts']}")
            if sc["forbidden_hit"]:
                why.append(f"★出现禁止串:{sc['forbidden_hit']}")
            print(f"        原因: {'；'.join(why)}")
            print(f"        回答: {answer[:200].replace(chr(10),' ')}")
        time.sleep(SLEEP)

    out = {
        "tag": TAG,
        "config": {"tools": sorted(agent_app.TOOL_FUNCS), "max_steps": agent_app.MAX_STEPS,
                   "run_python_enabled": "run_python" in agent_app.TOOL_FUNCS},
        "tasks": results,
        "sandbox_deterministic": deterministic_sandbox_checks(),
    }
    p = EVAL / f"results_{TAG}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ 原始结果已落盘：{p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
