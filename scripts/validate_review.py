# -*- coding: utf-8 -*-
"""validate_review.py — 审查结果自动校验（第七步）。

输入：
  <task_dir>/contract.json     （extract_contract.py 产出）
  <task_dir>/review_draft.json  （模型产出的原始风险草稿）
  law_index/*.json              （法律知识库）

职责（全部确定性、可复现）：
  1. 法条校验：legal_basis 每条 (law_id, article_no) 必须存在于知识库；
     若草稿带了 text，则与知识库条文做规范化比对，不一致标记 mismatch。
  2. 证据校验：evidence 每条 (block_id, quote) 必须在合同原文中定位；
     用 locate_quote 解析出精确 span（处理换行/空白/重复出现）。
     - 定位成功 -> verified, span 落库
     - block_id 指定但 quote 不在该块 -> 尝试全文定位并标注 block_mismatch
     - 缺失条款无原文 -> no_text=true，定位到 suggested block 或合同末尾
  3. 结构校验：category/severity 合法；risk_id 唯一；conclusion/explanation 非空。
  4. 去重：同 category+同 evidence span 集合+相似 title 的重复风险合并，
     但保留「不同风险引用同一条款」的关系（不同 category/severity 不合并）。
  5. 生成 verification_status 汇总；输出 verified_review.json。

不做法律判断，只做「引用是否真实、定位是否准确、结构是否合法」的机械校验。
模型若编造法条或错误定位，这里会被标记为 unverifiable / not_found，
渲染阶段据此显示「定位失败」「法条待核实」，绝不显示为已核实结论。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (force_utf8_stdio, read_json, write_json, now_iso, merge_log,
                    load_contract, locate_quote, norm_law_text, build_norm_map,
                    CATEGORIES, SEVERITIES, SEV_ORDER)

force_utf8_stdio()


def load_law_index(index_dir: Path) -> dict:
    idx = {}
    for p in sorted(Path(index_dir).glob("*.json")):
        rec = read_json(p)
        by_no = {a["article_no"]: a for a in rec["articles"]}
        idx[rec["law_id"]] = {"meta": rec, "by_no": by_no}
    return idx


def validate_legal_basis(basis, law_index, kb_complete: dict):
    """basis: {law_id, article_no, text?} -> 带校验结果的 dict。"""
    out = {
        "law_id": basis.get("law_id", ""),
        "article_no": basis.get("article_no", ""),
        "law_name": "",
        "version": "",
        "kb_text": "",
        "cited_text": basis.get("text", ""),
        "exists": False,
        "text_match": None,   # None=未提供引用文本; True/False
        "status": "unverified",
        "note": "",
    }
    lid = out["law_id"]
    no = out["article_no"]
    if lid not in law_index:
        out["status"] = "not_found"
        out["note"] = f"知识库中无此法律 law_id={lid!r}（可用: {', '.join(law_index)}）"
        return out
    law = law_index[lid]
    out["law_name"] = law["meta"]["law_name"]
    out["version"] = law["meta"]["version"]
    art = law["by_no"].get(no)
    if not art:
        out["status"] = "not_found"
        out["note"] = f"{law['meta']['law_name']} 中不存在条号 {no!r}"
        return out
    out["exists"] = True
    out["kb_text"] = art["text"]
    if out["cited_text"]:
        a = norm_law_text(out["cited_text"])
        b = norm_law_text(art["text"])
        if a == b:
            out["text_match"] = True
            out["status"] = "verified"
        elif a and a in b:
            out["text_match"] = True
            out["status"] = "verified"
            out["note"] = "引用为条文节选，已确认属于该条"
        else:
            out["text_match"] = False
            out["status"] = "mismatch"
            out["note"] = "引用文本与知识库该条号原文不一致（可能张冠李戴或编造）"
    else:
        out["status"] = "verified"
        out["note"] = "未附引用文本，条号存在，已回填知识库原文"
    # 知识库完整性提示
    if not kb_complete.get(lid, True):
        out["status"] = "kb_incomplete"
        out["note"] = (out["note"] + "；知识库该法律存在缺失，不能据此声称全面审查").strip("；")
    return out


def validate_evidence(ev, contract):
    """ev: {block_id?, quote?, occurrence?, no_text?, suggested_block_id?} -> 带 span 的结果。"""
    full = contract["_full_text"]
    offsets = contract["_offsets"]
    block_ids = set(offsets.keys())
    out = {
        "block_id": ev.get("block_id", ""),
        "quote": ev.get("quote", ""),
        "occurrence": ev.get("occurrence", 1),
        "no_text": bool(ev.get("no_text", False)),
        "span": None,
        "resolved_block_id": "",
        "note": "",
        "verified": False,
    }

    # 缺失条款：无直接原文
    if out["no_text"]:
        sug = ev.get("suggested_block_id", "")
        if sug and sug in block_ids:
            s, e = offsets[sug]
            out["span"] = [s, e]
            out["resolved_block_id"] = sug
            out["note"] = "该问题无直接原文（缺失条款），定位到建议插入位置"
            out["verified"] = True
        elif ev.get("locate_at_end"):
            # 合同末尾
            last = contract["blocks"][-1]["block_id"] if contract["blocks"] else ""
            if last:
                s, e = offsets[last]
                out["span"] = [s, e]
                out["resolved_block_id"] = last
            out["note"] = "该问题无直接原文（缺失条款），建议在合同中补充相应条款"
            out["verified"] = True
        else:
            out["note"] = "该问题无直接原文（缺失条款）"
            out["verified"] = True  # 缺失条款本就无原文，属正常
        return out

    quote = out["quote"]
    if not quote:
        out["note"] = "证据缺少 quote 且未标记 no_text，无法定位"
        return out

    bid = out["block_id"]
    # 优先在指定 block 内定位
    if bid and bid in block_ids:
        s0, e0 = offsets[bid]
        s, e, note = locate_quote(full, quote, out["occurrence"], s0, e0)
        if s is not None:
            out["span"] = [s, e]
            out["resolved_block_id"] = bid
            out["note"] = f"块内定位成功({note})"
            out["verified"] = True
            return out
        # 块内失败 -> 全文定位
        s, e, note = locate_quote(full, quote, out["occurrence"])
        if s is not None:
            out["span"] = [s, e]
            # 找 span 落在哪个 block
            rb = ""
            for b, (bs, be) in offsets.items():
                if bs <= s < be:
                    rb = b
                    break
            out["resolved_block_id"] = rb
            out["note"] = f"指定块 {bid} 内未找到，已全文定位({note})"
            out["verified"] = True
            return out
        out["note"] = f"quote 未在块 {bid} 及全文中定位到：{note}"
        return out

    # 未指定 block -> 全文定位
    s, e, note = locate_quote(full, quote, out["occurrence"])
    if s is not None:
        out["span"] = [s, e]
        rb = ""
        for b, (bs, be) in offsets.items():
            if bs <= s < be:
                rb = b
                break
        out["resolved_block_id"] = rb
        out["note"] = f"全文定位成功({note})"
        out["verified"] = True
        return out
    out["note"] = f"quote 未在合同全文中定位到：{note}"
    return out


def _norm_title(t):
    """标题归一化：去空白与标点，用于判定是否同一风险。"""
    import re
    return re.sub(r"[\s，。、；：（）()【】\u3000]+", "", t or "")


def risk_signature(r):
    """完全重复的风险才合并：分类 + 标题 + 证据span集合 + 法律依据 均相同。

    纳入 title/conclusion，以保留「不同风险引用同一条款」的关系——
    例如"缺工作时间条款"与"缺劳动保护条款"同为条款缺失、同引第十七条、
    同建议插入位置，但属不同缺失事项，不得合并（对应需求 §3 第七步）。
    """
    spans = tuple(sorted(tuple(e["span"]) for e in r["evidence"] if e.get("span")))
    basis = tuple(sorted((b["law_id"], b["article_no"]) for b in r["legal_basis"]))
    return (r["category"], r.get('risk_source','legal'), r.get('preference_id',''), r.get('edit_plan',{}).get('plan_id',''), _norm_title(r["title"]), _norm_title(r["conclusion"]), spans, basis)


def resolve_index_dir(p: str) -> Path:
    """相对 CWD 找不到时，回落到 skill 根目录下的 law_index。"""
    cand = Path(p)
    if cand.exists():
        return cand
    fallback = Path(__file__).resolve().parent.parent / p
    if fallback.exists():
        return fallback
    fallback2 = Path(__file__).resolve().parent.parent / "law_index"
    if fallback2.exists():
        return fallback2
    return cand


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-dir", required=True)
    ap.add_argument("--index-dir", required=True)
    ap.add_argument("--draft", default="review_draft.json")
    ap.add_argument("--out", default="verified_review.json")
    args = ap.parse_args()

    task_dir = Path(args.task_dir)
    contract = load_contract(task_dir)
    draft = read_json(task_dir / args.draft)
    if isinstance(draft,list):
        draft={'risks':draft}
    if not isinstance(draft,dict) or not isinstance(draft.get('risks',[]),list):
        raise ValueError('风险草稿格式不正确。')
    law_index = load_law_index(resolve_index_dir(args.index_dir))

    # 知识库完整性
    kb_complete = {}
    kb_notes = []
    for lid, law in law_index.items():
        meta = law["meta"]
        expected_count={'minfadian':1260,'laodonghetongfa':98,'gongsifa':266}.get(lid)
        complete = expected_count is not None and len(law['by_no'])==meta.get('article_count')==expected_count and {a.get('no') for a in meta['articles']}==set(range(1,expected_count+1))
        kb_complete[lid] = complete
        if not complete:
            kb_notes.append(f"{meta['law_name']} 索引不完整")
    if not law_index:
        kb_notes.append("法律知识库为空，无法进行任何法律引用校验")
    for expected in {'minfadian','laodonghetongfa','gongsifa'}-set(law_index):
        kb_complete[expected]=False
        kb_notes.append(f'法律知识库缺少 {expected}')

    risks = draft.get("risks", draft if isinstance(draft, list) else [])
    verified_risks = []
    stats = {
        "total": len(risks), "basis_not_found": 0, "basis_mismatch": 0,
        "evidence_unverified": 0, "struct_errors": 0, "merged": 0,
        "kb_complete": kb_complete,
    }
    issues = []

    for i, r in enumerate(risks):
        rid = r.get("risk_id") or f"R{i+1:03d}"
        cat = r.get("category", "")
        sev = r.get("severity", "")
        vr = {
            "risk_id": rid,
            "title": r.get("title", "").strip(),
            "category": cat if cat in CATEGORIES else "待核实事项",
            "severity": sev if sev in SEVERITIES else "review_required",
            "conclusion": r.get("conclusion", "").strip(),
            "explanation": r.get("explanation", "").strip(),
            "recommendation": r.get("recommendation", "").strip(),
            "proposed_clause": r.get("proposed_clause", ""),
            "manual_checks": r.get("manual_checks", []),
            "scope_note": r.get("scope_note", ""),
            "evidence": [],
            "legal_basis": [],
            "verification_status": {},
            "risk_source":r.get('risk_source','legal'),
            "preference_id":r.get('preference_id',''),
            "objective_legal_conclusion":r.get('objective_legal_conclusion',''),
            "edit":None,
        }
        if vr['risk_source'] not in {'legal','company_policy','negotiation','experience'}:
            vr['risk_source']='experience'
            issues.append(f'{rid}: 未知风险来源，需人工核实')
            stats['struct_errors']+=1
        if vr['risk_source']!='legal' and vr['category']=='法律合规风险':
            vr['category']='待核实事项'
            issues.append(f'{rid}: 企业偏好不能直接作为违法依据，已标为待核实')
            stats['struct_errors']+=1
        if vr['risk_source']!='legal' and '违法' in vr['conclusion']:
            vr['category']='待核实事项'
            issues.append(f'{rid}: 偏好来源的违法表述需独立法律核实')
            stats['struct_errors']+=1
        # 结构校验
        if cat not in CATEGORIES:
            issues.append(f"{rid}: 非法 category {cat!r}，已归为待核实事项")
            stats["struct_errors"] += 1
        if sev not in SEVERITIES:
            issues.append(f"{rid}: 非法 severity {sev!r}，已归为 review_required")
            stats["struct_errors"] += 1
        if not vr["title"]:
            issues.append(f"{rid}: 缺少 title")
            stats["struct_errors"] += 1
        if not vr["conclusion"]:
            issues.append(f"{rid}: 缺少 conclusion")
            stats["struct_errors"] += 1

        # 证据校验
        ev_list = r.get("evidence", [])
        if not isinstance(ev_list, list):
            ev_list = [ev_list] if ev_list else []
        for ev in ev_list:
            if not isinstance(ev, dict):
                ev = {"quote": str(ev)}
            ve = validate_evidence(ev, contract)
            if not ve["verified"]:
                stats["evidence_unverified"] += 1
            vr["evidence"].append(ve)

        if isinstance(r.get('edit'),dict):
            from revision_core import nodes_for
            edit=dict(r['edit']);edit['verified']=False
            node=next((n for n in nodes_for(contract) if n['node_id']==edit.get('node_id')),None)
            start,end=edit.get('start'),edit.get('end')
            if edit.get('kind')=='insert_clause':
                group=[n for n in nodes_for(contract) if node and n['block_id']==node['block_id']]
                edit['verified']=bool(node and group[-1]['node_id']==node['node_id'])
            elif edit.get('kind') in {'partial','replace'} and node and node['editable'] and type(start)is int and type(end)is int and 0<=start<=end<=len(node['text']):
                edit['verified']=node['text'][start:end]==edit.get('expected_text')
                if edit['kind']=='replace' and (start!=0 or end!=len(node['text'])):edit['verified']=False
            if not edit['verified']:issues.append(f'{rid}: 建议修改位置未通过核验，禁止自动应用')
            vr['edit']=edit

        # 法条校验
        basis_list = r.get("legal_basis", [])
        if not isinstance(basis_list, list):
            basis_list = [basis_list] if basis_list else []
        for b in basis_list:
            if not isinstance(b, dict):
                continue
            vb = validate_legal_basis(b, law_index, kb_complete)
            if vb["status"] == "not_found":
                stats["basis_not_found"] += 1
                issues.append(f"{rid}: 法条不存在 {vb['law_id']}:{vb['article_no']} — {vb['note']}")
            elif vb["status"] == "mismatch":
                stats["basis_mismatch"] += 1
                issues.append(f"{rid}: 法条文本不一致 {vb['law_id']}:{vb['article_no']}")
            vr["legal_basis"].append(vb)

        # verification_status 汇总
        all_basis_ok = all(b["status"] in ("verified",) for b in vr["legal_basis"]) if vr["legal_basis"] else True
        any_basis_bad = any(b["status"] in ("not_found", "mismatch", "kb_incomplete") for b in vr["legal_basis"])
        all_ev_ok = all(e["verified"] for e in vr["evidence"]) if vr["evidence"] else True
        if vr["category"] == "待核实事项" or sev == "review_required":
            vstat = "review_required"
        elif any_basis_bad:
            vstat = "basis_unverified"
        elif not all_ev_ok:
            vstat = "evidence_unverified"
        elif all_basis_ok and all_ev_ok:
            vstat = "verified"
        else:
            vstat = "partial"
        vr["verification_status"] = {
            "overall": vstat,
            "basis_ok": all_basis_ok and not any_basis_bad,
            "evidence_ok": all_ev_ok,
            "has_legal_basis": bool(vr["legal_basis"]),
            "has_evidence": bool(vr["evidence"]),
        }
        from plan_quality import evaluate_plan,legacy_plan
        raw_plan=dict(r['edit_plan']) if isinstance(r.get('edit_plan'),dict) else legacy_plan(vr)
        raw_plan['risk_context']={'title':vr['title'],'conclusion':vr['conclusion'],'explanation':vr['explanation'],
                                  'evidence':[{'block_id':e.get('block_id',''),'quote':e.get('quote',''),'no_text':e.get('no_text',False)} for e in vr['evidence']],
                                  'category':vr['category'],'severity':vr['severity'],'risk_source':vr['risk_source'],
                                  'scope_note':vr['scope_note'],'manual_checks':vr['manual_checks'],
                                  'perspective':draft.get('perspective',{}),'evidence_verified':all_ev_ok and bool(vr['evidence'])}
        vr['edit_plan']=evaluate_plan(raw_plan,contract,draft.get('contract_analysis'),vr['legal_basis'])
        vr['verification_status']['suggestion_quality']=vr['edit_plan']['quality_result']
        verified_risks.append(vr)

    # 去重合并：完全相同签名 (category + spans + basis) 合并
    merged = {}
    order = []
    for vr in verified_risks:
        sig = risk_signature(vr)
        if sig in merged:
            base = merged[sig]
            base["merged_from"] = base.get("merged_from", [base["risk_id"]]) + [vr["risk_id"]]
            # 合并 manual_checks / proposed_clause 缺失项
            for mc in vr.get("manual_checks", []):
                if mc not in base["manual_checks"]:
                    base["manual_checks"].append(mc)
            stats["merged"] += 1
        else:
            merged[sig] = vr
            order.append(sig)
    final_risks = [merged[s] for s in order]

    # 排序：severity -> 出现位置
    def sort_key(r):
        first = min((e["span"][0] for e in r["evidence"] if e.get("span")), default=10**9)
        return (SEV_ORDER.get(r["severity"], 9), first)
    final_risks.sort(key=sort_key)

    # 重新编号 risk_id 为稳定顺序号，但保留原 id 映射
    id_map = {}
    for n, r in enumerate(final_risks, 1):
        old = r["risk_id"]
        new = f"R{n:03d}"
        id_map[old] = new
        r["orig_id"] = old
        r["risk_id"] = new

    resolution=[]
    for item in draft.get('risk_resolution',[]):
        if not isinstance(item,dict):
            issues.append('复审分类记录不是对象，需重新提供');continue
        item=dict(item);target=item.get('current_risk_id')
        if item.get('status')=='resolved':
            from plan_quality import post_review_valid
            if not post_review_valid(item,contract):
                item['status']='needs_confirmation';item['reason']='缺少与当前稿绑定的语义复审，不能把修改插入或风险未再列出认定为已解决。'
        if target in id_map:item['current_risk_id']=id_map[target]
        elif target and target not in {r['risk_id'] for r in final_risks}:
            item['status']='needs_confirmation';item['reason']='当前风险编号不存在，需 WorkBuddy 重新核对映射。'
            issues.append('复审分类引用不存在的当前风险编号：'+str(target))
            item.pop('current_risk_id',None)
        resolution.append(item)

    result = {
        "contract": {
            "source_name": contract["source_name"],
            "file_sha256": contract["file_sha256"],
            "title_guess": contract["title_guess"],
            "parse_status": contract["parse_status"],
            "char_count": contract["char_count"],
        },
        "review_meta": {
            "reviewed_at": now_iso(),
            "contract_type": draft.get("contract_type", ""),
            "law_scope": [
                {"law_id": lid, "law_name": law["meta"]["law_name"],
                 "version": law["meta"]["version"], "status": law["meta"].get("status", "")}
                for lid, law in law_index.items()
            ],
            "kb_notes": kb_notes,
            "scope_limitation": draft.get("scope_limitation", ""),
            "stats": stats,
            "issues": issues,
            "schema_version":2,
            "review_id":__import__('uuid').uuid4().hex,
            "perspective":draft.get('perspective',read_json(task_dir/'review_context.json').get('perspective') if (task_dir/'review_context.json').exists() else {'mode':'neutral','focus':''}),
            "risk_resolution":resolution,
            "contract_analysis":draft.get('contract_analysis'),
        },
        "risks": final_risks,
        "risk_id_map": id_map,
    }
    if (task_dir/'review_result.json').exists():
        import uuid
        archive=task_dir/'history'/uuid.uuid4().hex[:12]
        for name in ['review_result.json','verified_review.json','contract_review.html','review_context.json']:
            if (task_dir/name).exists():
                archive.mkdir(parents=True,exist_ok=True)
                (archive/name).write_bytes((task_dir/name).read_bytes())
    write_json(task_dir / args.out, result)
    # 验收规范要求的固定产物名：review_result.json（结构化风险结果）
    write_json(task_dir / "review_result.json", result)
    write_json(task_dir/'quality_requests.json',{'requires_workbuddy_analysis':True,'requests':[
        {'risk_id':r['risk_id'],'plan_id':r['edit_plan'].get('plan_id'),'plan_fingerprint':r['edit_plan']['plan_fingerprint'],
         'scope_node_hashes':{k:__import__('plan_quality').digest(v) for k,v in r['edit_plan']['scope_node_texts'].items()},
         'raw_plan':r['edit_plan']['raw_plan'],'preview_nodes':r['edit_plan']['preview_nodes'],'blockers':r['edit_plan']['blockers']}
        for r in final_risks]})
    merge_log(task_dir, "validate_review", {
        "stats": stats, "issue_count": len(issues),
        "final_risk_count": len(final_risks), "kb_notes": kb_notes,
    })

    print(f"[校验完成] 草稿 {stats['total']} 条 -> 合并后 {len(final_risks)} 条")
    print(f"  法条不存在: {stats['basis_not_found']}  法条不一致: {stats['basis_mismatch']}")
    print(f"  证据未定位: {stats['evidence_unverified']}  结构错误: {stats['struct_errors']}  合并: {stats['merged']}")
    if kb_notes:
        print(f"  知识库提示: {'; '.join(kb_notes)}")
    for it in issues:
        print(f"  ! {it}")
    # 不因为发现问题而退出非零：问题本身就是要呈现给用户的校验结果


if __name__ == "__main__":
    main()
