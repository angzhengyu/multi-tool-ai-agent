# -*- coding: utf-8 -*-
r"""
难度探针：造一份**脏数据** + 一组"必须小心处理才答对"的任务
==============================================================
为什么需要它：
  主评测集（28 条）跑出 **100% 完成率** —— 但那是**干净数据**（240 行、零缺失）上的
  直白任务。100% 高的原因不是 Agent 强，而是**题太容易**。这个探针就是来把水分挤掉的。

刻意注入的 6 类脏（全部可确定性复现，seed 固定）：
  ① 完全重复行        10 行（同订单号、所有字段一字不差）→ 不去重就会多算
  ② 数量缺失           8 行
  ③ 单价缺失          12 行
  ④ 单价写成带千分位的**文本**（"2,599"）15 行 → 整列变 object，
     直接 .max() / 求和会得到**字符串比较**或报错，必须先 to_numeric 清洗
  ⑤ 产品名首尾带空格  12 行 → 不 strip 就会被当成不同产品，分组数变多
  ⑥ 日期混格式        60 行写成 2026/3/5（其余是 2026-03-05）→ 排序/取最早日期会错
另外还有一个**跨文件关联**任务：脏表里没有「类别」列，要用 data/hard/products.csv 关联进来
—— 而 aggregate_csv 只能单表操作，所以只能上 run_python，是"多工具编排"的硬考。

★ 标准答案全部由本脚本用 pandas 现算，且**每题的判定规则都写进题干**
  （比如"忽略缺失值""去掉完全重复的行"），避免"标准答案本身有歧义"。

用法（在本项目根目录）：
    python eval/gen_hard_set.py
"""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent
HARD = ROOT / "data" / "hard"

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

rng = np.random.default_rng(20260920)

N_ROWS = 260
N_DUP = 10          # 完全重复的行数
N_MISS_QTY = 8      # 数量缺失
N_MISS_PRICE = 12   # 单价缺失
N_COMMA_PRICE = 15  # 单价带千分位逗号
N_SPACE_PROD = 12   # 产品名首尾带空格
N_SLASH_DATE = 60   # 日期用 / 分隔

PRODUCTS = ["充电宝", "平板", "手机", "显示器", "机械键盘", "笔记本", "耳机", "鼠标"]
# ★ 刻意让一个类别含多个产品，这样"按类别统计"**必须真的做关联**才能算对，
#   否则如果每个产品自成一类，不做 join 也能蒙对 —— 那就白测了。
CATEGORY = {"笔记本": "电脑", "平板": "电脑",          # 电脑 = 笔记本 + 平板
            "显示器": "外设", "机械键盘": "外设", "鼠标": "外设",   # 外设 = 显示器+机械键盘+鼠标
            "充电宝": "配件", "耳机": "配件",          # 配件 = 充电宝 + 耳机
            "手机": "手机"}
BRAND = {"笔记本": "芯河", "显示器": "芯河", "机械键盘": "键入", "鼠标": "键入",
         "充电宝": "随身", "耳机": "随身", "手机": "星驰", "平板": "星驰"}
REGIONS = ["华东", "华中", "华北", "华南", "西南"]
PRICE_BY_PROD = {"笔记本": 5899, "手机": 3999, "平板": 2599, "显示器": 1299,
                 "耳机": 799, "机械键盘": 499, "充电宝": 199, "鼠标": 149}


def build():
    HARD.mkdir(parents=True, exist_ok=True)

    # ── 1) 生成"干净"底表 ──
    prod = rng.choice(PRODUCTS, N_ROWS)
    base = pd.DataFrame({
        "订单号": [f"SO-{(i + 1) * 3:05d}" for i in range(N_ROWS)],
        "日期": [f"2026-{rng.integers(1, 7):02d}-{rng.integers(1, 28):02d}" for _ in range(N_ROWS)],
        "产品": prod,
        "地区": rng.choice(REGIONS, N_ROWS),
        "数量": rng.integers(1, 41, N_ROWS),
        "单价": [PRICE_BY_PROD[p] for p in prod],
    })

    # ── 2) 先注入全部脏 ──
    df = base.copy()
    n_unique = len(base)

    # ── 3) 注入脏：缺失值 ──
    idx_qty = rng.choice(n_unique, N_MISS_QTY, replace=False)
    df["数量"] = df["数量"].astype(float)
    df.loc[idx_qty, "数量"] = np.nan
    idx_pr = rng.choice([i for i in range(n_unique) if i not in set(idx_qty)],
                        N_MISS_PRICE, replace=False)
    df.loc[idx_pr, "单价"] = np.nan

    # ── 4) 注入脏：单价写成带千分位的文本 ──
    # ★ pandas 3.x 不允许往 float64 列里塞字符串，所以先把该列转成 object
    df["单价"] = df["单价"].astype(object)
    idx_c = [i for i in range(n_unique)
             if i not in set(idx_qty) and i not in set(idx_pr)][:N_COMMA_PRICE]
    for i in idx_c:
        df.loc[i, "单价"] = f"{int(df.loc[i, '单价']):,}"

    # ── 5) 注入脏：产品名首尾空格 ──
    df["产品"] = df["产品"].astype(object)
    idx_s = [i for i in range(n_unique) if i not in set(idx_c)][:N_SPACE_PROD]
    for i in idx_s:
        df.loc[i, "产品"] = "  " + str(df.loc[i, "产品"]) + " "

    # ── 6) 注入脏：日期混格式 ──
    df["日期"] = df["日期"].astype(object)
    idx_d = rng.choice(n_unique, N_SLASH_DATE, replace=False)
    for i in idx_d:
        y, m, d = str(df.loc[i, "日期"]).split("-")
        df.loc[i, "日期"] = f"{y}/{int(m)}/{int(d)}"

    # ── 7) 最后才复制"完全重复行"（放在脏注入之后，保证副本与原件一字不差）──
    dup = df.sample(N_DUP, random_state=7)
    df = pd.concat([df, dup], ignore_index=True)

    df.to_csv(HARD / "orders_dirty.csv", index=False, encoding="utf-8-sig")

    # ── 8) 关联表 ──
    pd.DataFrame({"产品": PRODUCTS,
                  "类别": [CATEGORY[p] for p in PRODUCTS],
                  "品牌": [BRAND[p] for p in PRODUCTS]}).to_csv(
        HARD / "products.csv", index=False, encoding="utf-8-sig")

    # ══ 标准答案（全部现算；每题的判定规则写进题干）══
    rows_all = len(df)
    uniq_orders = int(df["订单号"].nunique())
    rows_dedup = len(df.drop_duplicates())
    miss_qty = int(df["数量"].isna().sum())
    miss_price = int(df["单价"].isna().sum())
    qty_sum = float(df["数量"].sum())                     # pandas 默认跳过 NaN
    # ★★ 这里踩过一个真坑，记下来：
    #   `pd.to_numeric("2,599")` 会**解析失败变成 NaN**，于是那 15 行带千分位的价格
    #   被当成缺失值丢掉了，所有「数量×单价」的和**全部被低估**。
    #   必须**先去掉千分位逗号**再转数值。
    #   （更糟的是我后来还用同一个错表达式写"校验脚本"，把错数字又"确认"了一遍 ——
    #     用同样有 bug 的代码去校验另一段代码，等于没校验。）
    price_num = pd.to_numeric(
        df["单价"].astype(str).str.replace(",", "", regex=False), errors="coerce")
    price_max = float(price_num.max())
    price_mean = round(float(price_num.mean()), 2)
    prod_clean = df["产品"].astype(str).str.strip()
    n_prod = int(prod_clean.nunique())
    rev = df["数量"] * price_num                          # 任一侧 NaN → 该行 NaN，自动忽略
    rev_by_prod = rev.groupby(prod_clean).sum().sort_values(ascending=False)
    top_prod = str(rev_by_prod.index[0])
    top_prod_rev = int(round(rev_by_prod.iloc[0]))

    merged = df.assign(产品=prod_clean, _rev=rev).merge(
        pd.DataFrame({"产品": PRODUCTS, "类别": [CATEGORY[p] for p in PRODUCTS]}),
        on="产品", how="left")
    rev_by_cat = merged["_rev"].groupby(merged["类别"]).sum().sort_values(ascending=False)
    top_cat = str(rev_by_cat.index[0])
    top_cat_rev = int(round(rev_by_cat.iloc[0]))

    truth = {
        "rows_all": rows_all, "uniq_orders": uniq_orders, "rows_dedup": rows_dedup,
        "miss_qty": miss_qty, "miss_price": miss_price, "qty_sum": qty_sum,
        "price_max": price_max, "price_mean": price_mean, "n_prod": n_prod,
        "top_prod": top_prod, "top_prod_rev": top_prod_rev,
        "top_cat": top_cat, "top_cat_rev": top_cat_rev,
    }

    tasks = [
        {"id": "H01", "dirt": "重复行", "question":
         "data/hard/orders_dirty.csv 一共有多少条数据行？（就是文件里有多少行数据，不去重）",
         "expect_numbers": [rows_all], "expect_texts": []},
        {"id": "H02", "dirt": "重复行", "question":
         "data/hard/orders_dirty.csv 里，「订单号」一共有多少个不重复的值？",
         "expect_numbers": [uniq_orders], "expect_texts": []},
        {"id": "H03", "dirt": "重复行", "question":
         "请把 data/hard/orders_dirty.csv 里**完全重复的行**去掉（所有字段都相同的行只保留一条），"
         "剩下多少条记录？",
         "expect_numbers": [rows_dedup], "expect_texts": []},
        {"id": "H04", "dirt": "缺失值", "question":
         "data/hard/orders_dirty.csv 的「数量」列里有多少个缺失值？",
         "expect_numbers": [miss_qty], "expect_texts": []},
        {"id": "H05", "dirt": "缺失值", "question":
         "data/hard/orders_dirty.csv 的「单价」列里有多少个缺失值？",
         "expect_numbers": [miss_price], "expect_texts": []},
        {"id": "H06", "dirt": "缺失值", "question":
         "data/hard/orders_dirty.csv 的「数量」列总和是多少？（缺失值忽略不计）",
         "expect_numbers": [int(qty_sum)], "expect_texts": []},
        {"id": "H07", "dirt": "数值是文本+千分位", "question":
         "data/hard/orders_dirty.csv 的「单价」列最大值是多少？"
         "（注意这一列混着形如 2,599 的文本，要先转成数字再取最大值）",
         "expect_numbers": [int(price_max)], "expect_texts": []},
        {"id": "H08", "dirt": "数值是文本+千分位", "question":
         "data/hard/orders_dirty.csv 的「单价」列平均值是多少？"
         "（先转成数字，缺失值忽略，保留两位小数）",
         "expect_numbers": [price_mean], "expect_texts": []},
        {"id": "H09", "dirt": "文本带空格", "question":
         "data/hard/orders_dirty.csv 的「产品」列里，一共有多少种不同的产品？"
         "（注意部分取值首尾有多余空格，应当去掉空格后再统计）",
         "expect_numbers": [n_prod], "expect_texts": []},
        {"id": "H10", "dirt": "综合", "question":
         "在 data/hard/orders_dirty.csv 里，哪种产品的销售额（数量×单价）最高？金额是多少？"
         "（数量或单价缺失的行忽略不计）",
         "expect_numbers": [top_prod_rev], "expect_texts": [top_prod]},
        {"id": "H11", "dirt": "跨文件关联", "question":
         "data/hard/orders_dirty.csv 里没有「类别」列，请用 data/hard/products.csv 把「类别」关联进来，"
         "然后告诉我「外设」这个类别的销售额（数量×单价）合计是多少？"
         "（缺失值忽略，产品名首尾空格请先去掉，结果取整数）",
         "expect_numbers": [int(round(rev_by_cat.get("外设", 0)))], "expect_texts": ["外设"]},
        {"id": "H12", "dirt": "跨文件关联", "question":
         "同样把两个文件关联起来之后，哪个「类别」的销售额最高？金额是多少？（取整数）",
         "expect_numbers": [top_cat_rev], "expect_texts": [top_cat]},
    ]

    data = {
        "meta": {
            "purpose": "难度探针：在**脏数据**上考察数据清洗与边界条件处理能力",
            "why": "主评测集是干净数据 → 28 条 100%，区分度不足；本集用来挤出水分",
            "csv": "data/hard/orders_dirty.csv（+ data/hard/products.csv）",
            "injected_dirt": {
                "完全重复行": N_DUP,
                "数量缺失（实测，含重复行）": miss_qty,
                "单价缺失（实测）": miss_price,
                "单价千分位文本": N_COMMA_PRICE,
                "产品名首尾空格": N_SPACE_PROD,
                "日期混用 / 分隔": N_SLASH_DATE,
            },
            "expected_traps": {
                "不去重就会多算": f"总行数 {rows_all} vs 唯一订单 {uniq_orders}",
                "直接对单价求最值会错": f"单价列 dtype={df['单价'].dtype}，"
                                        f"必须先 to_numeric；正确最大值 {int(price_max)}",
                "不 strip 产品名会把品种数算多": f"正确品种数 {n_prod}",
                "不关联就答不出类别": f"按产品最高是「{top_prod}」，"
                                     f"按类别最高是「{top_cat}」——两者不同，必须真做 join",
            },
            "total": len(tasks),
            "truth": truth,
            "truth_note": "所有 expect_numbers 由 pandas 现算；每题判定规则写在题干里",
        },
        "tasks": tasks,
    }
    (OUT / "hard_set.json").write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    with (OUT / "hard_set.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "dirt", "question", "expect_numbers", "expect_texts"])
        for t in tasks:
            w.writerow([t["id"], t["dirt"], t["question"],
                        " | ".join(str(x) for x in t["expect_numbers"]),
                        " | ".join(t["expect_texts"])])

    print(f"✅ 脏数据：{HARD / 'orders_dirty.csv'}")
    print(f"✅ 关联表：{HARD / 'products.csv'}")
    print(f"✅ 难度探针集：{OUT / 'hard_set.json'}（{len(tasks)} 条）")
    print("\n=== 标准答案（pandas 现算）===")
    for k, v in truth.items():
        print(f"   {k:<16} = {v}")
    print("\n=== 脏数据实际形态抽样 ===")
    print(df.head(3).to_string())
    print(f"\n单价列 dtype = {df['单价'].dtype}（混了文本所以不是数值型）")
    print(f"数量列 dtype = {df['数量'].dtype}")
    return 0


if __name__ == "__main__":
    sys.exit(build())
