# -*- coding: utf-8 -*-
"""
多工具 AI Agent（模块 3：加了前端页面）
=====================================================
Agent 主循环 + 工具集：模型自己决定调哪些工具、按什么顺序调。

工具（与下方 TOOLS_SCHEMA 保持一致）：
  get_current_time / calculate / list_files / describe_csv / aggregate_csv
  （高危工具 run_python 默认不挂载，需设 ENABLE_RUN_PYTHON=1 开启）

链路：
  用户提问 → 模型看"工具清单"自己决策
       ├─ 不用工具  → 直接回答
       └─ 要调工具  → 我们执行 → 结果喂回 → 模型再决策 → …（最多 5 轮）→ 最终答案

接口：
  GET  /        前端页面（能看答案 + 工具调用轨迹）
  POST /agent   {"question": "..."} → {answer, trace, steps}
  GET  /health  健康检查（列出当前有哪些工具）

注意：本项目用端口 8001，避免和项目 A（8000）冲突。
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

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
load_dotenv(BASE_DIR / ".env")
load_dotenv(r"D:\AI-Career\.env")

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
1. 不需要工具就能回答的（闲聊、常识）→ 直接回答，不要调用工具；
2. 只用工具返回的真实结果作答，不要编造数字；
3. 只允许分析本项目 data/ 目录内的文件；不要尝试访问项目外的路径；
4. 这些工具**只返回聚合结果，不返回明细行**（保护隐私），所以不要试图索取原始数据行；
5. 回答要用自然语言，**绝对不要**把工具调用的内部标记（如 <|DSML|>、invoke name=）写进回答。
"""

MAX_STEPS = 5   # 最多几轮"决策 → 调工具 → 喂回"，防止死循环


def _looks_like_tool_markup(text: str) -> bool:
    """判断回答里是否泄漏了"工具调用的内部标记"（DSML 泄漏）。

    有些模型偶尔会把本该藏在 tool_calls 字段里的调用语法，直接写进正文，
    用户看到的回答就会变成一堆 <|DSML|>... 。检测到就重新生成一次。
    """
    t = text or ""
    return ("DSML" in t) or ("invoke name=" in t) or ("<|tool" in t)


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
    return {
        "answer": final.choices[0].message.content,
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
    """健康检查：能看出当前挂了哪些工具。"""
    return {"status": "ok", "tools": list(TOOL_FUNCS)}


# 方便启动：直接 `python main.py`（端口 8001，避开项目 A 的 8000）
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8001, reload=True)
