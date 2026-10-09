# -*- coding: utf-8 -*-
"""
多工具 AI Agent
=====================================================
Agent 主循环 + 工具集：模型自己决定调哪些工具、按什么顺序调。

工具（与下方 TOOLS_SCHEMA 保持一致）：
  get_current_time / calculate / list_files / describe_csv / read_excel / aggregate_csv
  （高危工具 run_python 默认不挂载，需设 ENABLE_RUN_PYTHON=1 开启）

链路：
  用户提问 → 模型看"工具清单"自己决策
       ├─ 不用工具  → 直接回答
       └─ 要调工具  → 我们执行 → 结果喂回 → 模型再决策 → …（最多 MAX_STEPS 轮）→ 最终答案

接口：
  GET  /        前端页面（能看答案 + 工具调用轨迹）
  POST /agent   {"question": "..."} → {answer, trace, steps}
  GET  /health  健康检查（当前模式、已挂载工具、轮次上限）
  GET  /assets  数据资产清单（前端"数据资产"面板用）

端口：8001（写在文件末尾的 __main__ 分支里）。
"""
import json
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import OpenAI

import tools

# ====================== 启动自检：依赖缺一个都别"假装能跑" ======================
# 真实事故（2026-10-09）：用 `python -m venv .venv` + `pip install -r requirements.txt`
# 建出来的项目内环境，装了 fastapi/openai/dotenv 却**漏了 pandas**（它是 requirements 最后一行，
# 安装没跑完）。于是服务**能正常启动、网页能打开**，但 describe_csv / aggregate_csv /
# run_python 全部报 ModuleNotFoundError —— 模型只能在回答里说"工具全部执行失败"。
# 这类失败最难排查，因为表面上"服务是好的"。
# 因此这里在**启动时**就把话说清楚：缺什么、当前用的是哪个解释器、该怎么修。
import importlib.util as _ilu
import sys as _sys

_REQUIRED = {
    "pandas": "describe_csv / aggregate_csv / run_python 都靠它读表",
    "numpy": "pandas 的依赖，同时也被 run_python 的预置导入用到",
    "openpyxl": "read_excel 靠它读 .xlsx（财务勾稽模式必需）",
}
_missing = {m: why for m, why in _REQUIRED.items() if _ilu.find_spec(m) is None}

if _missing:
    _lines = [
        "",
        "=" * 78,
        "⚠️  启动自检未通过：当前解释器缺少以下依赖，工具会在运行时报错",
        "=" * 78,
        f"  当前解释器：{_sys.executable}",
        "",
    ]
    for _m, _why in _missing.items():
        _lines.append(f"  ✗ {_m:<10} —— {_why}")
    _lines += [
        "",
        "  修复（二选一）：",
        f"    ① 给这个环境补装：",
        f'       "{_sys.executable}" -m pip install {" ".join(_missing)}',
        f"    ② 或换一个装了全部依赖的解释器启动（例如项目里的 .venv）：",
        f"       .venv\\Scripts\\python.exe main.py        # Windows",
        "",
        "  说明：自检不阻断启动（网页仍可打开），但上面这些工具一定不可用。",
        "=" * 78,
        "",
    ]
    print("\n".join(_lines))
else:
    print(f"[自检] 依赖齐全（pandas / numpy / openpyxl），解释器：{_sys.executable}")

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"

# 加载密钥：优先项目自己的 .env；没有就往上找两级
# （方便把 .env 放在工作区根目录统一管理，同时不写死任何本机绝对路径）
load_dotenv(BASE_DIR / ".env")
for _parent in (BASE_DIR.parent, BASE_DIR.parent.parent):
    if (_parent / ".env").exists():
        load_dotenv(_parent / ".env")
        break

client = OpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"), base_url="https://api.deepseek.com")

# ---- 工具清单：告诉模型"你有哪些工具、分别什么时候用" ----
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "获取当前的日期和时间。当用户问『现在几点』『今天几号』这类问题时使用。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "计算一个数学表达式，例如 '12*35+7'。当用户需要精确计算时使用。",
            "parameters": {
                "type": "object",
                "properties": {"expression": {"type": "string", "description": "要计算的数学表达式"}},
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "列出某个目录下的文件与文件夹。dir_path 必须是目录（如 '.' 或 'data'），不要传文件名。不确定数据文件放在哪里时用它找一找。",
            "parameters": {
                "type": "object",
                "properties": {"dir_path": {"type": "string", "description": "相对路径，默认 '.'"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "describe_csv",
            "description": ("在本地分析一个 CSV 的结构与统计概况：列名、类型、缺失数、数值列统计。"
                            "分析数据之前先用它了解数据结构。为保护隐私，它不返回任何明细行。"),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "CSV 的相对路径，如 data/sales.csv"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_excel",
            "description": ("读取一个 Excel 工作簿（.xlsx/.xlsm）的**结构与双通道内容**："
                            "表清单、行列规模、合并单元格、标签/数值/公式，以及**缓存值是否可用**。"
                            "★ 财务勾稽必须先调它：它同时给出「公式文本（通道A）」和「缓存值（通道B）」，"
                            "并明确告诉你哪些公式格缓存缺失 —— 程序生成、没被 Excel 保存过的文件，"
                            "缓存值会整片为空，**不要当成 0**。路径写项目内相对路径，如 data/fin/sample_fin.xlsx。"),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "工作簿的相对路径，如 data/fin/sample_fin.xlsx"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "aggregate_csv",
            "description": ("在本地对 CSV 做分组聚合（分组、求和、平均、计数、排序取前几名），"
                            "只把聚合结果返回。统计类问题用它。"
                            'value_expr 可以是列名，也可以是简单算式，如 "数量*单价"。'),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "CSV 的相对路径，如 data/sales.csv"},
                    "group_by": {"type": "string", "description": "按哪一列分组，如 产品 / 地区 / 销售员"},
                    "value_expr": {"type": "string", "description": "对哪一列或算式聚合，如 数量*单价；agg=count 时可留空"},
                    "agg": {"type": "string", "enum": ["sum", "mean", "count", "max", "min"], "description": "聚合方式，默认 sum"},
                    "top_n": {"type": "integer", "description": "只返回前几名，默认 10"},
                },
                "required": ["path", "group_by"],
            },
        },
    },
]

# 工具名 → 真正要执行的 Python 函数
# 默认只挂"受限、安全"的工具：它们只在本地分析，只回传聚合结果，隐私数据不出本机。
TOOL_FUNCS = {
    "get_current_time": tools.get_current_time,
    "calculate": tools.calculate,
    "list_files": tools.list_files,
    "describe_csv": tools.describe_csv,
    "aggregate_csv": tools.aggregate_csv,
    # read_excel 是**只读**工具（只读项目内文件、不批量返回明细），
    # 因此和 describe_csv 同级常开，不需要 ENABLE_RUN_PYTHON。
    "read_excel": tools.read_excel,
}

# run_python（执行任意代码）**默认关闭**：能力最强、也最危险。
# 需要时显式开启：设置环境变量 ENABLE_RUN_PYTHON=1
if os.getenv("ENABLE_RUN_PYTHON") == "1":
    TOOLS_SCHEMA.append({
        "type": "function",
        "function": {
            "name": "run_python",
            "description": (
                "执行一段 Python 代码（可用 pandas / numpy），返回 print 的输出。"
                "适合做**需要清洗或跨文件关联**的分析：比如把文本列转成数字、去重、"
                "合并两个 CSV、多步派生指标。\n"
                "★★ 读文件请务必用**绝对路径**：`pd.read_csv(DATA_DIR + '/xxx.csv')`。\n"
                "   本段代码的工作目录是 sandbox/（不是项目根目录），"
                "所以写相对路径 `data/xxx.csv` 会**找不到文件**；"
                "`DATA_DIR` 已在代码开头自动定义好，指向本项目的 data/ 目录，"
                "例如 `pd.read_csv(DATA_DIR + '/hard/orders_dirty.csv')`。"
            ),
            "parameters": {
                "type": "object",
                "properties": {"code": {"type": "string", "description": "要执行的 Python 代码"}},
                "required": ["code"],
            },
        },
    })
    TOOL_FUNCS["run_python"] = tools.run_python

SYSTEM_PROMPT = """你是一个可以调用工具的助手。你有这些工具：
- get_current_time：获取当前日期时间
- calculate：计算数学表达式
- list_files：列出目录下的文件
- describe_csv：在本地查看 CSV 的列名、类型、缺失数、数值列统计（不含明细行）
- aggregate_csv：在本地做分组聚合（分组/求和/平均/计数/排序），只返回聚合结果

【数据分析任务的标准流程】
1. 先用 list_files 找到数据文件（通常在 data/ 目录）；
2. 用 describe_csv 了解列名、类型和大致分布；
3. 用 aggregate_csv 做统计。注意 value_expr 可以写算式，例如要算销售额（数据里只有数量和单价）就传 "数量*单价"；
4. 最后用中文把结论讲清楚。

规则：
1. 先分清问题属于哪一类：
   - **要"本地数据里的数字"**（某个表/某个公司某年的某个指标、某文件里有多少行…）
     → **必须先调工具查 data/ 目录，即使你认为自己记得答案。**
     凭记忆报出的公开数据（尤其上市公司财报）一律不算数：模型记忆会记错，而且没有来源可追溯。
   - **与本地数据无关**（闲聊、概念解释、换算公式、当前时间）→ 直接回答，不要调用工具。
2. 只用工具返回的真实结果作答，不要编造数字；
3. **在说"没有数据/请你把文件放进 data/"之前，必须先用 list_files 把 data/ 目录列出来**，
   确认真的没有再说。data/ 下可能还有子目录，要逐层看。
4. 只允许分析本项目 data/ 目录内的文件；不要尝试访问项目外的路径；
5. 这些工具**只返回聚合结果，不返回明细行**（保护隐私），所以不要试图索取原始数据行；
6. 回答要用自然语言，**绝对不要**把工具调用的内部标记（如 <|DSML|>、invoke name=）写进回答。
"""

# ★ 提示词模式：默认是 CSV 数据分析版；要做财务报表勾稽就设 AGENT_MODE=finance。
#   财务版提示词放在 prompts/finance_agent.md（可随时改文本，不用动代码）。
AGENT_MODE = os.getenv("AGENT_MODE", "csv")
_FIN_PROMPT_FILE = Path(__file__).parent / "prompts" / "finance_agent.md"
if AGENT_MODE == "finance":
    if _FIN_PROMPT_FILE.exists():
        SYSTEM_PROMPT = _FIN_PROMPT_FILE.read_text(encoding="utf-8")
        print(f"[提示词] 已加载财务勾稽版（{len(SYSTEM_PROMPT)} 字符）")
    else:
        print(f"[提示词] ⚠️ AGENT_MODE=finance 但找不到 {_FIN_PROMPT_FILE}，已回退到 CSV 版")

MAX_STEPS = int(os.getenv("MAX_STEPS", "15"))   # 最多几轮"决策 → 调工具 → 喂回"，防止死循环
# ★ 为什么从 5 提到 15（实测依据，不是拍脑袋）：
#   在「财务勾稽」这类真实任务上，一次跑批用了 9 次工具调用、在第 5 轮就用尽配额，
#   报告还没写出来就被兜底分支截断了。要完成「结构勘察 → 双通道读取 → 逐条校验 → 出报告」，
#   5 轮根本不够。轮次上限是防死循环的护栏，不该变成能力的瓶颈。


def _looks_like_tool_markup(text: str) -> bool:
    """判断回答里是否泄漏了"工具调用的内部标记"（DSML 泄漏）。

    有些模型偶尔会把本该藏在 tool_calls 字段里的调用语法，直接写进正文，
    用户看到的回答就会变成一堆 <|DSML|>... 。检测到就重新生成一次。
    """
    t = text or ""
    return ("DSML" in t) or ("invoke name=" in t) or ("<|tool" in t)


def _strip_tool_markup(text: str) -> str:
    """保底清洗：万一重新生成仍然泄漏，也**绝不能让用户看见内部标记**。

    这不是"把回答修好"，是一道兜底。它做两件事：
      · 标记出现在正文之后 → 保留标记之前的正文并注明已截断；
      · 正文本身就没成形 → 换成一句实话，而不是把内部语法丢给用户。
    标记里的竖线有全角（U+FF5C）和半角两种写法，这里都用 unicode 转义匹配，
    避免源码里出现字面量。
    """
    import re

    t = text or ""
    pipes = re.escape("\uff5c")                      # 全角竖线
    m = re.search(r"[<\uff5c]{0,3}\s*DSML", t) or re.search(r"<\|tool", t)
    if not m:
        return t
    head = t[: m.start()].rstrip()
    if len(head) >= 40:                              # 前面还有像样的正文
        return head + "\n\n（回答末尾混入了工具调用的内部标记，已截断。）"
    return ("已达最大工具步数，但模型没能组织出完整回答。"
            "已获得的工具结果都在上方轨迹里，可据此判断下一步。")


def run_agent(question: str) -> dict:
    """Agent 主循环：模型自己决定调不调工具、调哪个、调几次。"""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    trace = []

    for _ in range(MAX_STEPS):
        resp = client.chat.completions.create(
            model="deepseek-chat", messages=messages, tools=TOOLS_SCHEMA)
        msg = resp.choices[0].message

        # 模型不要工具 → 最终回答
        if not msg.tool_calls:
            answer = msg.content or ""
            # DSML 泄漏：模型把工具调用的内部标记当正文吐了出来 → 让它重新生成一次
            if _looks_like_tool_markup(answer):
                messages.append({"role": "assistant", "content": answer})
                messages.append({
                    "role": "user",
                    "content": ("你的上一条回答里混进了工具调用的内部标记。"
                                "请直接用中文自然语言重新回答，不要输出任何 <|DSML|>、invoke name= 之类的内部标记。"),
                })
                retry = client.chat.completions.create(model="deepseek-chat", messages=messages)
                answer = (retry.choices[0].message.content or "").strip() or answer
                trace.append({
                    "tool": "(格式纠正)",
                    "arguments": {},
                    "result": "检测到回答里泄漏了工具调用标记，已让模型重新生成",
                })
            return {"answer": answer, "trace": trace, "steps": len(trace)}

        # 模型要调工具 → 执行，并把结果喂回去
        messages.append(msg)
        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            func = TOOL_FUNCS.get(name)
            if func is None:
                result = f"未知工具：{name}"
            else:
                try:
                    result = str(func(**args))        # 执行工具
                except Exception as e:
                    # ★ 关键：工具报错不能让整个请求挂掉。
                    # 把错误当成"工具结果"喂回模型，它看到后能自己纠正、重试。
                    result = f"工具执行出错：{type(e).__name__}: {e}。请检查参数后重试。"
            trace.append({"tool": name, "arguments": args, "result": result[:600]})
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

    # 到了最大步数还没给出最终回答 → 最后再问一次（这次不给工具），让它基于已有信息作答。
    # 这样用户至少能得到一个解释，而不是一句冷冰冰的"达到最大步数"。
    final = client.chat.completions.create(model="deepseek-chat", messages=messages)
    answer = final.choices[0].message.content or ""

    # ★ 缺陷修复（原第 2 号缺陷）：兜底分支原先**直接返回原文**，绕过了上面那条正常路径上的
    #   DSML 清洗。结果是——**最需要兜底的场景（模型已经卡了十几轮）反而最容易把内部标记吐给用户**。
    #   实测在真实财务任务上复现过：整段回答全是内部调用语法。
    if _looks_like_tool_markup(answer):
        note = "兜底回答里出现工具调用内部标记，已处理"
        try:
            retry = client.chat.completions.create(
                model="deepseek-chat",
                messages=messages + [
                    {"role": "assistant", "content": answer},
                    {"role": "user", "content": (
                        "你的回答里混进了工具调用的内部标记，用户看到的就是一堆内部语法。"
                        "请**只用中文自然语言**重述你目前已经确认的结论，"
                        "不要再输出任何内部标记，也不要再尝试调用工具。")},
                ],
            )
            cleaned = (retry.choices[0].message.content or "").strip()
            if cleaned and not _looks_like_tool_markup(cleaned):
                answer = cleaned
            else:
                answer = _strip_tool_markup(answer)
                note += "（重新生成仍未通过，已按保底规则清洗）"
        except Exception:
            answer = _strip_tool_markup(answer)
            note += "（重新生成失败，已按保底规则清洗）"
        trace.append({"tool": "(格式纠正)", "arguments": {}, "result": note})

    return {
        "answer": answer,
        "trace": trace,
        "steps": len(trace),
        "note": "已达到最大工具调用步数，以下为基于已获得信息的回答",
    }


# ====================== FastAPI ======================
app = FastAPI(title="多工具 AI Agent")


class AgentRequest(BaseModel):
    question: str


@app.get("/")
def home():
    """返回前端页面（多工具 AI Agent）。"""
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/agent")
def agent(req: AgentRequest):
    """Agent 问答：模型自己决定调用哪些工具。"""
    return run_agent(req.question)


@app.get("/health")
def health():
    """健康检查：当前模式、工具集、轮次上限 —— 前端用它显示真实状态。"""
    return {
        "status": "ok",
        "mode": AGENT_MODE,
        "tools": list(TOOL_FUNCS),
        "max_steps": MAX_STEPS,
    }


@app.get("/assets")
def assets():
    """数据资产清单（只读）：data/ 下的文件、大小、类型。

    给前端侧栏用 —— 让它显示**库里真有什么**，而不是写死的文案。
    新增一个 csv / xlsx 进去，刷新页面就会多一行。
    """
    files = []
    # ★ 用 tools.DATA_DIR，别在 main.py 里另起一个：数据目录只该有一个真相来源。
    #   （第一版直接写了 DATA_DIR，而 main.py 里没这个变量 → 500 NameError）
    data_dir = tools.DATA_DIR
    for p in sorted(data_dir.rglob("*")):
        if not p.is_file() or p.name.startswith("."):
            continue
        rel = p.relative_to(data_dir).as_posix()
        suffix = p.suffix.lower()
        kind = ("明细表" if suffix == ".csv" else
                "工作簿" if suffix in (".xlsx", ".xlsm") else
                "说明" if suffix == ".md" else
                "结论" if suffix == ".json" else "其它")
        item = {"path": f"data/{rel}", "name": p.stem, "size_kb": round(p.stat().st_size / 1024, 1),
                "kind": kind, "ext": suffix}
        # CSV 顺手给出行列数（读表头，不做统计；读不动就跳过）
        if suffix == ".csv":
            try:
                import pandas as pd
                df = pd.read_csv(p, nrows=0)
                item["rows"] = sum(1 for _ in open(p, encoding="utf-8-sig", errors="ignore")) - 1
                item["cols"] = len(df.columns)
            except Exception:
                pass
        files.append(item)
    return {"files": files, "count": len(files)}


# 方便启动：直接 `python main.py`（端口 8001，避开项目 A 的 8000）
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8001, reload=True)
