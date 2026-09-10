# -*- coding: utf-8 -*-
"""
生成一份"数据量适中"的示例销售数据 data/sales.csv（240 行）
用于演示 Agent 读取与分析 CSV 的能力。

运行：python generate_sample_data.py
"""
import csv
import random
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).parent / "data" / "sales.csv"   # 输出到脚本所在目录的 data/ 下

random.seed(42)   # 固定随机种子，保证每次生成的数据一样（可复现）

# 产品 → (类别, 单价)
PRODUCTS = {
    "笔记本": ("电脑", 5899),
    "手机": ("手机", 3299),
    "平板": ("平板", 2599),
    "耳机": ("配件", 799),
    "显示器": ("外设", 1299),
    "机械键盘": ("外设", 499),
    "鼠标": ("配件", 199),
    "充电宝": ("配件", 149),
}
REGIONS = ["华东", "华南", "华北", "华中", "西南"]
SELLERS = ["张伟", "李娜", "王强", "刘敏", "陈杰", "赵磊"]

START = date(2026, 1, 1)
ROWS = 240

rows = []
for i in range(1, ROWS + 1):
    day = START + timedelta(days=random.randint(0, 180))     # 2026 上半年
    name = random.choice(list(PRODUCTS))
    category, price = PRODUCTS[name]
    rows.append({
        "订单号": f"SO-{i:04d}",
        "日期": day.isoformat(),
        "产品": name,
        "类别": category,
        "地区": random.choice(REGIONS),
        "销售员": random.choice(SELLERS),
        "数量": random.randint(1, 40),
        "单价": price,
    })

rows.sort(key=lambda r: r["日期"])     # 按日期排序，更像真实数据

out = OUT
out.parent.mkdir(parents=True, exist_ok=True)
with open(out, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(
        f, fieldnames=["订单号", "日期", "产品", "类别", "地区", "销售员", "数量", "单价"])
    writer.writeheader()
    writer.writerows(rows)

print(f"已生成 {out}，共 {len(rows)} 行")
