# -*- coding: utf-8 -*-
r"""
前端机械校验（不调 API、不起服务）：把 craft-floor 里能被机器判的部分做成断言。

★ 调色板**从 HTML 的 :root 里读**，不在校验器里写死 —— 否则改了 HTML 校验器还在测旧颜色，
  变成"改了不生效、错了不报警"的假检查（这个坑踩过）。
"""
import re
import sys
from pathlib import Path

HTML = Path(__file__).resolve().parent.parent / "static" / "index.html"
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'[OK]' if ok else '[FAIL]'} {name}")
    if detail:
        print(f"      {detail}")


def lum(h):
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))

    def f(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def ratio(a, b):
    la, lb = lum(a), lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def main() -> int:
    html = HTML.read_text(encoding="utf-8")
    print("=" * 74)
    print(f"前端机械校验：{HTML.name}（{len(html)} 字符）")
    print("=" * 74)

    # ---------- 1. 对比度 ----------
    print("\n--- 1. 对比度（WCAG AA）---")
    root = re.search(r":root\s*\{(.*?)\}", html, re.S)
    if not root:
        check("能找到 :root 调色板", False)
        return 1
    P = {m.group(1): m.group(2)
         for m in re.finditer(r"--([a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{3,8})", root.group(1))}
    print(f"      从 HTML 读到 {len(P)} 个颜色变量")

    pairs = [
        ("正文 ink / 白底", "ink", "surface", 4.5),
        ("次级 ink-2 / 白底", "ink-2", "surface", 4.5),
        ("弱化 ink-3 / 白底", "ink-3", "surface", 4.5),
        ("弱化 ink-3 / 侧栏底", "ink-3", "surface-2", 4.5),
        ("次级 ink-2 / 侧栏底", "ink-2", "surface-2", 4.5),
        ("按钮白字 / 强调底", "#ffffff", "accent", 4.5),
        ("强调文字 / 白底", "accent-ink", "surface", 4.5),
        ("强调文字 / accent-weak 底", "accent-ink", "accent-weak", 4.5),
        ("通过色 ok / ok-weak 底", "ok", "ok-weak", 4.5),
        ("提示色 warn / warn-weak 底", "warn", "warn-weak", 4.5),
        ("危险色 danger / danger-weak 底", "danger", "danger-weak", 4.5),
        ("禁用按钮文字 ink-3 / surface-3", "ink-3", "surface-3", 4.5),
        ("状态点 ok / 侧栏底", "ok", "surface-2", 3.0),
    ]
    miss = sorted({k for _, f, b, _ in pairs for k in (f, b) if not k.startswith("#") and k not in P})
    check("调色板变量齐全", not miss, f"缺 {miss}" if miss else "")
    worst, wname = 99.0, ""
    for name, fk, bk, need in pairs:
        fg = fk if fk.startswith("#") else P[fk]
        bg = bk if bk.startswith("#") else P[bk]
        r = ratio(fg, bg)
        if r < worst:
            worst, wname = r, name
        check(f"{name}  {r:.2f}:1（需 ≥{need}）", r >= need, "" if r >= need else f"★ 差 {need - r:.2f}")

    # ---------- 2. JS 引用的 id ----------
    print("\n--- 2. JS 引用的 id 是否都存在 ---")
    declared = set(re.findall(r'\bid="([^"]+)"', html))
    referenced = set(re.findall(r"\$\('([^']+)'\)", html))
    dangling = sorted(referenced - declared)
    check(f"{len(referenced)} 个引用全部有对应元素", not dangling, f"悬空：{dangling}" if dangling else "")

    # ---------- 3. craft-floor 禁令 ----------
    print("\n--- 3. craft-floor 禁令 ---")
    # ★ 只扫「界面上会显示出来的文本」：把 <style>、<script> 和 HTML 注释都剥掉。
    #   为什么：craft-floor 禁的是"用 Unicode 符号**冒充图标系统**"（例如旧版的 logo 用了齿轮符），
    #   而代码注释里写个箭头或星号只是记号，不是图标。第一版没剥注释，误报了两处。
    visible = re.sub(r"<style.*?</style>|<script.*?</script>|<!--.*?-->", "", html, flags=re.S)
    bans = [
        ("渐变文字（全文件样式）", r"background-clip\s*:\s*text"),
        ("粗色 border-left/right（>1px）", r"border-(?:left|right)\s*:\s*(?!1px)(?!0)\d+(?:\.\d+)?px"),
        ("硬阴影 Npx Npx 0", r"box-shadow\s*:\s*-?\d+px\s+-?\d+px\s+0(?:\s|;|$)"),
        ("backdrop-filter（玻璃效果）", r"backdrop-filter"),
    ]
    for label, pat in bans:
        hits = re.findall(pat, html if "全文件" in label else visible)
        check(f"无「{label}」", not hits, f"命中 {hits[:4]}" if hits else "")

    glyph = r"[\u2190-\u21FF\u2600-\u27BF\u2B00-\u2BFF\uFE0F]|&#x1F"
    hits = re.findall(glyph, visible)
    check("界面上没有用 Unicode 符号冒充图标", not hits,
          f"命中 {hits[:4]}" if hits else "（注释里的记号不计）")
    check("品牌标记是自绘 SVG", '<svg class="mark"' in html)

    # ---------- 4. 示例问题必须对得上真实数据 ----------
    print("\n--- 4. 示例问题 ---")
    chips = re.findall(r'<button class="chip"[^>]*data-q="([^"]+)"', html)
    check(f"{len(chips)} 个示例都带 data-q", len(chips) >= 6, f"共 {len(chips)} 个")
    real = ["data/tesla/tesla_financials.csv", "data/fin/sample_fin.xlsx",
            "data/sales.csv", "data/hard/orders_dirty.csv"]
    bad = [q for q in chips if not any(r in q for r in real) and "123*456" not in q]
    check("每个示例都指向真实存在的文件", not bad, f"悬空引用：{bad}" if bad else "（123*456 是刻意留的常识题）")

    # ---------- 5. 状态与交互面 ----------
    print("\n--- 5. 状态与交互面 ---")
    for sid, label in [("st-empty", "空状态"), ("st-loading", "加载"), ("st-answer", "命中"), ("st-error", "报错")]:
        check(f"有{label}容器 #{sid}", f'id="{sid}"' in html)
    for sel, label in [("::selection", "文本选区"), ("caret-color", "光标颜色"),
                       ("focus-visible", "键盘焦点环"), ("scrollbar-color", "滚动条"),
                       ("tabular-nums", "表格数字"), ("prefers-reduced-motion", "减弱动效")]:
        check(f"定制了{label}", sel in html)
    check("加载用骨架屏而非转圈", "sk-l" in html and "spinner" not in html)
    check("能渲染 markdown 表格（财务题材必备）", 'class="tbl"' in html and "isSep" in html)

    n_ok = sum(1 for r in results if r)
    print("\n" + "=" * 74)
    print(f"{n_ok}/{len(results)} 项通过；最低对比度 {worst:.2f}:1（{wname}）")
    print("=" * 74)
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())