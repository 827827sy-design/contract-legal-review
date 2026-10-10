# -*- coding: utf-8 -*-
"""render_report.py — 用固定模板渲染单文件 HTML 审查报告（第八步）。

输入：
  <task_dir>/contract.json        合同结构化原文
  <task_dir>/verified_review.json validate_review.py 校验后的风险结果
  assets/report_template.html     固定模板（本脚本同目录的 ../assets/）

关键设计（对应需求 §6 原文定位技术要求）：
- 所有高亮 span 由 Python 根据 verified span 预拆分：合同文本被切成原子片段，
  每个片段带 class="mk mk-<severity> m-<risk_id>-<ev_i> ..."，
  JS 只按 class 增删 mk-current/mk-active，不做任何字符串搜索，
  因此不存在 Python/JS 字符索引不一致问题。
- 渲染前对每条 span 做二次确定性校验：full_text[s:e] 与 quote 规范化一致，
  不一致则降级为「定位失败」，宁可不高亮也不高亮错位置。
- 重叠 span：以所有 span 端点为边界切分，一个片段可携带多个 m-<rid>-<i> class；
  下划线颜色取该片段最高严重级。
- 合同文字全部经 HTML 转义，绝不作为 HTML/脚本插入。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (force_utf8_stdio, read_json, write_json, now_iso, merge_log,
                    load_contract, norm_law_text, esc, json_for_script,
                    SEV_ORDER, SEV_LABEL)

force_utf8_stdio()

SEV_RANK = {"high": 0, "medium": 1, "low": 2, "review_required": 3}


def dom_sev(sevs):
    return sorted(sevs, key=lambda s: SEV_RANK.get(s, 9))[0]


class SegmentSplitter:
    """把 (start,end) span 集合切成原子片段。"""

    def __init__(self, spans):
        # spans: list of (s, e, rid, ev_i, sev)
        self.spans = [sp for sp in spans if sp[1] > sp[0]]
        pts = sorted({p for sp in self.spans for p in (sp[0], sp[1])})
        self.points = pts

    def segments(self, lo, hi):
        """返回 [(seg_start, seg_end, [span,...])] 覆盖 [lo,hi)。"""
        if not self.spans:
            return [(lo, hi, [])]
        pts = [lo] + [p for p in self.points if lo < p < hi] + [hi]
        pts = sorted(set(pts))
        out = []
        for a, b in zip(pts, pts[1:]):
            if b <= a:
                continue
            cover = [sp for sp in self.spans if sp[0] <= a and b <= sp[1]]
            out.append((a, b, cover))
        return out


def render_text_with_marks(text, base, splitter):
    """text 是 full_text 中 [base, base+len(text)) 的内容。返回安全 HTML。"""
    segs = splitter.segments(base, base + len(text))
    parts = []
    for a, b, cover in segs:
        chunk = esc(text[a - base:b - base])
        if not chunk:
            continue
        if not cover:
            parts.append(chunk)
            continue
        rids = sorted({(sp[2], sp[3]) for sp in cover})
        sevs = {sp[4] for sp in cover}
        cls = ["mk", "mk-" + dom_sev(sevs)]
        for rid, i in rids:
            cls.append(f"m-{rid}-{i}")
        parts.append(f'<span class="{" ".join(cls)}">{chunk}</span>')
    return "".join(parts)


def render_block(block, base, splitter):
    bid = block["block_id"]
    kind = block["kind"]
    text = block["text"]
    no = f'<span class="blkno">{esc(bid)}</span>'
    if kind == "table" and "|" in text and "\n" in text:
        rows_html = []
        off = base
        for r, row in enumerate(text.split("\n")):
            cells_html = []
            coff = off
            cells = row.split(" | ")
            for c, cell in enumerate(cells):
                cell_html = render_text_with_marks(cell, coff, splitter)
                tag = "td" if r > 0 else "th"
                cells_html.append(f"<{tag}>{cell_html or '&nbsp;'}</{tag}>")
                coff += len(cell) + (3 if c < len(cells) - 1 else 0)
            rows_html.append("<tr>" + "".join(cells_html) + "</tr>")
            off += len(row) + 1
        return f'{no}<table class="blk blk-table">{"".join(rows_html)}</table>'
    cls = "blk blk-heading" if kind == "heading" else "blk"
    inner = render_text_with_marks(text, base, splitter)
    return f'<div class="{cls}" data-bid="{esc(bid)}">{no}{inner}</div>'


def render_contract(contract, spans_all):
    splitter = SegmentSplitter(spans_all)
    blocks_html = []
    title = contract.get("title_guess", "")
    if title:
        blocks_html.append(f'<div class="doc-title">{esc(title)}</div>')
    offsets = contract["_offsets"]
    for b in contract["blocks"]:
        s, _ = offsets[b["block_id"]]
        blocks_html.append(render_block(b, s, splitter))
    return "".join(blocks_html)


def render_print_summary(review):
    rows = []
    for r in review["risks"]:
        basis = "；".join(
            f"{b['law_name']}{b['article_no']}[{b['status']}]" for b in r["legal_basis"]
        ) or "—"
        rows.append(
            f"<tr><td>{esc(r['risk_id'])}</td><td>{esc(SEV_LABEL.get(r['severity'], r['severity']))}</td>"
            f"<td>{esc(r['category'])}</td><td>{esc(r['title'])}</td>"
            f"<td>{esc(r['conclusion'])}</td><td>{esc(basis)}</td>"
            f"<td>{esc(r['recommendation'])}</td></tr>"
        )
    return (
        "<h2>风险清单（打印版）</h2>"
        "<table><tr><th>编号</th><th>等级</th><th>类型</th><th>风险</th><th>判断</th>"
        "<th>法律依据</th><th>建议</th></tr>" + "".join(rows) + "</table>"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-dir", required=True)
    args = ap.parse_args()
    task_dir = Path(args.task_dir)

    contract = load_contract(task_dir)
    review = read_json(task_dir / "verified_review.json")
    tpl_path = Path(__file__).resolve().parent.parent / "assets" / "report_template.html"
    template = tpl_path.read_text(encoding="utf-8")

    full = contract["_full_text"]
    offsets = contract["_offsets"]

    # ---- 渲染前二次校验 + 收集 span ----
    spans_all = []
    render_issues = []
    for r in review["risks"]:
        for i, ev in enumerate(r["evidence"]):
            ev["i"] = i
            ev["has_span"] = False
            ev["pos_desc"] = ""
            if ev.get("span"):
                s, e = ev["span"]
                actual = full[s:e]
                quote = ev.get("quote", "")
                ok = (norm_law_text(actual) == norm_law_text(quote)) if quote else True
                if ok and 0 <= s < e <= len(full):
                    ev["has_span"] = True
                    bid = ev.get("resolved_block_id") or ""
                    # 找块序号（第几个块）便于人读
                    bidx = next((n for n, b in enumerate(contract["blocks"], 1)
                                 if b["block_id"] == bid), None)
                    ev["pos_desc"] = (f"块 {bid}" + (f"（第 {bidx} 段）" if bidx else "")
                                      + ("，表格" if contract["_block_by_id"].get(bid, {}).get("kind") == "table" else ""))
                    spans_all.append((s, e, r["risk_id"], i, r["severity"]))
                else:
                    ev["note"] = ("渲染校验失败：span 与原文不一致，已降级为定位失败"
                                  + (f"（原 note: {ev.get('note','')}）" if ev.get("note") else ""))
                    render_issues.append(f"{r['risk_id']} 证据{i+1} span 校验失败")
            if ev.get("no_text"):
                ev["pos_desc"] = ev.get("note") or "该问题无直接原文"
                if ev.get("span"):
                    s, e = ev["span"]
                    if 0 <= s < e <= len(full):
                        ev["has_span"] = True
                        spans_all.append((s, e, r["risk_id"], i, r["severity"]))

    # ---- DATA（供 JS 使用；不含合同原文，原文已在 DOM） ----
    data_risks = []
    cats_used = []
    for r in review["risks"]:
        if r["category"] not in cats_used:
            cats_used.append(r["category"])
        data_risks.append({
            "risk_id": r["risk_id"], "title": r["title"], "category": r["category"],
            "severity": r["severity"], "conclusion": r["conclusion"],
            "explanation": r["explanation"], "recommendation": r["recommendation"],
            "proposed_clause": r.get("proposed_clause", ""),
            "manual_checks": r.get("manual_checks", []),
            "scope_note": r.get("scope_note", ""),
            "verification_status": r.get("verification_status", {}),
            "evidence": [{
                "i": ev["i"], "quote": ev.get("quote", ""), "has_span": ev["has_span"],
                "no_text": ev.get("no_text", False), "pos_desc": ev.get("pos_desc", ""),
                "note": ev.get("note", ""), "block_id": ev.get("block_id", ""),
            } for ev in r["evidence"]],
            "legal_basis": [{
                "law_id": b.get("law_id", ""), "law_name": b.get("law_name", b.get("law_id", "")),
                "version": b.get("version", ""), "article_no": b.get("article_no", ""),
                "status": b.get("status", ""), "note": b.get("note", ""),
                "kb_text": b.get("kb_text", ""), "cited_text": b.get("cited_text", ""),
            } for b in r["legal_basis"]],
        })

    meta = review.get("review_meta", {})
    cinfo = review.get("contract", {})
    data = {
        "meta": {
            "source_name": cinfo.get("source_name", ""),
            "contract_type": meta.get("contract_type", ""),
            "reviewed_at": meta.get("reviewed_at", now_iso()),
            "parse_status": cinfo.get("parse_status", ""),
            "law_scope": meta.get("law_scope", []),
            "scope_limitation": meta.get("scope_limitation", ""),
            "categories_used": cats_used,
        },
        "risks": data_risks,
    }

    # ---- banners ----
    banners = []
    ps = cinfo.get("parse_status", "")
    if ps == "partial":
        notes = "；".join(contract.get("parse_notes", []))
        banners.append(f'<div class="banner warn">⚠ 文件解析不完整：{esc(notes)}。'
                       f'本报告仅覆盖已成功提取的文本，未提取部分（如扫描页）可能包含未审查的风险。</div>')
    elif ps == "failed":
        banners.append('<div class="banner err">✘ 文件解析失败，本报告不包含有效审查内容。请检查文件或转换格式后重试。</div>')
    for note in meta.get("kb_notes", []):
        banners.append(f'<div class="banner err">⚠ 法律知识库问题：{esc(note)}。'
                       f'在知识库完整之前，不得声称已完成全面法律审查。</div>')
    stats = meta.get("stats", {})
    if stats.get("basis_not_found") or stats.get("basis_mismatch"):
        banners.append(f'<div class="banner warn">⚠ 有 {stats.get("basis_not_found",0)} 条引用法条不存在、'
                       f'{stats.get("basis_mismatch",0)} 条引用条文与知识库不一致，已在对应风险卡片中标红，'
                       f'相关结论不得直接采信。</div>')
    if render_issues:
        banners.append(f'<div class="banner warn">⚠ {len(render_issues)} 条证据在渲染前二次校验中定位失败，'
                       f'已降级显示为“未能定位”，不会高亮到错误文字。</div>')
    banners.append('<div class="banner info">本报告由 AI 辅助生成，属于风险提示与核查线索，不构成法律意见。'
                   '涉及合同效力认定、签署或争议处理，请咨询执业律师并以人工核实为准。</div>')

    title = contract.get("title_guess") or f"合同审查报告 — {cinfo.get('source_name','')}"
    html = (template
            .replace("__TITLE__", esc(title))
            .replace("__BANNERS_HTML__", "".join(banners))
            .replace("__CONTRACT_HTML__", render_contract(contract, spans_all))
            .replace("__PRINT_SUMMARY_HTML__", render_print_summary(review))
            .replace("__DATA_JSON__", json_for_script(data)))

    out = task_dir / "contract_review.html"
    out.write_text(html, encoding="utf-8")

    # 自校验：无外链资源
    checks = {"no_cdn": True, "no_external_src": True, "data_json_valid": True}
    low = html.lower()
    for bad in ("http://", "https://", "//cdn", "src=\"http"):
        if bad in low:
            # 允许出现在纯文本内容里（如合同原文中的网址），但不能出现在资源标签中
            import re as _re
            if _re.search(r'<(script|link|img|iframe)[^>]*(src|href)\s*=\s*["\']?(https?:)?//', low):
                checks["no_external_src"] = False
    try:
        json.loads(json_for_script(data).replace("<\\/", "</"))
    except Exception:
        checks["data_json_valid"] = False

    merge_log(task_dir, "render_report", {
        "output": str(out), "html_bytes": len(html.encode("utf-8")),
        "span_count": len(spans_all), "render_issues": render_issues, "checks": checks,
    })
    print(f"[OK] 报告已生成: {out} ({len(html)//1024} KB)")
    print(f"  高亮片段: {len(spans_all)}  渲染校验问题: {len(render_issues)}")
    print(f"  单文件校验: {checks}")
    if not all(checks.values()):
        print("  [WARN] 单文件/离线校验未全部通过，请检查")
        sys.exit(3)


if __name__ == "__main__":
    main()
