# -*- coding: utf-8 -*-
r"""
从 SEC EDGAR 官方接口抓特斯拉 2014-2024 年财务数据（真实一手数据，不用任何第三方库）。

为什么用 SEC 而不是 AKShare / 财经网站
----------------------------------------
1. **一手权威**：10-K 就是提交给 SEC 的原文，XBRL 结构化数据由公司自己申报，不经第三方转手；
2. **零依赖**：`data.sec.gov` 是普通 HTTPS JSON 接口，标准库 urllib 就够，不用装 akshare/yfinance；
3. **可复现**：每次跑都从官方取，结果可对账 —— 而不是把数字抄进代码里（那种做法一旦抄错，
   后面所有分析全跟着错，而且看不出来）。

★ 两个真实的坑（本脚本就是为了绕开它们）
----------------------------------------
坑 1：**同一概念在不同年份用的 tag 不一样**。
      例如「营业收入」，2018 年后公司改用 RevenueFromContractWithCustomerExcludingAssessedTax，
      而旧的 Revenues 标签在早期年份口径更窄。所以这里按**候选 tag 优先级**取，并逐条打印用的是哪个。

坑 2：**一份 10-K 里同时申报了年度值和季度值**。
      只按 `form=10-K & fp=FY` 筛会把季度值也捞进来 → 早年数字会莫名其妙变小。
      所以必须校验 `start → end` 的跨度确实是**整年**（本脚本用 350~380 天判定）。

用法（项目根目录）：
    python fetch_tesla_sec.py

产出（都写进 data/tesla/）：
    sec_raw_facts.csv        原始取数痕迹（tag / 期间 / 值 / 来自哪份申报），用于对账与复查
    tesla_financials.csv     整理后的宽表：年份 × 6 个指标（单位：百万美元）→ 交给 Agent 分析
"""
import csv
import json
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

OUT = Path(__file__).parent / "data" / "tesla"

CIK = "0001318605"          # Tesla, Inc.
# ★ SEC 要求声明调用方身份（填你自己的邮箱即可，不填容易被限流）
UA = {"User-Agent": "Tesla financial analysis (student project) your_email@example.com"}

YEARS = list(range(2014, 2025))     # 2014–2024

# 概念 → 候选 tag（按优先级）。第一个取到就用第一个。
CONCEPTS = [
    ("营收",       ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"]),
    ("毛利",       ["GrossProfit"]),
    ("营业利润",   ["OperatingIncomeLoss"]),
    ("净利润",     ["NetIncomeLoss", "ProfitLoss"]),
    ("研发费用",   ["ResearchAndDevelopmentExpense"]),
    ("销售及管理费用", ["SellingGeneralAndAdministrativeExpense"]),
]

MIN_DAYS, MAX_DAYS = 350, 380        # 整年判定（坑 2）


def fetch_concept(tag: str, attempts: int = 3):
    """取一个 tag 的全部事实；返回 (facts, err)。★ SEC 偶尔很慢，所以要重试。"""
    url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{CIK}/us-gaap/{tag}.json"
    last = ""
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode("utf-8")), None
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None, "HTTP 404（该公司没用过这个 tag）"
            last = f"HTTP {e.code}"
        except Exception as e:
            last = f"{type(e).__name__}"
        time.sleep(1.5 * (i + 1))          # 退避后重试
    return None, f"{last}（重试 {attempts} 次仍失败）"


def pick_annual(facts: dict) -> dict:
    """从事实里挑出**真正的年度值**：unit=USD、含 start/end、跨度≈1 年。返回 {年份: (值, 来源文件, 申报日)}"""
    out = {}
    for unit, arr in (facts.get("units") or {}).items():
        if unit != "USD":
            continue
        for x in arr:
            if "start" not in x or "end" not in x:
                continue
            try:
                d0 = date.fromisoformat(x["start"])
                d1 = date.fromisoformat(x["end"])
            except Exception:
                continue
            if not (MIN_DAYS <= (d1 - d0).days <= MAX_DAYS):   # ★ 坑 2：季度值在这里被挡掉
                continue
            y = d1.year
            if y not in YEARS:
                continue
            prev = out.get(y)
            # 同一年有多条 → 取申报日更新的那条
            if prev is None or x.get("filed", "") >= prev[2]:
                out[y] = (x["val"], x.get("form", ""), x.get("filed", ""))
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    print("=" * 78)
    print("从 SEC EDGAR 抓特斯拉财务数据（官方 XBRL，单位：美元）")
    print("=" * 78)

    raw_rows, table = [], {}
    for name, tags in CONCEPTS:
        # ★ 坑 1 的正确解法：**跨候选 tag 合并**，缺哪年就用下一个 tag 补哪年。
        #   只用一个 tag 会出现「2014-2017 营收全空」——因为新 tag 2018 年才开始申报。
        merged, used_tags = {}, []
        for tag in tags:
            facts, err = fetch_concept(tag)
            if err:
                print(f"  [{name}] {tag:<52} {err}")
                continue
            annual = pick_annual(facts)
            added = [y for y in annual if y not in merged]
            for y in added:
                merged[y] = annual[y]
            used_tags.append(f"{tag}(+{len(added)})")
            print(f"  [{name}] {tag:<52} 年度值 {len(annual)} 个，新增 {len(added)} 个 -> 累计 {len(merged)}/11")
            if len(merged) >= len(YEARS):
                break
        if not merged:
            print(f"  [{name}] ✗ 所有候选 tag 都没取到")
            continue
        table[name] = merged
        for y in sorted(merged):
            val, form, filed = merged[y]
            raw_rows.append({"年份": y, "指标": name, "tag": " + ".join(used_tags),
                             "金额_美元": val, "申报表": form, "申报日": filed})
        time.sleep(0.3)      # 对官方接口客气一点

    # ── 原始痕迹 ──
    with (OUT / "sec_raw_facts.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["年份", "指标", "tag", "金额_美元", "申报表", "申报日"])
        w.writeheader()
        w.writerows(sorted(raw_rows, key=lambda r: (r["年份"], r["指标"])))

    # ── 整理成宽表（百万美元）──
    cols = [n for n, _ in CONCEPTS if n in table]
    wide_rows = []
    for y in YEARS:
        row = {"年份": y}
        for c in cols:
            row[c] = round(table[c][y][0] / 1e6, 1) if y in table[c] else ""
        wide_rows.append(row)
    with (OUT / "tesla_financials.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["年份"] + cols)
        w.writeheader()
        w.writerows(wide_rows)

    print("\n" + "=" * 78)
    print(f"宽表（单位：百万美元）→ {(OUT / 'tesla_financials.csv').name}")
    print("=" * 78)
    hdr = "年份  " + "".join(f"{c:>14}" for c in cols)
    print(hdr)
    for r in wide_rows:
        print(f"{r['年份']}  " + "".join(f"{str(r[c]):>14}" for c in cols))

    print(f"\n原始取数痕迹 → {(OUT / 'sec_raw_facts.csv').name}（{len(raw_rows)} 条）")
    print("\n自检：")
    miss = [y for y in YEARS if any(y not in table.get(c, {}) for c in cols)]
    print(f"  {'✓' if not miss else '✗'} 2014-2024 十一年 × {len(cols)} 个指标，缺数据的年份：{miss or '无'}")
    if "营收" in table and "净利润" in table:
        pos = [y for y in YEARS if y in table["净利润"] and table["净利润"][y][0] > 0]
        print(f"  ✓ 净利润首次为正的年份（由官方数据算出）：{pos[0] if pos else '无'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())