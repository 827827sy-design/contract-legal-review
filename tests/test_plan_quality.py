"""Plan protocol/content invariants; no production contract-type branches."""
import copy,json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from plan_quality import evaluate_plan,digest,CHECKS,verify_compiled,post_review_valid
from plan_executor import execute_plan,set_group_status
from revision_core import document_for,replay,nodes_for
from common import build_full_text

def contract(texts,kind='测试合同'):
    blocks=[{'block_id':f'b{i+1:04d}','kind':'para','text':text,'editable':True} for i,text in enumerate(texts)]
    full,offsets=build_full_text(blocks)
    return {'source_name':kind+'.txt','file_sha256':digest(texts),'blocks':blocks,'full_text':full,'block_offsets':offsets,'parse_status':'ok','title_guess':kind,'char_count':len(full)}
def action(c,node,after,operation='replace',start=None,end=None):
    n=next(n for n in nodes_for(c) if n['node_id']==node);text=n['text']
    operation='partial' if start is not None and operation=='replace' else operation
    return {'edit_id':'edit-'+node+'-'+str(start),'target_node_id':node,'operation':operation,'expected_node_text':text,
            'expected_original':text if start is None else text[start:end],'start':start,'end':end,'replacement_text':after,'dependencies':[]}
def edge(c,a,b,relation='condition_dependency'):
    n={n['node_id']:n for n in nodes_for(c)}
    return {'from':a,'to':b,'relationship':relation,'source_quote':n[a]['text'],'target_quote':n[b]['text'],'reason':'两处约定处理同一项付款或定义条件，需结合上下文核查。','status':'confirmed'}
def plan(c,actions,required=None):
    return {'plan_id':'plan-test','risk_id':'stable-risk','reason':'统一已确认的付款时间，保留未变更的担保或退还权利。','questions':[],'business_terms':[],
            'edits':actions,'required_edit_node_ids':required or [],'postconditions':[],'amount_records':[],
            'risk_context':{'title':'相同义务的条件冲突','conclusion':'需要统一条件。','explanation':'本测试提供的两处条件描述不同。','evidence_verified':True}}
def assess(p,c,analysis,overrides=None):
    p=copy.deepcopy(p);initial=evaluate_plan(p,c,analysis)
    # This is a test receipt, not an automated model or legal opinion.
    checks={key:{'result':'pass','reason':'按本合成样本指定的范围和业务事实核查此项；仅验证审查记录和执行协议。'} for key in CHECKS}
    checks.update(overrides or {})
    p['semantic_review']={'reviewer':'WorkBuddy','reviewed_at':'test-fixture','plan_fingerprint':initial['plan_fingerprint'],
                          'scope_node_hashes':{k:digest(v) for k,v in initial['scope_node_texts'].items()},
                          'checked_node_ids':list(initial['scope_node_texts']),'checks':checks}
    return evaluate_plan(p,c,analysis)
def revision(c):
    doc=document_for(c);base={n['node_id']:n['text'] for n in doc['original_nodes']}
    return {'schema_version':2,'contract':doc['identity'],'base_nodes':base,'current_nodes':dict(base),'operations':[],
            'history':[],'redo_stack':[],'risk_decisions':{},'perspective':{'mode':'neutral'}}

class Quality(unittest.TestCase):
    def setUp(self):
        self.c=contract(['采购合同','货款于验收后30日支付。','货款于验收后60日支付。','供货人仍承担一年质量保修义务。'],'采购合同')
        self.graph={'edges':[edge(self.c,'b0002','b0003')],'obligations':[{'id':'warranty','node_ids':['b0004'],'summary':'保修权利不变。'}]}
    def test_single_replacement_does_not_cover_related_condition(self):
        p=plan(self.c,[action(self.c,'b0003','货款于验收后30日支付。')],['b0002','b0003'])
        q=assess(p,self.c,self.graph)
        self.assertFalse(q['can_apply']);self.assertTrue(any('缺少关联修改' in b for b in q['blockers']))
    def test_atomic_group_content_rights_and_risk_state(self):
        p=plan(self.c,[action(self.c,'b0002','买方于验收后30日支付货款。'),action(self.c,'b0003','同一货款的付款到期日为验收后30日。')],['b0002','b0003'])
        p['postconditions']=[{'type':'absent','node_ids':['b0002','b0003'],'text':'60日'},{'type':'present','node_ids':['b0004'],'text':'一年质量保修义务'}]
        q=assess(p,self.c,self.graph);self.assertTrue(q['can_apply']);self.assertEqual(q['readiness'],'coordinated_review')
        old=revision(self.c);result=execute_plan(self.c,old,q)
        self.assertEqual(old['operations'],[]);self.assertNotIn('60日',''.join(result['current_nodes'].values()));self.assertIn('保修',result['current_nodes']['b0004'])
        self.assertEqual(result['risk_status']['stable-risk']['status'],'needs_re_review');self.assertEqual(len(result['operations']),2)
        gid=next(iter(result['plan_groups']));undone=set_group_status(result,gid,'undone');undone['current_nodes']=dict(old['base_nodes'])
        replay(document_for(self.c),undone);restored=set_group_status(undone,gid,'active');restored['current_nodes']=result['current_nodes'];replay(document_for(self.c),restored)
        self.assertEqual(restored['current_nodes'],result['current_nodes'])
        bad=copy.deepcopy(result);bad['operations'][0]['status']='undone'
        with self.assertRaises(ValueError):replay(document_for(self.c),bad)
    def test_one_failed_step_no_partial_change(self):
        p=plan(self.c,[action(self.c,'b0002','验收后20日付款。'),action(self.c,'b0003','验收后20日付款。')])
        q=assess(p,self.c,self.graph);old=revision(self.c);tampered=copy.deepcopy(q);tampered['edits'][1]['expected_original']='错误位置'
        with self.assertRaises(ValueError):execute_plan(self.c,old,tampered)
        self.assertEqual(old,revision(self.c))
    def test_same_text_multiple_nodes_exact_target(self):
        c=contract(['服务费为100元。','服务费为100元。','每季度结算。'],'服务合同')
        q=assess(plan(c,[action(c,'b0002','服务费为120元。')]),c,{'edges':[],'obligations':[]});result=execute_plan(c,revision(c),q)
        self.assertEqual(result['current_nodes']['b0001'],'服务费为100元。');self.assertEqual(result['current_nodes']['b0002'],'服务费为120元。')
    def test_missing_terms_placeholders_and_commentary_cannot_apply(self):
        for text in ['货款为【金额】。','付款日为 年 月 日。','货款按【税率】计算。','（示例文本）付款30日内完成。','以下为修改建议：付款30日内完成。']:
            q=assess(plan(self.c,[action(self.c,'b0002',text)]),self.c,self.graph)
            self.assertFalse(q['can_apply']);self.assertTrue(any(c['code']=='formal_text' and c['result']=='conflict' for c in q['checks']))
        p=plan(self.c,[action(self.c,'b0002','货款验收后20日支付。')]);p['questions']=[{'id':'days','question':'是否确认20日？','required':True}]
        q=assess(p,self.c,self.graph);self.assertFalse(q['can_apply']);self.assertEqual(q['readiness'],'needs_input')
    def test_normal_parentheses_preserved(self):
        c=contract(['服务费100元（人民币壹佰元整）。'])
        q=assess(plan(c,[action(c,'b0001','服务费120元（人民币壹佰贰拾元整）。')]),c,{'edges':[],'obligations':[]})
        result=execute_plan(c,revision(c),q);self.assertIn('（人民币壹佰贰拾元整）',result['current_nodes']['b0001'])
    def test_new_semantic_risk_and_rights_loss_block(self):
        c=contract(['服务合同','服务方应退还未履行部分预付款，故意或重大过失造成损失仍应承担责任。'])
        q=assess(plan(c,[action(c,'b0002','服务方不承担任何赔偿或退款责任。')]),c,{'edges':[],'obligations':[]},
                 {'preserves_rights':{'result':'conflict','reason':'删除了未履行部分退款权利。'},'no_new_major_risk':{'result':'conflict','reason':'新增全面免责，需另行法律审查。'}})
        self.assertFalse(q['can_apply']);self.assertEqual(q['quality_result'],'发现明确冲突')
    def test_uncertain_relation_and_insufficient_law_scope(self):
        graph=copy.deepcopy(self.graph);graph['edges'][0]['status']='uncertain'
        q=assess(plan(self.c,[action(self.c,'b0002','付款30日到期。')]),self.c,graph)
        self.assertFalse(q['can_apply'])
        q=assess(plan(self.c,[action(self.c,'b0002','付款30日到期。')]),self.c,self.graph,{'legal_scope':{'result':'insufficient','reason':'修改涉及未核验的专门规则。'}})
        self.assertEqual(q['quality_result'],'依据不足，无法完成核验')
    def test_stale_assessment_cannot_survive_changed_text(self):
        q=assess(plan(self.c,[action(self.c,'b0002','货款验收后20日支付。')]),self.c,self.graph)
        raw=copy.deepcopy(q['raw_plan']);raw['edits'][0]['replacement_text']='货款验收后100日支付。'
        changed=evaluate_plan(raw,self.c,self.graph);self.assertFalse(changed['can_apply']);self.assertIn('过期',''.join(changed['blockers']))
    def test_multiple_plans_same_clause_and_repeated_plan(self):
        q=assess(plan(self.c,[action(self.c,'b0002','货款验收后20日支付。')]),self.c,self.graph)
        state=execute_plan(self.c,revision(self.c),q)
        with self.assertRaises(ValueError):execute_plan(self.c,state,q)
        other=plan(self.c,[action(self.c,'b0002','货款验收后10日支付。')]);other['plan_id']='another'
        second=assess(other,self.c,self.graph)
        with self.assertRaises(ValueError):execute_plan(self.c,state,second)
    def test_two_disjoint_partials_same_node_and_overlap_rejected(self):
        c=contract(['甲方付款30日；乙方交付20日。'])
        p=plan(c,[action(c,'b0001','15',start=4,end=6),action(c,'b0001','10',start=12,end=14)])
        q=assess(p,c,{'edges':[],'obligations':[]});state=execute_plan(c,revision(c),q)
        self.assertEqual(state['current_nodes']['b0001'],'甲方付款15日；乙方交付10日。')
        p['edits'][1]['start']=5;p['edits'][1]['end']=7;p['edits'][1]['expected_original']='0日'
        self.assertFalse(assess(p,c,{'edges':[],'obligations':[]})['can_apply'])
    def test_insert_and_delete_clauses_remain_replayable(self):
        c=contract(['服务合同','旧条款。','双方书面协商变更。'])
        actions=[action(c,'b0002','',operation='delete_clause'),action(c,'b0003','通知应发送至双方确认的邮箱。',operation='insert_clause')]
        q=assess(plan(c,actions),c,{'edges':[],'obligations':[]});state=execute_plan(c,revision(c),q)
        self.assertEqual(state['current_nodes']['b0002'],'');self.assertIn('通知应发送至双方确认的邮箱。',state['current_nodes'].values());replay(document_for(c),json.loads(json.dumps(state)))
    def test_old_word_revision_needs_source_basis(self):
        c=copy.deepcopy(self.c);c['nodes']=nodes_for(c);c['nodes'][1]['has_existing_revisions']=True
        p=plan(c,[action(c,'b0002','货款验收后30日付款。')]);self.assertFalse(assess(p,c,self.graph)['can_apply'])
        p['source_revision_basis']={'mode':'provisional_current','confirmed':True,'source':'合成测试给定的待审文本基准，不接受旧修订。'}
        self.assertTrue(assess(p,c,self.graph)['can_apply'])
    def test_resolution_requires_bound_post_review(self):
        item={'prior_risk_id':'old','status':'resolved'};self.assertFalse(post_review_valid(item,self.c))
        item['semantic_post_review']={'prior_risk_id':'old','reviewer':'WorkBuddy','reviewed_at':'test',
             'scope_node_hashes':{'b0002':digest(self.c['blocks'][1]['text'])},'checks':{k:{'result':'pass','reason':'合成复审记录。'} for k in CHECKS}}
        self.assertTrue(post_review_valid(item,self.c));item['semantic_post_review']['checks']['removes_cause']['result']='manual';self.assertFalse(post_review_valid(item,self.c))
    def test_unrelated_edit_reuses_same_semantic_receipt(self):
        q=assess(plan(self.c,[action(self.c,'b0002','货款验收后20日付款。')]),self.c,self.graph)
        c=copy.deepcopy(self.c);c['blocks'][3]['text']='供货人仍承担两年质量保修义务。'
        self.assertTrue(verify_compiled(q,c)['can_apply'])
    def test_new_payment_precondition_requires_confirmed_business_source(self):
        c=contract(['货款于验收后30日支付。'])
        p=plan(c,[action(c,'b0001','货款于双方书面确认验收合格后30日支付。')])
        p['condition_changes']=[{'node_id':'b0001','before_quote':'验收后','after_quote':'双方书面确认验收合格后','effect':'business_change',
          'source':'尚未有用户或原合同确认','reason':'将付款条件增加为双方书面确认，改变到期条件。','confirmed':False}]
        q=assess(p,c,{'edges':[],'obligations':[]});self.assertFalse(q['can_apply']);self.assertEqual(q['readiness'],'needs_input')

if __name__=='__main__':unittest.main(verbosity=2)
