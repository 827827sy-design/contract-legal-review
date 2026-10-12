"""Executable backend acceptance tests; all data is synthetic and isolated."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid
import zipfile
from html.parser import HTMLParser

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from revision_core import document_for,replay,contract_from_nodes
from check_amounts import financial_number,check

TEST_ROOT=Path(os.environ.get('CONTRACT_REVIEW_TEST_DIR') or tempfile.mkdtemp(prefix='contract-v2-'))
TEST=TEST_ROOT/('run-'+uuid.uuid4().hex[:12])
TEST.mkdir(parents=True,exist_ok=True)
(TEST_ROOT/'latest-fixtures.txt').write_text(str(TEST),encoding='utf-8')
def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def write(path,data):Path(path).parent.mkdir(parents=True,exist_ok=True);Path(path).write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
def run(script,*args,ok=True):
    result=subprocess.run([sys.executable,'-B','-X','utf8',str(ROOT/'scripts'/script),*map(str,args)],capture_output=True,encoding='utf-8')
    if ok and result.returncode:raise AssertionError(result.stdout+result.stderr)
    if not ok and not result.returncode:raise AssertionError('Expected rejection')
    return result.stdout

def fixture():
    source=TEST/'original.docx';task=TEST/'task'
    paragraphs=['合成采购合同','甲方：合成甲公司；乙方：合成乙公司','付款金额为100元。','付款金额为100元。','含有 🧾 中文字符。']
    p=lambda t:'<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>'+t+'</w:t></w:r></w:p>'
    table='<w:tbl><w:tr><w:tc>'+p('名称')+'</w:tc><w:tc>'+p('值')+'</w:tc></w:tr><w:tr><w:tc>'+p('交付项')+'</w:tc><w:tc>'+p('旧单元格')+'</w:tc></w:tr><w:tr><w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr>'+p('合并单元格')+'</w:tc></w:tr></w:tbl>'
    xml='<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'+''.join(p(t) for t in paragraphs)+table+'<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr></w:body></w:document>'
    with zipfile.ZipFile(source,'w')as z:
        z.writestr('word/document.xml',xml);z.writestr('unchanged.bin',b'original immutable asset')
        z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="bin" ContentType="application/octet-stream"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
    run('extract_contract.py','--input',source,'--task-dir',task)
    run('prepare_review.py','--task-dir',task,'--contract-type','买卖合同','--config-dir',TEST/'preferences')
    article=read(ROOT/'law_index'/'minfadian.json')['articles'][468]
    common={'category':'条款约定不明确','severity':'low','conclusion':'合成测试，不作法律判断。','explanation':'仅检查功能。','recommendation':'请核对修改位置。','legal_basis':[{'law_id':'minfadian','article_no':article['article_no'],'text':article['text']}]}
    draft={'contract_type':'买卖合同','scope_limitation':'固定三法快照，仅合成验收。','risks':[
        {**common,'risk_id':'D01','title':'重复原文的第二处','evidence':[{'block_id':'b0004','quote':'付款金额为100元。'}],'proposed_clause':'付款金额为120元。'},
        {**common,'risk_id':'D02','title':'缺失条款插入位置','evidence':[{'no_text':True,'suggested_block_id':'b0006'}],'proposed_clause':'新增合成条款，不涉及真实主体。'},
        {**common,'risk_id':'D03','title':'企业偏好','risk_source':'negotiation','preference_id':'P01','legal_basis':[],'evidence':[{'block_id':'b0002','quote':'甲方：合成甲公司'}],'proposed_clause':'甲方：合成甲公司【住所地待填写】'},
        {**common,'risk_id':'D04','title':'恶意内容应作为数据','recommendation':'--><img src="x" onerror="window.__injected=1"><!-- __EDITOR_JS__','evidence':[{'block_id':'b0005','quote':'含有 🧾 中文字符。'}],'proposed_clause':'仅作转义检查。'}]}
    write(task/'review_draft.json',draft);run('validate_review.py','--task-dir',task,'--index-dir',ROOT/'law_index');run('render_report.py','--task-dir',task)
    return source,task

SOURCE,TASK=fixture()
CONTRACT=read(TASK/'contract.json')
DOC=document_for(CONTRACT)
def revisions():return {'schema_version':2,'contract':DOC['identity'],'base_nodes':{n['node_id']:n['text'] for n in DOC['original_nodes']},'operations':[],'history':[],'redo_stack':[],'risk_decisions':{},'perspective':{'mode':'neutral','focus':''},'current_nodes':{n['node_id']:n['text'] for n in DOC['original_nodes']}}
def replace(value,node_id,text,decision='confirmed'):
    before=value['current_nodes'][node_id];op={'id':'op-'+str(len(value['operations'])),'type':'replace','node_id':node_id,'start':0,'end':len(before),'removed_text':before,'inserted_text':text,'before_text':before,'after_text':text,'source':'manual','risk_id':None,'perspective':{'mode':'neutral'},'reason':'合成测试','time':'2026-10-12T00:00:00Z','status':'active','decision':decision}
    value['operations'].append(op);value['history'].append({'action':'apply','revision_id':op['id']});value['current_nodes'][node_id]=text
def insert(value):
    op={'id':'insert-1','type':'insert_node','node_id':'n-test','anchor_node_id':'b0006-r2-c0','before_text':'','after_text':'新增确认条款。','start':0,'end':0,'removed_text':'','inserted_text':'新增确认条款。','source':'ai','risk_id':'R002','perspective':{'mode':'party_a'},'reason':'补充条款','time':'2026-10-12T00:00:00Z','status':'active','decision':'confirmed'}
    value['operations'].append(op);value['history'].append({'action':'apply','revision_id':op['id']});value['current_nodes']['n-test']=op['after_text']

class Acceptance(unittest.TestCase):
    def test_preferences_first_and_second_use(self):
        directory=TEST/'pref-roundtrip';first=json.loads(run('preferences.py','status','--config-dir',directory));self.assertFalse(first['configured']);self.assertFalse(directory.exists())
        rule={'id':'P01','kind':'negotiation','rule':'住所地争议解决偏好','contract_types':['买卖合同'],'basis':['用户明确说明']};write(TEST/'preference.json',rule)
        run('preferences.py','upsert','--config-dir',directory,'--input',TEST/'preference.json',ok=False)
        run('preferences.py','upsert','--config-dir',directory,'--input',TEST/'preference.json','--confirmed')
        second=json.loads(run('preferences.py','context','--config-dir',directory,'--contract-type','买卖合同'));self.assertTrue(second['configured']);self.assertEqual(len(second['preferences']),1)
        self.assertEqual(json.loads(run('preferences.py','context','--config-dir',directory,'--contract-type','劳动合同'))['preferences'],[])
        rule['rule']='更新偏好';write(TEST/'preference.json',rule);run('preferences.py','upsert','--config-dir',directory,'--input',TEST/'preference.json','--confirmed')
        for action in ['disable','enable','delete']:run('preferences.py',action,'--config-dir',directory,'--id','P01','--confirmed')
        self.assertEqual(json.loads(run('preferences.py','list','--config-dir',directory))['preferences'],[])
        run('preferences.py','init','--skip','--confirmed','--config-dir',TEST/'pref-skip');self.assertTrue(read(TEST/'pref-skip'/'preferences.json')['configured'])

    def test_perspectives_preserve_history(self):
        old=(TASK/'review_result.json').read_bytes()
        for perspective in ['neutral','party_a','party_b','custom']:
            result=json.loads(run('prepare_review.py','--task-dir',TASK,'--perspective',perspective,'--focus','回款','--new-run','--config-dir',TEST/'pref-skip'))
            context=read(Path(result['task_dir'])/'review_context.json');self.assertEqual(context['perspective']['mode'],perspective);self.assertTrue(context['party_candidates']['party_a'])
        self.assertEqual(old,(TASK/'review_result.json').read_bytes())

    def test_amount_arithmetic(self):
        self.assertEqual(str(financial_number('人民币壹万零贰元叁角肆分')),'10002.34')
        self.assertEqual(check({'nature':'price','numeric':113,'uppercase':'壹佰壹拾叁元整','net':100,'rate':'0.13','tax':13,'gross':113}),[])
        self.assertTrue(check({'numeric':100,'uppercase':'壹佰壹拾元整'}))
        self.assertEqual(check({'nature':'deposit','numeric':100,'uppercase':'壹佰元整'}),[])
        self.assertTrue(check({'nature':'price','net':100}))

    def test_unicode_sequential_and_conflicts(self):
        value=revisions();replace(value,'b0005','含有 🧾 第二次。');replace(value,'b0005','含有 🧾 第三次。')
        self.assertEqual(next(n['text'] for n in replay(DOC,value) if n['node_id']=='b0005'),'含有 🧾 第三次。')
        bad=copy.deepcopy(value);bad['operations'][1]['before_text']='错误原文'
        with self.assertRaises(ValueError):replay(DOC,bad)
        bad=copy.deepcopy(value);bad['contract']['file_sha256']='wrong'
        with self.assertRaises(ValueError):replay(DOC,bad)
        bad=copy.deepcopy(value);bad['current_nodes']['b0005']='篡改当前稿'
        with self.assertRaises(ValueError):replay(DOC,bad)

    def test_inactive_history_and_redo_stack_are_validated(self):
        value=revisions();replace(value,'b0004','付款金额为140元。');value['operations'][0]['status']='undone';value['redo_stack']=[value['operations'][0]['id']];value['current_nodes']=dict(value['base_nodes']);replay(DOC,value)
        bad=copy.deepcopy(value);bad['operations'][0]['end']=999
        with self.assertRaises(ValueError):replay(DOC,bad)
        bad=copy.deepcopy(value);bad['redo_stack']=[]
        with self.assertRaises(ValueError):replay(DOC,bad)
        bad=copy.deepcopy(value);bad['operations'][0].update({'before_text':'别的合法字符串','start':0,'end':7,'removed_text':'别的合法字符串','inserted_text':'付款金额为140元。','after_text':'付款金额为140元。'})
        with self.assertRaises(ValueError):replay(DOC,bad)

    def test_resolution_ids_follow_renumbering(self):
        target=TEST/'resolution';write(target/'contract.json',CONTRACT)
        draft=read(TASK/'review_draft.json');draft['risks']=draft['risks'][:1];draft['risk_resolution']=[{'prior_risk_id':'R001','status':'remaining','current_risk_id':'D01'}]
        write(target/'review_draft.json',draft);run('validate_review.py','--task-dir',target,'--index-dir',ROOT/'law_index')
        result=read(target/'review_result.json');self.assertEqual(result['review_meta']['risk_resolution'][0]['current_risk_id'],result['risks'][0]['risk_id'])
    def test_complex_readonly_and_table_nodes(self):
        nodes={n['node_id']:n for n in DOC['original_nodes']};self.assertTrue(nodes['b0006-r1-c1']['editable']);self.assertFalse(nodes['b0006-r2-c0']['editable'])
        value=revisions();replace(value,'b0006-r2-c0','不应修改')
        with self.assertRaises(ValueError):replay(DOC,value)

    def test_confirmed_docx_export_and_original_safety(self):
        value=revisions();replace(value,'b0004','付款金额为120元。');replace(value,'b0006-r1-c1','新单元格');insert(value);path=TEST/'confirmed.json';write(path,value)
        before=hashlib.sha256(SOURCE.read_bytes()).hexdigest();out=TEST/'modified.docx'
        run('apply_docx.py','--original',SOURCE,'--task-dir',TASK,'--revisions',path,'--output',out)
        self.assertEqual(before,hashlib.sha256(SOURCE.read_bytes()).hexdigest())
        with zipfile.ZipFile(out)as z:self.assertEqual(z.read('unchanged.bin'),b'original immutable asset')
        extracted=TEST/'word-check';run('extract_contract.py','--input',out,'--task-dir',extracted);c=read(extracted/'contract.json')
        self.assertEqual(c['blocks'][2]['text'],'付款金额为100元。');self.assertEqual(c['blocks'][3]['text'],'付款金额为120元。');self.assertIn('新单元格',c['full_text']);self.assertIn('新增确认条款。',c['full_text'])
        run('apply_docx.py','--original',SOURCE,'--task-dir',TASK,'--revisions',path,'--output',SOURCE,ok=False)
        pending=revisions();replace(pending,'b0004','未确认稿',decision='pending');write(TEST/'pending.json',pending)
        run('apply_docx.py','--original',SOURCE,'--task-dir',TASK,'--revisions',TEST/'pending.json','--output',TEST/'blocked.docx',ok=False);self.assertFalse((TEST/'blocked.docx').exists())

    def test_materialize_and_rereview_history(self):
        value=revisions();replace(value,'b0004','付款金额为130元。',decision='pending');write(TEST/'review-revisions.json',value)
        target=TEST/'rereview';run('revisions.py','materialize','--task-dir',TASK,'--revisions',TEST/'review-revisions.json','--out-dir',target)
        self.assertEqual(read(target/'revisions.json'),value);self.assertEqual(read(target/'base_contract.json'),CONTRACT)
        current=read(target/'contract.json');self.assertEqual(current['blocks'][3]['text'],'付款金额为130元。')
        draft=read(TASK/'review_draft.json');draft['risks'][0]['evidence'][0]['quote']='付款金额为130元。';draft['risk_resolution']=[{'prior_risk_id':'R001','status':'remaining'}]
        write(target/'review_draft.json',draft);run('validate_review.py','--task-dir',target,'--index-dir',ROOT/'law_index');run('render_report.py','--task-dir',target)
        run('validate_review.py','--task-dir',target,'--index-dir',ROOT/'law_index');self.assertTrue(list((target/'history').glob('*/review_result.json')))
        html=(target/'contract_review.html').read_text(encoding='utf-8');self.assertIn('付款金额为130元。',html)

    def test_repeated_insertion_order_in_word(self):
        value=revisions()
        for index in range(3):
            op={'id':f'insert-{index}','type':'insert_node','node_id':f'n-sequence-{index}',
                'anchor_node_id':'n-sequence-1' if index==2 else 'b0004',
                'before_text':'','after_text':f'新增顺序{index}。','start':0,'end':0,'removed_text':'','inserted_text':f'新增顺序{index}。',
                'source':'manual','risk_id':None,'perspective':{'mode':'neutral'},'reason':'顺序验证','time':'2026-10-12T00:00:00Z','status':'active','decision':'confirmed'}
            value['operations'].append(op);value['current_nodes'][op['node_id']]=op['after_text']
        path=TEST/'insertions.json';write(path,value);out=TEST/'insertions.docx'
        run('apply_docx.py','--original',SOURCE,'--task-dir',TASK,'--revisions',path,'--output',out)
        target=TEST/'insertions-extracted';run('extract_contract.py','--input',out,'--task-dir',target)
        expected=contract_from_nodes(CONTRACT,replay(DOC,value))['full_text']
        self.assertEqual(read(target/'contract.json')['full_text'],expected)

    def test_legacy_data_and_injection(self):
        legacy=TEST/'legacy';c=copy.deepcopy(CONTRACT);c.pop('nodes');c.pop('schema_version')
        for block in c['blocks']:
            for field in ['cells','locator','editable']:block.pop(field,None)
        write(legacy/'contract.json',c);write(legacy/'review_draft.json',read(TASK/'review_draft.json')['risks'])
        run('validate_review.py','--task-dir',legacy,'--index-dir',ROOT/'law_index');run('render_report.py','--task-dir',legacy)
        class Tags(HTMLParser):
            def __init__(self):super().__init__();self.images=[]
            def handle_starttag(self,tag,attrs):
                if tag=='img':self.images.append(attrs)
        parser=Tags();parser.feed((TASK/'contract_review.html').read_text(encoding='utf-8'));self.assertEqual(parser.images,[])
        self.assertIn('__EDITOR_JS__',(TASK/'contract_review.html').read_text(encoding='utf-8')) # user data stays literal

if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Acceptance))
    write(TEST/'backend_results.json',{'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'fixtures':str(TEST),'python':sys.version})
    print('FIXTURES='+str(TEST));sys.exit(not result.wasSuccessful())
