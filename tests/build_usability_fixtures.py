"""Additional fresh, synthetic first-review candidates and UI flows."""
import copy,json,os,sys,subprocess,zipfile
from pathlib import Path
from xml.sax.saxutils import escape
SKILL=Path(__file__).resolve().parents[1];sys.path[:0]=[str(SKILL/'scripts'),str(SKILL/'tests')]
from test_plan_quality import contract,action,plan
from plan_quality import CHECKS
ROOT=Path(os.environ['CONTRACT_REVIEW_TEST_DIR'])/'usability-browser';ROOT.mkdir(parents=True,exist_ok=True)
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def write(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
def run(name,*args):subprocess.run([sys.executable,'-B','-X','utf8',str(SKILL/'scripts'/name),*map(str,args)],check=True,capture_output=True)
task=ROOT/'interactive';source=task/'synthetic.docx';task.mkdir(parents=True,exist_ok=True)
paragraphs=['政府采购服务合同（合成）','\t履约记录：资料收到日期待填写。','付款仍按验收后30日，日期记录不单独改变验收条件。','服务商承担一年质保。\t验收另行出具书面记录。']
body=''.join('<w:p><w:r>'+''.join('<w:tab/>' if part=='\t' else '<w:t xml:space="preserve">'+escape(part)+'</w:t>' for part in __import__('re').split('(\t)',text))+'</w:r></w:p>' for text in paragraphs)
with zipfile.ZipFile(source,'w') as z:
 z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'+body+'</w:body></w:document>')
 z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
 z.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
run('extract_contract.py','--input',source,'--task-dir',task);c=read(task/'contract.json')
def raw(id,edits):
 p=plan(c,edits);p['plan_id']=id;p['reason']='合成协议样本：按明确声明的事实字段/谈判方案修订，验证数据和操作流程。';return p
e=action(c,'b0002','\t履约记录：资料收到日期为{{field:received}}。');t=raw('fact-record',[e]);t['questions']=[{'id':'received_fact','question':'填入已核实的资料收到日期。','required':True}];t['field_bindings']=[{'id':'received','question_id':'received_fact','edit_ids':[e['edit_id']],'kind':'date','semantic_effect':'fact_only'}]
choices=[]
for days in ['20','45']:
 text=c['blocks'][2]['text'];start=text.index('30日');p=raw('payment-'+days,[action(c,'b0003',days+'日',start=start,end=start+3)]);p['label']='建议'+days+'日付款';p['business_terms']=[{'id':'deadline','kind':'negotiation','value':days+'日','proposed':True,'confirmed':False,'source':'合成谈判建议，不是原合同事实或法定期限。'}];choices.append(p)
text=c['blocks'][1]['text'];start=text.index('履约记录');same=raw('same-node-mark',[action(c,'b0002','履约事实记录',start=start,end=start+4)])
missing=raw('missing-condition',[dict(action(c,'b0004',None),draft_pending=True)]);missing['questions']=[{'id':'address','question':'请提供真实服务地点。','required':True},{'id':'scope','question':'请确认服务范围。','required':True}]
def risk(id,title,sev,candidates,quote):
 for p in candidates:p['risk_id']=id
 return {'risk_id':id,'title':title,'severity':sev,'category':'条款约定不明确','conclusion':title,'explanation':'合成样本，不是法律意见。','recommendation':'查看拟议文本和条件，确认后应用。','evidence':[{'block_id':candidates[0]['edits'][0]['target_node_id'],'quote':quote}],'suggestion':{'candidates':candidates}}
draft={'contract_type':'政府采购合同（合成）','scope_limitation':'显式金标准测试，未调用独立模型。','contract_analysis':{'edges':[],'obligations':[]},'risks':[
 risk('analysis-date','签收事实需填写','medium',[t],paragraphs[1]),risk('analysis-payment','付款谈判选择','high',choices,'30日'),risk('analysis-label','同段另一风险','low',[same],'履约记录'),risk('analysis-missing','服务信息缺失','medium',[missing],paragraphs[3])]}
write(task/'review_draft.json',draft);run('validate_review.py','--task-dir',task,'--index-dir',SKILL/'law_index')
requests={r['plan_id']:r for r in read(task/'quality_requests.json')['requests']}
for r in draft['risks']:
 for i,p in enumerate(r['suggestion']['candidates']):
  req=requests[p['plan_id']];p=copy.deepcopy(req['raw_plan']);checks={k:{'result':'pass','reason':'合成金标准明确指定此方案的适用范围，验证协议与真实修改结果，不代表独立法律评测。'} for k in CHECKS}
  if p['plan_id']=='missing-condition':checks['business_complete']={'result':'manual','reason':'真实地点和范围缺失。'};checks['removes_cause']={'result':'manual','reason':'尚未生成正式条款。'}
  p['semantic_review']={'reviewer':'WorkBuddy','reviewed_at':'synthetic-golden','plan_fingerprint':req['plan_fingerprint'],'scope_node_hashes':req['scope_node_hashes'],'checked_node_ids':list(req['scope_node_hashes']),'checks':checks}
  if p.get('field_bindings'):p['semantic_review']['field_policy']={'approved':True,'field_ids':['received'],'reason':'日期仅记载签收事实，验收和付款机制不变。'}
  r['suggestion']['candidates'][i]=p
write(task/'review_draft.json',draft);run('finalize_review.py','--task-dir',task)
assert read(task/'review_result.json')['review_meta']['suggestion_coverage']['incomplete_count']==0
print(json.dumps({'output':str(ROOT),'fresh_candidates':5},ensure_ascii=False))
