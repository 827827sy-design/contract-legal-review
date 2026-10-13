"""Content/structure tests for usability fixes. Synthetic data only."""
import copy,json,sys,tempfile,unittest,os,uuid,zipfile,subprocess,xml.etree.ElementTree as ET
from pathlib import Path
from test_plan_quality import contract,action,plan,assess,revision
from plan_quality import evaluate_plan,verify_compiled
from plan_executor import execute_plan
from proposal_fields import instantiate
from proposal_pipeline import proposals_for,coverage
from extract_contract import W,_docx_paragraph_text,paragraph_features
from docx_tracked import Tracker,replace_tracked
from docx_controls import replace_plain_islands
from test_tracked import xml,reject_new
from knowledge import load_records,content_digest,temporal_status

def field_template():
    c=contract(['服务合同','履约记录：资料收到日期待填写。','付款仍按验收后30日，日期记录不单独改变验收条件。'])
    p=plan(c,[action(c,'b0002','履约记录：资料收到日期为{{field:received}}。')]);p['reason']='填入已确认的资料收到事实，仅作记录，不改变验收和付款条件。'
    p['questions']=[{'id':'received_fact','question':'请填入已核实的资料收到日期（YYYY-MM-DD）。','required':True}]
    p['field_bindings']=[{'id':'received','question_id':'received_fact','edit_ids':[p['edits'][0]['edit_id']],'kind':'date','semantic_effect':'fact_only'}]
    q=assess(p,c,{'edges':[],'obligations':[]});raw=q['raw_plan'];raw['semantic_review']['field_policy']={'approved':True,'field_ids':['received'],'reason':'仅替换事实记录，保留验收、付款机制；有效日期由确定性规则检查。'}
    q=evaluate_plan(raw,c,{'edges':[],'obligations':[]});return c,q
class Usability(unittest.TestCase):
    def test_tabs_and_breaks_preserve_xml_and_native_history(self):
        data='<w:r><w:rPr><w:b/></w:rPr><w:tab/><w:t>金额100</w:t><w:tab/><w:t>付款30日</w:t><w:br w:clear="none"/><w:t>保修一年</w:t></w:r>'
        for tracked in [False,True]:
            p=xml(data);before=_docx_paragraph_text(p);controls=[ET.tostring(n) for n in p.iter() if n.tag in {W+'tab',W+'br',W+'cr'}];after='\t金额120\t付款20日\n保修一年'
            self.assertTrue(paragraph_features(p)['editable'])
            if tracked:
                t=Tracker(p);replace_tracked(p,before,after,t);restored=reject_new(copy.deepcopy(p),set(t.ids));self.assertEqual(_docx_paragraph_text(restored),before)
            else:replace_plain_islands(p,before,after)
            self.assertEqual(_docx_paragraph_text(p),after);self.assertEqual([ET.tostring(n) for n in p.iter() if n.tag in {W+'tab',W+'br',W+'cr'}],controls)
    def test_empty_text_island_can_be_filled_without_deleting_tab(self):
        for tracked in [False,True]:
            p=xml('<w:r><w:tab/></w:r>');before='\t';after='签收\t2026-10-12'
            if tracked:replace_tracked(p,before,after,Tracker(p))
            else:replace_plain_islands(p,before,after)
            self.assertEqual(_docx_paragraph_text(p),after);self.assertEqual(len(list(p.iter(W+'tab'))),1)
    def test_structure_change_or_page_break_remains_guarded(self):
        p=xml('<w:r><w:t>甲</w:t><w:tab/><w:t>乙</w:t></w:r>')
        with self.assertRaises(ValueError):replace_plain_islands(p,'甲\t乙','甲乙')
        self.assertFalse(paragraph_features(xml('<w:r><w:br w:type="page"/><w:t>分页</w:t></w:r>'))['editable'])
    def test_tab_stop_is_formatting_not_body_text_and_legacy_record_can_migrate(self):
        p=xml('<w:pPr><w:tabs><w:tab w:val="left" w:pos="400"/></w:tabs></w:pPr><w:r><w:t>付款30日。</w:t><w:tab/><w:t>保修</w:t></w:r>')
        self.assertEqual(_docx_paragraph_text(p),'付款30日。\t保修');self.assertEqual(len(paragraph_features(p)['text_controls']),1)
        original_props=ET.tostring(p.find(W+'pPr'));replace_tracked(p,_docx_paragraph_text(p),'付款20日。\t保修',Tracker(p));self.assertEqual(ET.tostring(p.find(W+'pPr')),original_props)
        from migrate_revisions import migrate
        from revision_core import document_for
        c=contract(['付款30日。']);c['blocks'][0]['legacy_layout_tabstop_count']=1;doc=document_for(c);v=revision(c);v['base_nodes']['b0001']='\t付款30日。';v['current_nodes']['b0001']='\t付款30日。';v['contract']['content_sha256']='old-parser-snapshot'
        changed,did=migrate(doc,v);self.assertTrue(did);self.assertEqual(changed['base_nodes']['b0001'],'付款30日。');self.assertEqual(v['base_nodes']['b0001'],'\t付款30日。')
    def test_parser_serializes_control_and_format_metadata_without_stripping_cells(self):
        base=Path(os.environ.get('CONTRACT_REVIEW_TEST_DIR','work/usability-tests'));task=base/('parse-meta-'+uuid.uuid4().hex);task.mkdir(parents=True);source=task/'synthetic.docx'
        body='<w:p><w:pPr><w:jc w:val="center"/><w:tabs><w:tab w:val="left" w:pos="400"/></w:tabs></w:pPr><w:r><w:t>标题</w:t><w:tab/><w:t>记录</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:tab/><w:t>单元格</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
        with zipfile.ZipFile(source,'w') as z:z.writestr('word/document.xml','<w:document xmlns:w="'+W[1:-1]+'"><w:body>'+body+'</w:body></w:document>')
        subprocess.run([sys.executable,'-B','-X','utf8',str(Path(__file__).parents[1]/'scripts/extract_contract.py'),'--input',str(source),'--task-dir',str(task)],check=True,capture_output=True)
        c=json.loads((task/'contract.json').read_text(encoding='utf-8'));n=c['nodes'][0];self.assertEqual(n['legacy_layout_tabstop_count'],1);self.assertEqual(len(n['text_controls']),1);self.assertEqual(n['alignment'],'center');self.assertEqual(n['text'],'标题\t记录');self.assertEqual(c['nodes'][1]['text'],'\t单元格');self.assertTrue(c['nodes'][1]['editable'])
    def test_partial_actions_keep_exact_ranges_and_group_cannot_be_tampered(self):
        c=contract(['价款100元，通知期30日。']);p=plan(c,[action(c,'b0001','120',start=2,end=5),action(c,'b0001','20',start=10,end=12)])
        q=assess(p,c,{'edges':[],'obligations':[]});s=execute_plan(c,revision(c),q)
        self.assertTrue(all(o['start']>0 for o in s['operations']));self.assertEqual(s['current_nodes']['b0001'],'价款120元，通知期20日。')
        bad=copy.deepcopy(s);bad['operations'][0]['inserted_text']='99';bad['operations'][0]['after_text']=bad['operations'][0]['before_text'][:10]+'99'+bad['operations'][0]['before_text'][12:]
        from revision_core import replay,document_for
        with self.assertRaises(ValueError):replay(document_for(c),bad)
    def test_negotiation_default_requires_explicit_user_acceptance(self):
        c=contract(['付款期限另行商定。']);p=plan(c,[action(c,'b0001','买方于验收合格后30日支付货款。')]);p['business_terms']=[{'id':'days','kind':'negotiation','value':'30日','proposed':True,'confirmed':False,'source':'本测试推荐方案，不是合同事实或法律要求。'}]
        q=assess(p,c,{'edges':[],'obligations':[]});self.assertTrue(q['can_apply']);self.assertFalse(q['validation']['business_terms_confirmed'])
        with self.assertRaises(ValueError):execute_plan(c,revision(c),q)
        s=execute_plan(c,revision(c),q,accept_negotiation=True);self.assertEqual(next(iter(s['plan_groups'].values()))['accepted_negotiation_terms'],q['proposed_terms'])
    def test_pre_reviewed_fact_fields_reuse_receipt_without_new_semantic_claim(self):
        c,t=field_template();self.assertEqual(t['readiness'],'editable_draft');self.assertFalse(t['can_apply'])
        raw=instantiate(t['raw_plan'],{'received':'2026-10-12'});q=evaluate_plan(raw,c,t['analysis']);self.assertTrue(q['can_apply'],q['blockers'])
        self.assertEqual(q['semantic_review_mode'],'pre_reviewed_field_materialization');self.assertEqual(q['raw_plan']['semantic_review'],t['raw_plan']['semantic_review']);s=execute_plan(c,revision(c),q);self.assertIn('2026-10-12',s['current_nodes']['b0002'])
        with self.assertRaises(ValueError):instantiate(t['raw_plan'],{'received':'2026-02-30'})
        bad=copy.deepcopy(raw);bad['edits'][0]['replacement_text']+='供方免除全部责任。';self.assertFalse(evaluate_plan(bad,c,t['analysis'])['can_apply'])
    def test_no_plan_is_generation_failure_and_explicit_manual_reason_is_distinct(self):
        c=contract(['合同']);p=plan(c,[]);q=evaluate_plan(p,c,{'edges':[]});self.assertEqual(q['readiness'],'generation_failed');self.assertNotEqual(q['quality_result'],'发现明确冲突')
        p['no_edit_reason']='需核验原始附件，不能仅改写主文';q=evaluate_plan(p,c,{'edges':[]});self.assertEqual(q['readiness'],'manual_review')
    def test_unrelated_existing_blank_does_not_block_precise_known_edit(self):
        c=contract(['联系电话：123；签署日期： 年 月 日。']);start=c['blocks'][0]['text'].index('123')
        q=assess(plan(c,[action(c,'b0001','456',start=start,end=start+3)]),c,{'edges':[]});self.assertTrue(q['can_apply'],q['blockers'])
        state=execute_plan(c,revision(c),q);self.assertEqual(state['current_nodes']['b0001'],'联系电话：456；签署日期： 年 月 日。')
    def test_new_candidate_owner_is_checked_without_calling_it_legal_conflict(self):
        from proposal_pipeline import compile_candidates
        c=contract(['付款30日。']);p=plan(c,[action(c,'b0001','付款20日。')]);p['risk_id']='another-risk'
        r={'risk_id':'analysis-one','suggestion':{'candidates':[p]}}
        validated={'legal_basis':[]};context={'title':'付款期限','conclusion':'需核对','explanation':'两种表述','evidence_verified':True}
        q=compile_candidates(r,validated,c,{'edges':[]},context)[0];self.assertEqual(q['readiness'],'generation_failed');self.assertFalse(q['can_apply']);self.assertNotEqual(q['quality_result'],'发现明确冲突')
    def test_first_review_gate_requires_complete_semantic_checks(self):
        from proposal_pipeline import coverage
        c=contract(['付款30日。']);p=plan(c,[action(c,'b0001','付款20日。')]);q=assess(p,c,{'edges':[]});raw=copy.deepcopy(q['raw_plan']);del raw['semantic_review']['checks']['preserves_rights'];bad=evaluate_plan(raw,c,{'edges':[]})
        row=lambda p:{'risk_id':'R001','orig_id':'analysis','edit_plan':p,'edit_plans':[p]}
        self.assertFalse(bad['semantic_complete']);self.assertEqual(coverage([row(bad)])['incomplete_count'],1);self.assertEqual(coverage([row(q)])['incomplete_count'],0)
    def test_legacy_without_explicit_target_cannot_guess_and_multiple_candidates_survive(self):
        r={'risk_id':'draft-a','evidence':[{'block_id':'b0001','quote':'甲'}],'proposed_clause':'乙'};self.assertEqual(proposals_for(r)[0]['edits'],[])
        r['suggestion']={'candidates':[{'plan_id':'choice-a'},{'plan_id':'choice-b'}]};self.assertEqual(len(proposals_for(r)),2)
    def test_legal_extension_verification_and_historical_date_are_separate(self):
        base=Path(os.environ.get('CONTRACT_REVIEW_TEST_DIR','work/usability-tests'));base.mkdir(parents=True,exist_ok=True)
        root=base/('knowledge-'+uuid.uuid4().hex);root.mkdir();directory=root/'extensions';directory.mkdir();articles=[{'no':1,'article_no':'第一条','text':'合成资源，非真实法律。'}]
        resource={'law_id':'synthetic-resource','law_name':'测试','article_count':1,'articles':articles,'source_url':'https://example.invalid/synthetic','version':'测试','effective_from':'2021-01-01','topics':{},'verification':{'status':'pending'}}
        path=directory/'sample.json';path.write_text(json.dumps(resource),encoding='utf-8');self.assertFalse(load_records(root)['synthetic-resource']['_complete'])
        resource['verification']={'status':'verified','verified_at':'synthetic-test','content_sha256':content_digest(articles)};path.write_text(json.dumps(resource),encoding='utf-8');r=load_records(root)['synthetic-resource'];self.assertTrue(r['_complete']);self.assertEqual(temporal_status(r,None)['status'],'unconfirmed');self.assertEqual(temporal_status(r,'2020-10-01')['status'],'requires_transition_review')
if __name__=='__main__':unittest.main(verbosity=2)
