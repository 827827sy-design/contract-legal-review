"""Final new inputs, not used for production tuning. Explicit test receipts."""
import copy,json,os,unittest,hashlib
from pathlib import Path
from test_plan_quality import contract,action,edge,plan,assess,revision
from plan_quality import evaluate_plan
from plan_executor import execute_plan
from proposal_fields import instantiate
ROOT=Path(__file__).resolve().parents[1]
def hashes():return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for d in ['scripts','assets'] for p in sorted((ROOT/d).glob('*')) if p.is_file()}
BEFORE=hashes()
class FinalHoldout(unittest.TestCase):
    def test_batch_record_two_places_instantiates_as_one_consistent_group(self):
        c=contract(['物流交接合同','交接记录批号待录入。','复核记录批号待录入。','包装及运输赔偿另依既有条款。'])
        g={'edges':[edge(c,'b0002','b0003','same_fact_record')],'obligations':[]}
        actions=[action(c,id,'交接/复核记录批号为{{field:batch}}。') for id in ['b0002','b0003']];p=plan(c,actions,['b0002','b0003']);p['questions']=[{'id':'batch_fact','question':'录入已核实的批号','required':True}];p['field_bindings']=[{'id':'batch','kind':'short_text','max_length':30,'question_id':'batch_fact','edit_ids':[e['edit_id'] for e in actions],'semantic_effect':'fact_only'}]
        q=assess(p,c,g);raw=q['raw_plan'];raw['semantic_review']['field_policy']={'approved':True,'field_ids':['batch'],'reason':'仅同一事实记录，两处绑定，不改变赔偿机制。'}
        raw=instantiate(raw,{'batch':'BATCH-203-已核对'});ready=evaluate_plan(raw,c,g);self.assertTrue(ready['can_apply'],ready['blockers']);s=execute_plan(c,revision(c),ready)
        self.assertEqual(s['current_nodes']['b0002'],s['current_nodes']['b0003']);self.assertEqual(s['current_nodes']['b0004'],c['blocks'][3]['text']);self.assertEqual(len(s['plan_groups']),1)
    def test_numeric_fact_does_not_allow_extra_business_clause(self):
        c=contract(['设备交接记录','实收件数待填写，赔偿责任另依原约定。']);p=plan(c,[action(c,'b0002','实收件数{{field:count}}件，赔偿责任另依原约定。')]);p['questions']=[{'id':'count','question':'实收数量','required':True}];p['field_bindings']=[{'id':'count','kind':'decimal','min':'0','max':'99999999999999999.99','question_id':'count','edit_ids':[p['edits'][0]['edit_id']],'semantic_effect':'fact_only'}]
        q=assess(p,c,{'edges':[]});raw=q['raw_plan'];raw['semantic_review']['field_policy']={'approved':True,'field_ids':['count'],'reason':'记录事实数量，不改变赔偿责任。'}
        value=instantiate(raw,{'count':'17'});ready=evaluate_plan(value,c,{'edges':[]});self.assertTrue(ready['can_apply']);self.assertIn('17件',execute_plan(c,revision(c),ready)['current_nodes']['b0002'])
        bad=copy.deepcopy(value);bad['edits'][0]['replacement_text']+='双方免除赔偿责任。';self.assertFalse(evaluate_plan(bad,c,{'edges':[]})['can_apply'])
    @classmethod
    def tearDownClass(cls):
        if BEFORE!=hashes():raise AssertionError('Production changed during final holdout')
        out=Path(os.environ.get('CONTRACT_REVIEW_TEST_DIR','work/usability-tests'))/'usability-final-holdout.json';out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps({'cases':2,'production_unchanged':True,'hashes':BEFORE,'independent_model':False},indent=2),encoding='utf-8')
if __name__=='__main__':unittest.main(verbosity=2)
