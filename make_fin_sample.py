# -*- coding: utf-8 -*-
r"""
造一个「含已知缺陷」的财务报表样本，供勾稽校验 Agent 测试与评测。

为什么必须人造样本
------------------
校验型 Agent 的评测前提是**知道正确答案**。真实报表你不知道哪一格错，
所以无法算检出率和定位准确率。这里按 C01–C12 清单**逐条注入缺陷**，
并输出 ground truth 清单，评测时逐条比对。

两个版本（对应提示词 R2 双通道读取的现实分叉）
----------------------------------------------
  sample_fin.xlsx        程序生成 → **缓存值全空**，通道 B 不可用
  sample_fin_baked.xlsx  用 Excel COM 真实重算并保存 → **缓存值有值**
两种文件在真实场景里都存在（财务人发来的是后者，程序导出的是前者），
所以"通道 B 是否可用"本身就是一个必须检出的维度。

用法：python make_fin_sample.py
产出：data/fin/sample_fin.xlsx + data/fin/ground_truth.json
"""
import json
from pathlib import Path

import openpyxl
from openpyxl.styles import Font, PatternFill

OUT = Path(__file__).parent / "data" / "fin"

BOLD = Font(bold=True)
HEAD = PatternFill("solid", fgColor="DCE6F1")


def sheet_bs(wb):
    ws = wb.create_sheet("资产负债表")
    ws["A1"] = "项目"; ws["B1"] = "2024-12-31"; ws["C1"] = "2023-12-31"
    ws["A1"].font = ws["B1"].font = ws["C1"].font = BOLD
    rows = [
        ("货币资金",   5000, 4200),
        ("应收账款",   3200, 2800),
        ("存货",       2600, 2400),
    ]
    r = 2
    for name, a, b in rows:
        ws[f"A{r}"] = name; ws[f"B{r}"] = a; ws[f"C{r}"] = b; r += 1
    ws[f"A{r}"] = "流动资产合计"; ws[f"B{r}"] = "=SUM(B2:B4)"; ws[f"C{r}"] = "=SUM(C2:C4)"
    liu, r = r, r + 1

    ws[f"A{r}"] = "固定资产"; ws[f"B{r}"] = 9000; ws[f"C{r}"] = 8800
    gu, r = r, r + 1

    # ★ 缺陷 C05 + C07：资产总计**硬编码 19700**，而 流动资产合计+固定资产 = 19800
    ws[f"A{r}"] = "资产总计"; ws[f"B{r}"] = 19700; ws[f"C{r}"] = 19600
    ws[f"B{r}"].fill = PatternFill("solid", fgColor="FFF2CC")
    zc, r = r, r + 1

    r += 0
    ws[f"A{r}"] = "短期借款"; ws[f"B{r}"] = 3000; ws[f"C{r}"] = 3200
    duan, r = r, r + 1
    ws[f"A{r}"] = "应付账款"; ws[f"B{r}"] = 2400; ws[f"C{r}"] = 2100
    ying, r = r, r + 1
    ws[f"A{r}"] = "流动负债合计"; ws[f"B{r}"] = f"=SUM(B{duan}:B{ying})"; ws[f"C{r}"] = f"=SUM(C{duan}:C{ying})"
    ld, r = r, r + 1
    ws[f"A{r}"] = "长期借款"; ws[f"B{r}"] = 4000; ws[f"C{r}"] = 4200
    cq, r = r, r + 1
    ws[f"A{r}"] = "负债合计"; ws[f"B{r}"] = f"=B{ld}+B{cq}"; ws[f"C{r}"] = f"=C{ld}+C{cq}"
    fz, r = r, r + 1
    ws[f"A{r}"] = "实收资本"; ws[f"B{r}"] = 6000; ws[f"C{r}"] = 6000
    ss, r = r, r + 1
    # ★ 未分配利润故意取 4250（不是 4300），使 C01 差 50
    ws[f"A{r}"] = "未分配利润"; ws[f"B{r}"] = 4250; ws[f"C{r}"] = 4000
    wf, r = r, r + 1
    ws[f"A{r}"] = "所有者权益合计"; ws[f"B{r}"] = f"=B{ss}+B{wf}"; ws[f"C{r}"] = f"=C{ss}+C{wf}"
    qy, r = r, r + 1
    ws[f"A{r}"] = "负债和所有者权益总计"; ws[f"B{r}"] = f"=B{fz}+B{qy}"; ws[f"C{r}"] = f"=C{fz}+C{qy}"
    ws[f"A{r}"].font = BOLD
    tot = r

    # ★ 缺陷 C08：引用断链
    ws[f"A{tot+2}"] = "附注"; ws[f"A{tot+2}"].font = BOLD
    ws[f"A{tot+3}"] = "上期调整数（引用已删除的工作表）"
    ws[f"B{tot+3}"] = "=已删除表!B5"
    # ★ 缺陷 C09：跨表引用指向空白单元格
    ws[f"A{tot+4}"] = "待确认项（引用了现金流量表的空白格）"
    ws[f"B{tot+4}"] = "=现金流量表!B40"
    # ★ 缺陷 C11：单位混用
    ws[f"A{tot+5}"] = "其他应付款（单位：元）"
    ws[f"B{tot+5}"] = 350000
    return ws


def sheet_is(wb):
    ws = wb.create_sheet("利润表")
    ws["A1"] = "项目"; ws["B1"] = "2024年度"
    ws["A1"].font = ws["B1"].font = BOLD
    data = [
        ("营业收入", 30000),
        ("营业成本", 18000),
    ]
    r = 2
    for n, v in data:
        ws[f"A{r}"] = n; ws[f"B{r}"] = v; r += 1
    ws[f"A{r}"] = "毛利"; ws[f"B{r}"] = "=B2-B3"; r += 1
    ws[f"A{r}"] = "销售费用"; ws[f"B{r}"] = 3000; r += 1
    ws[f"A{r}"] = "管理费用"; ws[f"B{r}"] = 2000; r += 1
    # ★ 缺陷 C07：营业利润是**硬编码常数**，公式链里本该由毛利-费用推出
    ws[f"A{r}"] = "营业利润"; ws[f"B{r}"] = 7000
    ws[f"B{r}"].fill = PatternFill("solid", fgColor="FFF2CC")
    op, r = r, r + 1
    ws[f"A{r}"] = "所得税费用"; ws[f"B{r}"] = 1750; r += 1
    tax = r - 1
    ws[f"A{r}"] = "净利润"; ws[f"B{r}"] = f"=B{op}-B{tax}"; ws[f"A{r}"].font = BOLD
    np_ = r
    # ★ 缺陷 C06：同一科目在两张表里叫法不同（这里叫「留存收益」）
    ws[f"A{np_+2}"] = "附注：本期留存收益变动"; ws[f"A{np_+2}"].font = BOLD
    ws[f"A{np_+3}"] = "期初留存收益"; ws[f"B{np_+3}"] = 4000
    ws[f"A{np_+4}"] = "加：本期留存收益（即净利润）"; ws[f"B{np_+4}"] = f"=B{np_}"
    # ★ 缺陷 C10：本表只有 2024 年度，而资产负债表有 2023/2024 两期 —— 期间不齐
    return ws


def sheet_cf(wb):
    ws = wb.create_sheet("现金流量表")
    ws["A1"] = "项目"; ws["B1"] = "2024年度"
    ws["A1"].font = ws["B1"].font = BOLD
    ws["A2"] = "一、经营活动"; ws["A2"].font = BOLD
    ws["A3"] = "销售商品、提供劳务收到的现金"; ws["B3"] = 31000
    ws["A4"] = "购买商品、接受劳务支付的现金"; ws["B4"] = -20000
    ws["A5"] = "支付给职工以及为职工支付的现金"; ws["B5"] = -5000
    ws["A6"] = "经营活动产生的现金流量净额"; ws["B6"] = "=SUM(B3:B5)"
    ws["A8"] = "二、投资活动"; ws["A8"].font = BOLD
    ws["A9"] = "购建固定资产、无形资产支付的现金"; ws["B9"] = -2000
    ws["A10"] = "投资活动产生的现金流量净额"; ws["B10"] = "=SUM(B9:B9)"
    ws["A12"] = "三、筹资活动"; ws["A12"].font = BOLD
    ws["A13"] = "取得借款收到的现金"; ws["B13"] = 3000
    ws["A14"] = "偿还债务支付的现金"; ws["B14"] = -4000
    ws["A15"] = "筹资活动产生的现金流量净额"; ws["B15"] = "=SUM(B13:B14)"
    ws["A17"] = "四、汇率变动对现金的影响"; ws["B17"] = 0
    ws["A18"] = "五、现金及现金等价物净增加额"; ws["B18"] = "=B6+B10+B15+B17"
    ws["A19"] = "加：期初现金及现金等价物余额"; ws["B19"] = 3200
    # ★ 缺陷 C02：期末现金**硬编码 4600**，而 3200 + 净增加额(=-1000) = 2200，
    #   且与资产负债表货币资金 5000 都对不上
    ws["A20"] = "期末现金及现金等价物余额"; ws["B20"] = 4600
    ws["B20"].fill = PatternFill("solid", fgColor="FFF2CC")

    ws["A22"] = "补充资料：间接法调节"; ws["A22"].font = BOLD
    ws["A23"] = "净利润"; ws["B23"] = "=利润表!B9"
    ws["A24"] = "加：固定资产折旧"; ws["B24"] = 800
    ws["A25"] = "减：应收账款增加"; ws["B25"] = -400
    ws["A26"] = "减：存货增加"; ws["B26"] = -200
    ws["A27"] = "加：应付账款增加"; ws["B27"] = 300
    # ★ 缺陷 C03：合计写死 5750，而上面相加 = 5250+800-400-200+300 = 5750 —— 与经营净额 4800 不等
    ws["A28"] = "经营活动现金流量净额（间接法）"; ws["B28"] = "=SUM(B23:B27)"
    ws["A29"] = "直接法下的经营活动现金流量净额"; ws["B29"] = "=B6"

    # ★ 缺陷 C12：循环引用
    ws["A31"] = "待核项 A"; ws["B31"] = "=B32+100"
    ws["A32"] = "待核项 B"; ws["B32"] = "=B31-100"
    ws["A34"] = "备注：其他支出 3,000 元"; ws["A34"].font = Font(italic=True)
    return ws


def sheet_extra(wb):
    """★ 缺陷 C06：同一科目换名字的对照表"""
    ws = wb.create_sheet("科目对照")
    ws["A1"] = "本表列示的口径差异"; ws["A1"].font = BOLD
    ws["A2"] = "未分配利润（资产负债表口径）"
    ws["A3"] = "留存收益（利润表附注口径）  ← 同一科目、两个名字"
    ws["A4"] = "现金及现金等价物（现金流量表口径）  vs  货币资金（资产负债表口径）"
    return ws


GROUND_TRUTH = {
    "meta": {
        "purpose": "勾稽校验 Agent 的评测样本（含 C01-C12 已知缺陷）",
        "company": "示例科技股份有限公司（虚构）",
        "unit": "万元（★ 资产负债表末行故意混入一个「元」单位）",
        "period_bs": "2024-12-31 / 2023-12-31",
        "period_is_cf": "2024 年度（★ 与资产负债表期间不齐）",
    },
    "defects": [
        {"id": "D-C01", "check": "C01", "sev": "P0",
         "where": "资产负债表!B17", "desc": "资产负债表不平衡：资产总计 19700 vs 负债+权益 19650，差 50",
         "note": "同时暴露 C05"},
        {"id": "D-C02", "check": "C02", "sev": "P0",
         "where": "现金流量表!B20", "desc": "期末现金硬编码 4600；按 3200+净增加额(-1000)=2200，与资产负债表货币资金 5000 也不符"},
        {"id": "D-C03", "check": "C03", "sev": "P0",
         "where": "现金流量表!B28 vs B6", "desc": "间接法调节得 5750，直接法经营净额 4800，差 950"},
        {"id": "D-C04", "check": "C04", "sev": "P1",
         "where": "利润表!B2 vs 现金流量表!B3", "desc": "营业收入 30000 vs 销售收现 31000，含税还原需**增值税率**，样本未提供 → 正确行为是报「无法判定」并说明缺税率"},
        {"id": "D-C05", "check": "C05", "sev": "P0",
         "where": "资产负债表!B17", "desc": "资产总计 19700 ≠ 流动资产合计 10800 + 固定资产 9000 = 19800，差 100"},
        {"id": "D-C06", "check": "C06", "sev": "P1",
         "where": "资产负债表!A15 vs 利润表附注 / 科目对照表",
         "desc": "未分配利润 / 留存收益 同一科目两个名字"},
        {"id": "D-C07", "check": "C07", "sev": "P1",
         "where": "利润表!B7、资产负债表!B17", "desc": "营业利润 7000、资产总计 19700 均为硬编码常数，位于公式链中"},
        {"id": "D-C08", "check": "C08", "sev": "P0",
         "where": "资产负债表!B19", "desc": "公式引用已删除的工作表（=已删除表!B5）"},
        {"id": "D-C09", "check": "C09", "sev": "P2",
         "where": "资产负债表!B20", "desc": "跨表引用指向现金流量表的空白单元格（B40）"},
        {"id": "D-C10", "check": "C10", "sev": "P1",
         "where": "全表", "desc": "资产负债表两期（2023/2024），利润表与现金流量表只有一期 → 期间不齐"},
        {"id": "D-C11", "check": "C11", "sev": "P1",
         "where": "资产负债表!A21/B21", "desc": "同一列内单位混用：其余为万元，此行标注「元」且值为 350000"},
        {"id": "D-C12", "check": "C12", "sev": "P0",
         "where": "现金流量表!B31/B32", "desc": "B31=B32+100、B32=B31-100 构成循环引用"},
    ],
    "channel_b_trap": {
        "sample_fin.xlsx": "程序生成 → data_only=True 全为 None，通道 B 不可用",
        "sample_fin_baked.xlsx": "经 Excel 重算保存 → 通道 B 有缓存值",
        "期望行为": "Agent 必须**检出并声明**通道 B 不可用，而不是把 None 当成 0 继续算",
    },
}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    sheet_bs(wb); sheet_is(wb); sheet_cf(wb); sheet_extra(wb)
    dst = OUT / "sample_fin.xlsx"
    wb.save(dst)
    (OUT / "ground_truth.json").write_text(
        json.dumps(GROUND_TRUTH, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"写出 {dst}（{dst.stat().st_size/1024:.1f} KB）")
    print("工作表：", wb.sheetnames)
    print(f"写出 {OUT / 'ground_truth.json'}（{len(GROUND_TRUTH['defects'])} 条已知缺陷）")
    print("\n注入的缺陷：")
    for d in GROUND_TRUTH["defects"]:
        print(f"  [{d['sev']}] {d['check']:<4} {d['where']:<28} {d['desc'][:44]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())