"""Final held-out inputs introduced after production implementation was frozen.
Explicit semantic outcomes test the protocol, not model/legal accuracy.
"""
import copy,hashlib,json,sys,unittest,os
from pathlib import Path
from test_plan_quality import contract,action,edge,plan,assess,revision
from plan_executor import execute_plan
ROOT=Path(__file__).resolve().parents[1]
def production_hashes():
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for folder in ['scripts','assets'] for p in sorted((ROOT/folder).glob('*')) if p.is_file()}
BEFORE=production_hashes()
class Unseen(unittest.TestCase):
    def test_defined_notice_period_preserves_security_deposit(self):
        c=contract(['设备租赁合同','通知期是提前十个自然日。','解除通知须提前十个工作日送达。','设备完整返还后五日退还保证金。'])
        g={'edges':[edge(c,'b0002','b0003','defined_notice_period')],'obligations':[{'id':'deposit','node_ids':['b0004'],'summary':'保留返还保证金。'}]}
        p=plan(c,[action(c,'b0003','解除通知应按本合同通知期提前十个自然日送达。')])
        p['reason']='合同已有自然日定义，按测试已确认的双方解释统一解除通知口径，保留保证金。'
        p['business_terms']=[{'id':'period','value':'十个自然日','confirmed':True,'source':'本次未参与开发的合成样本明确指定双方选用已有定义。'}]
        p['condition_changes']=[{'node_id':'b0003','before_quote':'十个工作日','after_quote':'十个自然日','source_node_id':'b0002','source_quote':'通知期是提前十个自然日。','effect':'business_change','confirmed':True,'source':'本测试给定的双方确认','reason':'改变计算期限口径，必须确认。'}]
        p['postconditions']=[{'type':'absent','node_ids':['b0003'],'text':'工作日'},{'type':'present','node_ids':['b0004'],'text':'五日退还保证金'}]
        q=assess(p,c,g);self.assertTrue(q['can_apply']);s=execute_plan(c,revision(c),q)
        self.assertEqual(s['current_nodes']['b0003'],'解除通知应按本合同通知期提前十个自然日送达。')
        self.assertEqual(s['current_nodes']['b0004'],c['blocks'][3]['text']);self.assertEqual(s['risk_status']['stable-risk']['status'],'needs_re_review')
    def test_software_license_unknown_acceptance_not_safe(self):
        c=contract(['软件许可与维护合同','可用是指通过附件测试。','交付后三日未反馈即视为可用。','附件测试记录尚未提供。','维护期自可用日起一年，故障期间顺延。'])
        g={'edges':[edge(c,'b0002','b0003','acceptance_definition'),edge(c,'b0002','b0004','attachment_dependency'),edge(c,'b0003','b0005','maintenance_start')],'obligations':[{'id':'extension','node_ids':['b0005'],'summary':'故障期间维护期顺延。'}]}
        p=plan(c,[action(c,'b0003','交付即视为可用。'),action(c,'b0005','维护期自交付日起一年。')],['b0003','b0005'])
        p['reason']='负例试图修复定义，但缺附件、改变验收条件并删除维护顺延权利。'
        q=assess(p,c,g,{'business_complete':{'result':'manual','reason':'未提供附件测试与用户选定的验收方式。'},
          'related_consistency':{'result':'conflict','reason':'通过测试才可用与交付即可用仍冲突。'},
          'preserves_rights':{'result':'conflict','reason':'删除故障期间顺延维护期权利。'}})
        self.assertFalse(q['can_apply']);old=revision(c);snapshot=copy.deepcopy(old)
        with self.assertRaises(ValueError):execute_plan(c,old,q)
        self.assertEqual(old,snapshot)
    @classmethod
    def tearDownClass(cls):
        after=production_hashes()
        if after!=BEFORE:raise AssertionError('Production changed during held-out evaluation')
        out=Path(os.environ.get('CONTRACT_REVIEW_TEST_DIR','.') )/'final-heldout-results.json'
        out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps({'samples':2,'production_unchanged':True,'production_hashes':after,'external_model_eval':False},indent=2),encoding='utf-8')
if __name__=='__main__':unittest.main(verbosity=2)
