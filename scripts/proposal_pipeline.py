"""Compile first-review proposals and surface missing generation explicitly."""
import copy
from plan_quality import evaluate_plan,legacy_plan,digest
def proposals_for(risk):
    suggestion=risk.get('suggestion') or {}
    candidates=suggestion.get('candidates',[]) if isinstance(suggestion,dict) else []
    if candidates:return candidates
    if isinstance(risk.get('edit_plan'),dict):return [risk['edit_plan']]
    # Safe migration requires an explicit previously verified edit; evidence
    # alone never selects replacement scope. Semantic review remains required.
    e=risk.get('edit');text=risk.get('proposed_clause')
    if isinstance(e,dict) and e.get('verified') and isinstance(text,str) and text.strip():
        raw={'plan_id':'migrated-'+risk['risk_id'],'risk_id':risk['risk_id'],'reason':risk.get('recommendation') or risk.get('explanation'),
             'edits':[{'edit_id':'migration-action','target_node_id':e['node_id'],'operation':e['kind'],'start':e.get('start'),'end':e.get('end'),
               'expected_original':e.get('expected_text'),'replacement_text':text,'dependencies':[]}], 'questions':[],'migration':'explicit_position_only'}
        return [raw]
    p=legacy_plan(risk)
    if suggestion.get('no_edit_reason') or risk.get('no_edit_reason'):
        p['no_edit_reason']=suggestion.get('no_edit_reason') or risk['no_edit_reason'];p['reason']=p['no_edit_reason'];p['questions']=[]
    return [p]
def compile_candidates(original,validated,contract,analysis,context):
    source=copy.deepcopy(original)
    if source.get('edit'):source['edit']=validated.get('edit')
    plans=[]
    from revision_core import nodes_for
    nodes={n['node_id']:n for n in nodes_for(contract)}
    for candidate in proposals_for(source):
        raw=copy.deepcopy(candidate);raw['risk_context']=copy.deepcopy(context)
        if raw.get('migration')=='explicit_position_only':
            for e in raw['edits']:
                n=nodes.get(e['target_node_id']);e['expected_node_text']=n['text'] if n else ''
                if e['operation']=='insert_clause':e['expected_original']=e['expected_node_text']
        compiled=evaluate_plan(raw,contract,analysis,validated['legal_basis'])
        if original.get('suggestion') and raw.get('risk_id')!=original.get('risk_id'):
            compiled.update(can_apply=False,readiness='generation_failed',quality_result='生成未完成');compiled['blockers'].append('候选方案的分析风险编号与所属风险不一致');compiled['checks'].append({'code':'risk_owner','result':'manual','reason':'候选方案所属风险待修复'})
        plans.append(compiled)
    ids=[p.get('plan_id') for p in plans]
    if len(ids)!=len(set(ids)):
        for p in plans:
            p['can_apply']=False;p['readiness']='generation_failed';p['quality_result']='生成未完成';p['blockers'].append('同一风险的候选方案编号重复');p['checks'].append({'code':'candidate_identity','result':'manual','reason':'候选方案编号重复'})
    return plans
def refresh_digest(plan):plan['compiled_digest']=digest({k:v for k,v in plan.items() if k!='compiled_digest'})
def coverage(risks):
    rows=[]
    for r in risks:
        plans=r.get('edit_plans',[r['edit_plan']]);p=r['edit_plan']
        rows.append({'risk_id':r['risk_id'],'analysis_id':r.get('orig_id',r['risk_id']),'state':p['readiness'],
          'candidate_count':len(plans),'has_plan':any(x.get('edits') for x in plans),'can_apply':any(x['can_apply'] for x in plans),
          'generation_error':any(x['readiness']=='generation_failed' for x in plans),'model_review_complete':all(x.get('semantic_complete') or x.get('no_edit_reason') for x in plans),
          'no_edit_reason':p.get('no_edit_reason'),'reason':p['blockers']})
    return {'total':len(rows),'incomplete_count':sum(x['generation_error'] or not x['model_review_complete'] or not x['has_plan'] and not x['no_edit_reason'] for x in rows),'rows':rows}
