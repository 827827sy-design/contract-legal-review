"""Contract-independent edit-plan checks. Semantic findings come from WorkBuddy.

This module never infers a legal conclusion from words or clause numbers. It
checks model-produced relations/evidence, structured business facts and a bound
semantic review. Missing review is blocking, not a successful legal check.
"""
from __future__ import annotations
import argparse,copy,hashlib,json,re
from pathlib import Path
from revision_core import nodes_for
from check_amounts import check as check_amount
from common import read_json,write_json,force_utf8_stdio

CHECKS=('addresses_cause','removes_cause','related_consistency','no_duplicate_liability',
        'preserves_rights','no_new_major_risk','business_complete','legal_scope',
        'perspective_objective','scope_complete')
READINESS={'ready','editable_draft','needs_input','coordinated_review','manual_review','generation_failed'}
RESERVED_KEYS={'__proto__','constructor','prototype'}
PLACEHOLDER=re.compile(r'【[^】]+】|_{2,}|\{\{[^}]+\}\}|\bTODO\b|\bTBD\b|年\s*月\s*日',re.I)
COMMENTARY=re.compile(r'（示例文本）|\(示例文本\)|^\s*[（(]?仅供参考[）)]?[。.!！]?\s*$|以下为修改建议|^\s*(?:说明|修改建议|示例文本)\s*[:：]',re.M)

def digest(value):
    def normalize(x):
        if isinstance(x,float) and x.is_integer():return int(x)
        if isinstance(x,dict):return {k:normalize(v) for k,v in x.items()}
        if isinstance(x,(list,tuple)):return [normalize(v) for v in x]
        return x
    value=normalize(value)
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()

def formal_issues(text,literal_brackets=()):
    findings=[]
    for match in PLACEHOLDER.finditer(text):
        if match.group() not in literal_brackets or re.search('待|填写|未知|金额|日期|期限|比例|税率|另行|明确|住所',match.group()):findings.append('未确认占位内容：'+match.group())
    if COMMENTARY.search(text):findings.append('说明性文字混入正式条款')
    return findings
def introduced_formal_issues(before,after,literal_brackets=()):
    """Keep untouched pending fields outside a precise edit; do not clean them."""
    import difflib
    equal=[(b,d) for tag,a,c,b,d in difflib.SequenceMatcher(None,before,after,autojunk=False).get_opcodes() if tag=='equal']
    text=after
    # Mask only exact unresolved labels in unchanged ranges for checking.
    matches=list(PLACEHOLDER.finditer(after))+list(COMMENTARY.finditer(after))
    for m in sorted(matches,key=lambda m:m.start(),reverse=True):
        if any(lo<=m.start() and hi>=m.end() for lo,hi in equal):text=text[:m.start()]+' '*len(m.group())+text[m.end():]
    return formal_issues(text,literal_brackets)

def graph_scope(analysis,nodes,targets):
    scope=set(targets);errors=[];uncertain=[];edge_errors=[]
    if not isinstance(analysis,dict):return scope,['缺少WorkBuddy关联分析'],[]
    edges=analysis.get('edges',[])
    if not isinstance(edges,list):return scope,['关联边格式错误'],[]
    validated=[]
    for edge in edges:
        if not isinstance(edge,dict):errors.append('关联边不是对象');continue
        a,b=edge.get('from'),edge.get('to')
        if a not in nodes or b not in nodes or not edge.get('relationship') or not edge.get('reason'):
            edge_errors.append((a,b,'关联边端点或解释缺失'));continue
        valid=True
        for key,node_id in [('source_quote',a),('target_quote',b)]:
            quote=edge.get(key)
            if not isinstance(quote,str) or not quote or quote not in nodes[node_id]['text']:
                edge_errors.append((a,b,'关联证据无法核验：'+str(node_id)));valid=False
        # Keep endpoints for scope propagation even if a quote has become stale.
        validated.append(edge)
    changed=True
    while changed:
        changed=False
        for edge in validated:
            if edge['from'] in scope or edge['to'] in scope:
                before=len(scope);scope.update([edge['from'],edge['to']]);changed|=len(scope)!=before
    for edge in validated:
        if (edge['from'] in scope or edge['to'] in scope) and edge.get('status')!='confirmed':uncertain.append(edge)
    errors.extend(message for a,b,message in edge_errors if a in scope or b in scope)
    return scope,errors,uncertain

def plan_fingerprint(plan,scope,analysis,basis):
    payload={k:copy.deepcopy(plan.get(k)) for k in ('plan_id','risk_id','reason','questions','edits','business_terms',
              'required_edit_node_ids','postconditions','amount_records','literal_bracket_terms','related_risk_ids','source_revision_basis','risk_context','input_draft_id','source_file_sha256','condition_changes')}
    payload.update({k:copy.deepcopy(plan[k]) for k in ('field_bindings','materialization','no_edit_reason') if k in plan})
    relevant=None
    if isinstance(analysis,dict):
        relevant={'edges':[e for e in analysis.get('edges',[]) if isinstance(e,dict) and (e.get('from') in scope or e.get('to') in scope)],
                  'obligations':[o for o in analysis.get('obligations',[]) if isinstance(o,dict) and set(o.get('node_ids',[]))&set(scope)]}
    return digest({'plan':payload,'scope_node_texts':scope,'analysis':relevant,'risk_basis':basis})

def preview_edits(edits,nodes):
    """Preflight the entire set, then build a copy. No mutation on failure."""
    errors=[];normalized=[];ids=set();by_node={}
    if not isinstance(edits,list) or not edits:return [],{},['没有可执行修改动作']
    for index,raw in enumerate(edits):
        if not isinstance(raw,dict):errors.append('修改动作不是对象');continue
        e=copy.deepcopy(raw);eid=e.get('edit_id')
        if not isinstance(eid,str) or not eid or eid in ids:errors.append('修改动作ID缺失或重复')
        ids.add(eid)
        node=nodes.get(e.get('target_node_id'));op=e.get('operation')
        if node is None:errors.append('目标节点不存在');continue
        text=node['text'];expected=e.get('expected_node_text')
        if expected!=text:errors.append('目标完整原文不匹配：'+node['node_id'])
        if op not in {'partial','replace','insert_clause','delete_clause'}:errors.append('未知计划操作');continue
        if op!='insert_clause' and not node.get('editable'):errors.append('目标为只读节点：'+node['node_id'])
        if op=='insert_clause':
            group=[n for n in nodes.values() if n['block_id']==node['block_id']]
            if group[-1]['node_id']!=node['node_id']:errors.append('新增条款锚点位于表格内部')
            if e.get('expected_original')!=text:errors.append('插入锚点原文不匹配')
            if node.get('locator') and isinstance(e.get('replacement_text'),str) and any(x in e['replacement_text'] for x in ('\t','\n')):errors.append('新增Word条款应为单段；结构换行需独立条款或文档工具处理')
            start=end=len(text)
        elif op in {'replace','delete_clause'}:
            start,end=0,len(text)
            if e.get('expected_original')!=text:errors.append('整段原文不匹配')
        else:
            start,end=e.get('start'),e.get('end')
            if type(start)is not int or type(end)is not int or not 0<=start<=end<=len(text):errors.append('局部范围越界');continue
            if text[start:end]!=e.get('expected_original'):errors.append('局部原文不匹配')
        replacement=e.get('replacement_text')
        if replacement is None and e.get('draft_pending') is True:
            e.update(start=start,end=end);normalized.append(e);by_node.setdefault(node['node_id'],[]).append(e);continue
        if not isinstance(replacement,str):errors.append('正式修改文字缺失');continue
        if op=='delete_clause' and replacement!='':errors.append('删除条款的替换内容必须为空')
        if op=='insert_clause' and not replacement.strip():errors.append('新增条款不能为空')
        if not isinstance(e.get('dependencies',[]),list) or any(x not in nodes for x in e.get('dependencies',[])):errors.append('关联节点不存在')
        e.update(start=start,end=end);normalized.append(e);by_node.setdefault(node['node_id'],[]).append(e)
    for node_id,actions in by_node.items():
        for i,a in enumerate(actions):
            for b in actions[i+1:]:
                if a['operation']!='partial' or b['operation']!='partial' or max(a['start'],b['start'])<min(a['end'],b['end']) or a['start']==b['start']:
                    errors.append('组内修改范围冲突：'+node_id)
    if errors:return normalized,{},errors
    after={k:n['text'] for k,n in nodes.items()}
    for node_id,actions in by_node.items():
        if actions[0]['operation']=='insert_clause' or any(a.get('draft_pending') for a in actions):continue
        for e in sorted(actions,key=lambda x:x['start'],reverse=True):
            text=after[node_id];after[node_id]=text[:e['start']]+e['replacement_text']+text[e['end']:]
        if nodes[node_id].get('locator'):
            from docx_controls import validate_controls
            try:validate_controls(nodes[node_id]['text'],after[node_id])
            except ValueError as exc:errors.append(str(exc))
    return normalized,after,errors

def evaluate_plan(raw,contract,analysis=None,basis=None):
    p=copy.deepcopy(raw) if isinstance(raw,dict) else {}
    if not p.get('source_file_sha256'):p['source_file_sha256']=contract.get('file_sha256')
    nodes={n['node_id']:n for n in nodes_for(contract)};basis=basis or []
    edits,after,position_errors=preview_edits(p.get('edits'),nodes)
    targets={e.get('target_node_id') for e in edits if e.get('target_node_id') in nodes}
    changes=p.get('condition_changes',[])
    if not isinstance(changes,list):changes=[];position_errors.append('条件变更清单格式错误')
    scope_targets=targets|{k for e in edits for k in e.get('dependencies',[])}|{x.get('source_node_id') for x in changes if isinstance(x,dict) and x.get('source_node_id') in nodes}
    scope,graph_errors,uncertain=graph_scope(analysis,nodes,scope_targets)
    scope_values={k:nodes[k]['text'] for k in sorted(scope) if k in nodes}
    fingerprint=plan_fingerprint(p,scope_values,analysis,basis)
    blockers=[];check_results=[]
    def add(code,result,reason):
        check_results.append({'code':code,'result':result,'reason':reason})
        if result!='pass':blockers.append(reason)
    context=p.get('risk_context',{})
    valid_id=isinstance(p.get('plan_id'),str) and bool(p['plan_id']) and p['plan_id'] not in RESERVED_KEYS
    add('identity','pass' if valid_id and isinstance(context,dict) and context.get('title') and context.get('conclusion') and context.get('explanation') else 'manual','计划与原始风险原因已结构化绑定' if valid_id and context else '缺少安全计划ID或原始风险原因')
    add('contract_identity','pass' if p.get('source_file_sha256') and p['source_file_sha256']==contract.get('file_sha256') else 'conflict','修改计划与原始合同文件指纹绑定' if p.get('source_file_sha256')==contract.get('file_sha256') else '修改计划不属于当前原始合同文件')
    add('risk_evidence','pass' if context.get('evidence_verified') is True else 'manual','原始风险证据通过校验' if context.get('evidence_verified') is True else '原始风险证据缺失或未定位，不能直接应用方案')
    if context.get('category') in {'法律合规风险','合同效力风险'} and not any(b.get('status')=='verified' for b in basis):add('mandatory_basis','insufficient','涉及法律强制或效力判断但没有已核验条文依据')
    add('position','manual' if position_errors==['没有可执行修改动作'] else 'conflict' if position_errors else 'pass','；'.join(position_errors) if position_errors else '所有目标、完整原文及局部范围匹配')
    add('graph','manual' if graph_errors or uncertain else 'pass','；'.join(graph_errors) if graph_errors else '存在尚未确定的关联关系' if uncertain else '模型提交的关联边证据可定位；关系性质仍由模型判断')
    questions=p.get('questions',[])
    if not isinstance(questions,list):questions=[];add('questions_schema','conflict','问题列表格式错误')
    question_ids=[q.get('id') for q in questions if isinstance(q,dict)]
    if any(not isinstance(x,str) or not x or x in RESERVED_KEYS for x in question_ids) or len(question_ids)!=len(questions) or len(question_ids)!=len(set(question_ids)):add('question_ids','conflict','问题ID缺失、重复或使用保留键')
    unanswered=[q for q in questions if not isinstance(q,dict) or q.get('required',True) and not (q.get('answer') and q.get('confirmed') is True)]
    terms=p.get('business_terms',[])
    proposals=[t for t in terms if isinstance(t,dict) and t.get('kind')=='negotiation' and t.get('proposed') is True and t.get('source') and t.get('value') not in (None,'')]
    unconfirmed=[t for t in terms if not isinstance(t,dict) or not t.get('source') or t.get('value') in (None,'') or t.get('confirmed') is not True and t not in proposals]
    text_errors=[error for e in edits for error in formal_issues(e.get('replacement_text') or '',p.get('literal_bracket_terms',[]))]
    text_errors += [error for k in targets if k in after and after[k]!=nodes[k]['text'] for error in (introduced_formal_issues(nodes[k]['text'],after[k],p.get('literal_bracket_terms',[])) if all(e['operation']=='partial' for e in edits if e['target_node_id']==k) else formal_issues(after[k],p.get('literal_bracket_terms',[])))]
    pending_text=any(e.get('draft_pending') for e in edits)
    bound_placeholders=bool(p.get('field_bindings')) and bool(text_errors) and all(any(error=='未确认占位内容：{{field:'+f.get('id','')+'}}' for f in p['field_bindings']) for error in text_errors)
    add('formal_text','manual' if bound_placeholders else 'conflict' if text_errors else 'manual' if pending_text else 'pass','需补充已声明的事实字段，仍不能直接应用' if bound_placeholders else '；'.join(sorted(set(text_errors))) if text_errors else '正式条款尚待条件确认后生成' if pending_text else '正式文字及修改后完整节点未含检测到的占位或说明标签；没有删除括号内容')
    add('text_change','pass' if any(e['operation']=='insert_clause' or e.get('replacement_text')!=e.get('expected_original') for e in edits if not e.get('draft_pending')) else 'manual','存在明确文字变更' if after and any(nodes[k]['text']!=v for k,v in after.items()) or any(e['operation']=='insert_clause' for e in edits) else '尚无可执行文字变更')
    add('business','manual' if unanswered or unconfirmed else 'pass','关键问题或交易条件未经确认' if unanswered or unconfirmed else '结构化交易条件均有确认和来源')
    condition_errors=[];unconfirmed_changes=[]
    for change in changes:
        if not isinstance(change,dict) or change.get('effect') not in {'clarification','business_change','legal_requirement'}:
            condition_errors.append('条件变更缺少明确性质');continue
        node=change.get('node_id');before_quote=change.get('before_quote');after_quote=change.get('after_quote')
        if node not in nodes or not isinstance(before_quote,str) or before_quote not in nodes[node]['text'] or not isinstance(after_quote,str) or not after_quote or after_quote not in after.get(node,''):
            condition_errors.append('条件变更未绑定修改前后原文')
        if not change.get('source') or not change.get('reason'):condition_errors.append('条件变更缺少来源或理由')
        if change['effect']=='business_change' and change.get('confirmed') is not True and not (change.get('proposal_term_id') and any(t.get('id')==change['proposal_term_id'] for t in proposals)):unconfirmed_changes.append(change)
        if change['effect']=='legal_requirement' and not any(b.get('law_id')==change.get('law_id') and b.get('article_no')==change.get('article_no') and b.get('status')=='verified' for b in basis):condition_errors.append('新增法定条件没有已核验的条文依据')
        if change.get('source_node_id'):
            sn=nodes.get(change['source_node_id']);sq=change.get('source_quote')
            if not sn or not isinstance(sq,str) or not sq or sq not in sn['text']:condition_errors.append('条件变更的合同来源无法定位')
    add('condition_changes','conflict' if condition_errors else 'manual' if unconfirmed_changes else 'pass','；'.join(condition_errors) if condition_errors else '新增或变更的商务条件未经确认' if unconfirmed_changes else '已声明条件变更的前后文字和来源通过核验；遗漏仍须语义审查识别')
    required=set(p.get('required_edit_node_ids',[]))
    add('required_edits','conflict' if required-targets else 'pass','缺少关联修改：'+','.join(sorted(required-targets)) if required-targets else '分析要求的修改目标均列入计划')
    post_errors=[]
    for post in ([] if pending_text else p.get('postconditions',[])):
        if not isinstance(post,dict) or post.get('type') not in {'present','absent'} or not isinstance(post.get('text'),str) or not post['text']:
            post_errors.append('文本后置条件缺少明确类型或文字');continue
        ids=post.get('node_ids',[])
        if not ids or any(k not in nodes for k in ids):post_errors.append('文本后置条件节点不存在');continue
        values=[after.get(k,nodes[k]['text']) for k in ids]
        if post['type']=='absent' and any(post['text'] in v for v in values):post_errors.append('导致风险的指定文字仍有残留：'+post['text'])
        if post['type']=='present' and not any(post['text'] in v for v in values):post_errors.append('要求保留的指定文字丢失：'+post['text'])
    add('postconditions','conflict' if post_errors else 'manual' if pending_text else 'pass','；'.join(post_errors) if post_errors else '正式条款尚未生成，文本后置条件待核查' if pending_text else '指定文本后置条件通过，不等同于法律风险已解决')
    amount_errors=[]
    for record in p.get('amount_records',[]):
        try:
            node=record.get('node_id');quote=record.get('after_quote')
            if node not in after or not isinstance(quote,str) or not quote or quote not in after[node]:amount_errors.append('金额记录未绑定修改后的原文')
            amount_errors.extend(check_amount(record))
        except Exception as exc:amount_errors.append('金额不能机械核验：'+str(exc))
    add('amounts','conflict' if amount_errors else 'pass','；'.join(amount_errors) if amount_errors else '提交的明确金额记录通过算术核验；未推定缺失税率')
    revision_nodes=[k for k in scope_values if nodes[k].get('has_existing_revisions')]
    revision_basis=p.get('source_revision_basis',{})
    add('revision_basis','manual' if revision_nodes and not (revision_basis.get('confirmed') is True and revision_basis.get('source') and revision_basis.get('mode') in {'provisional_current','user_confirmed_current'}) else 'pass',
        '涉及未接受旧修订，尚未确认待审文本基准' if revision_nodes and not revision_basis.get('confirmed') else '保留旧修订，确认待审文本基准不等于接受旧修订')
    from proposal_fields import validate_materialization
    materialized=validate_materialization(p,contract,analysis,basis) if p.get('materialization') else False
    assessment=p.get('semantic_review') or {};bound=(assessment.get('plan_fingerprint')==fingerprint or materialized) and assessment.get('scope_node_hashes')=={k:digest(v) for k,v in scope_values.items()} and assessment.get('reviewer')=='WorkBuddy' and bool(assessment.get('reviewed_at'))
    add('semantic_binding','manual' if not bound else 'pass','缺少或过期的WorkBuddy语义审查，需重新分析受影响范围' if not bound else '语义记录与本计划、关联范围及依据绑定')
    semantic=assessment.get('checks',{})
    for code in CHECKS:
        entry=semantic.get(code,{}) if bound else {}
        result=entry.get('result','manual');reason=entry.get('reason','缺少本项语义判断')
        if result not in {'pass','manual','conflict','insufficient'} or not isinstance(reason,str) or not reason.strip():result='manual';reason='语义结论格式或理由不完整'
        add('semantic_'+code,result,reason)
    covered=set(assessment.get('checked_node_ids',[])) if bound else set()
    semantic_complete=bound and not scope-covered and all(isinstance(semantic.get(code),dict) and semantic[code].get('result') in {'pass','manual','conflict','insufficient'} and isinstance(semantic[code].get('reason'),str) and semantic[code]['reason'].strip() for code in CHECKS)
    add('semantic_coverage','manual' if scope-covered else 'pass','语义审查未覆盖关联范围：'+','.join(sorted(scope-covered)) if scope-covered else '已检查声明的关联范围')
    if any(b.get('status') not in {'verified'} for b in basis):add('cited_basis','insufficient','引用依据尚未通过校验')
    can_apply=not blockers
    multi=len(edits)>1 or len(required)>1
    useful=any(isinstance(e.get('replacement_text'),str) and e['replacement_text'].strip() for e in edits)
    if not edits or not pending_text and not any(e['operation']=='insert_clause' or e.get('replacement_text')!=e.get('expected_original') for e in edits):state='manual_review' if p.get('no_edit_reason') else 'generation_failed'
    elif unanswered or unconfirmed or unconfirmed_changes or any('占位' in x for x in text_errors):state='coordinated_review' if multi else 'editable_draft' if useful and p.get('field_bindings') else 'needs_input'
    elif not can_apply:state='coordinated_review' if multi else 'manual_review'
    else:state='coordinated_review' if multi else 'ready'
    substantive=any(c['result']=='conflict' and (c['code'].startswith('semantic_') or c['code']=='postconditions') for c in check_results)
    result_status='生成未完成' if state=='generation_failed' else '发现明确冲突' if substantive else '修改计划校验失败' if any(c['result']=='conflict' for c in check_results) else '模型核验未完成' if not semantic_complete and not p.get('no_edit_reason') else '依据不足，无法完成核验' if any(c['result']=='insufficient' for c in check_results) else '需要人工确认' if blockers else '已满足系统检查条件'
    output={**p,'execution_protocol':2,'readiness':state,'can_apply':can_apply,'reason':p.get('reason',''),'quality_result':result_status,
            'blockers':blockers,'checks':check_results,'questions':questions,'edits':edits,'scope_node_texts':scope_values,
            'plan_fingerprint':fingerprint,'preview_nodes':[{ 'node_id':k,'before':nodes[k]['text'],'after':after[k]} for k in sorted(targets) if k in after and nodes[k]['text']!=after[k]],
            'proposed_terms':proposals,'semantic_review_mode':'pre_reviewed_field_materialization' if materialized else 'workbuddy_review',
            'semantic_bound':bound,'semantic_complete':semantic_complete,'review_phase':'reviewed' if semantic_complete else 'not_required_without_edit' if p.get('no_edit_reason') else 'awaiting_model_review',
            'validation':{'position_verified':not position_errors,'business_terms_confirmed':not unanswered and not unconfirmed and not text_errors and not proposals,
                          'related_clauses_checked':not graph_errors and not uncertain and bound and not scope-covered,
                          'legal_scope_checked':bound and semantic.get('legal_scope',{}).get('result')=='pass'},
            'raw_plan':p,'analysis':analysis,'risk_basis':basis,'risk_status_after_apply':'needs_re_review'}
    output['compiled_digest']=digest({k:v for k,v in output.items() if k!='compiled_digest'})
    return output

def legacy_plan(risk):
    return {'plan_id':'legacy-'+risk['risk_id'],'risk_id':risk['risk_id'],'reason':'旧版建议可展示；缺少正式修改计划及语义质量记录，不能按证据猜测替换范围。',
            'questions':[{'id':'regenerate','question':'请返回WorkBuddy确认关键条件并生成、核验正式修改计划。','required':True}],
            'edits':[],'legacy_display_text':risk.get('proposed_clause','')}

def verify_compiled(plan,contract):
    expected=digest({k:v for k,v in plan.items() if k!='compiled_digest'})
    if expected!=plan.get('compiled_digest'):raise ValueError('修改计划内容已变化，须重新校验。')
    actual=evaluate_plan(plan.get('raw_plan'),contract,plan.get('analysis'),plan.get('risk_basis'))
    if not actual['can_apply'] or actual['plan_fingerprint']!=plan.get('plan_fingerprint'):raise ValueError('修改计划未满足应用条件或语义审查已过期。')
    if plan.get('risk_identity'):actual['risk_identity']=copy.deepcopy(plan['risk_identity']);actual['compiled_digest']=digest({k:v for k,v in actual.items() if k!='compiled_digest'})
    return actual

def post_review_valid(item,contract):
    review=item.get('semantic_post_review') or {};nodes={n['node_id']:n for n in nodes_for(contract)}
    hashes=review.get('scope_node_hashes')
    if review.get('reviewer')!='WorkBuddy' or not review.get('reviewed_at') or review.get('prior_risk_id')!=item.get('prior_risk_id') or not isinstance(hashes,dict) or not hashes:return False
    if any(k not in nodes or digest(nodes[k]['text'])!=v for k,v in hashes.items()):return False
    checks=review.get('checks',{})
    return all(checks.get(k,{}).get('result')=='pass' and checks[k].get('reason') for k in CHECKS) and not review.get('unresolved_items')

def main():
    force_utf8_stdio();ap=argparse.ArgumentParser();ap.add_argument('--task-dir',required=True);args=ap.parse_args()
    task=Path(args.task_dir)
    import subprocess,sys
    subprocess.run([sys.executable,'-B','-X','utf8',str(Path(__file__).with_name('validate_review.py')),'--task-dir',str(task),'--index-dir',str(Path(__file__).resolve().parent.parent/'law_index')],check=True,capture_output=True)
    verified=read_json(task/'review_result.json')
    requests=[]
    for r in verified.get('risks',[]):
        plan=r['edit_plan']
        requests.append({'risk_id':r['risk_id'],'plan_id':plan['plan_id'],'plan_fingerprint':plan['plan_fingerprint'],'needs_review':bool(plan['edits']) and not plan.get('semantic_complete') and not plan.get('no_edit_reason'),
                         'scope_node_hashes':{k:digest(v) for k,v in plan['scope_node_texts'].items()},
                         'required_semantic_checks':CHECKS,'preview_nodes':plan['preview_nodes'],'questions':plan['questions'],'blockers':plan['blockers'],'raw_plan':plan['raw_plan']})
    pending=[r for r in requests if r['needs_review']]
    write_json(task/'quality_requests.json',{'requires_workbuddy_analysis':bool(pending),'requests':pending,'bindings':requests})
    print(json.dumps({'output':str(task/'quality_requests.json'),'requests':len(pending),'semantic_checks_executed_by_python':False},ensure_ascii=False))

if __name__=='__main__':main()
