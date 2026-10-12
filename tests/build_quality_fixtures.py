"""Reproducible synthetic UI fixtures, standard library only. No model call."""
import copy,json,os,subprocess,sys,tempfile,zipfile
from pathlib import Path
from xml.sax.saxutils import escape
SKILL=Path(__file__).resolve().parents[1];sys.path.insert(0,str(SKILL/'scripts'))
from plan_quality import digest
ROOT=Path(os.environ.get('CONTRACT_REVIEW_TEST_DIR') or tempfile.mkdtemp(prefix='quality-tests-'))
ROOT.mkdir(parents=True,exist_ok=True)
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
write=lambda p,x:(p.parent.mkdir(parents=True,exist_ok=True),p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8'))
def run(name,*args):
    p=subprocess.run([sys.executable,'-B','-X','utf8',str(SKILL/'scripts'/name),*map(str,args)],capture_output=True,encoding='utf-8',check=True);return p.stdout
results=[]
for sample in read(SKILL/'tests/fixtures/quality_cases.json')['cases']:
    task=ROOT/'quality-browser'/sample['case_id'];task.mkdir(parents=True,exist_ok=True)
    if sample['source_format']=='docx':
        source=task/'synthetic.docx';paragraphs=''.join('<w:p><w:r><w:t xml:space="preserve">'+escape(text)+'</w:t></w:r></w:p>' for text in sample['paragraphs'])
        xml='<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'+paragraphs+'</w:body></w:document>'
        with zipfile.ZipFile(source,'w') as z:
            z.writestr('word/document.xml',xml)
            z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
            z.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
    else:
        source=task/'synthetic.txt';source.write_text('\n'.join(sample['paragraphs']),encoding='utf-8')
    run('extract_contract.py','--input',source,'--task-dir',task)
    raw=copy.deepcopy(sample['raw_plan']);raw.pop('semantic_review',None)
    risk={'risk_id':'draft-risk','title':'合成条款质量核查','category':'条款约定不明确','severity':'medium','conclusion':raw['reason'],'explanation':raw['reason'],
          'evidence':[{'block_id':e['target_node_id'],'quote':e['expected_node_text']} for e in raw['edits']],
          'legal_basis':[],'recommendation':'对照已确认条件和关联计划核查。','edit_plan':raw}
    draft={'contract_type':sample['contract_type'],'scope_limitation':'合成金标准协议样本；语义审查记录为明确测试数据，非独立模型或律师评测。','risks':[risk],'contract_analysis':sample['analysis']}
    write(task/'review_draft.json',draft);run('validate_review.py','--task-dir',task,'--index-dir',SKILL/'law_index')
    request=read(task/'quality_requests.json')['requests'][0];raw=copy.deepcopy(request['raw_plan'])
    raw['semantic_review']={'reviewer':'WorkBuddy','reviewed_at':'synthetic-golden-receipt','plan_fingerprint':request['plan_fingerprint'],
           'scope_node_hashes':request['scope_node_hashes'],'checked_node_ids':list(request['scope_node_hashes']),'checks':sample['semantic_checks']}
    draft['risks'][0]['edit_plan']=raw;write(task/'review_draft.json',draft);run('validate_review.py','--task-dir',task,'--index-dir',SKILL/'law_index')
    compiled=read(task/'verified_review.json')['risks'][0]['edit_plan'];assert compiled['can_apply']==sample['expected_can_apply'],sample['case_id']
    run('render_report.py','--task-dir',task);results.append({'case':sample['case_id'],'passed':True,'can_apply':compiled['can_apply'],'readiness':compiled['readiness']})
legacy=ROOT/'quality-browser/legacy';legacy.mkdir(parents=True,exist_ok=True);source=legacy/'legacy.txt';source.write_text('旧版合成合同\n付款为100元。',encoding='utf-8');run('extract_contract.py','--input',source,'--task-dir',legacy)
write(legacy/'review_draft.json',{'contract_type':'通用合同','scope_limitation':'旧JSON兼容测试。','risks':[{'risk_id':'old','title':'旧建议','category':'条款约定不明确','severity':'low','conclusion':'旧建议需核验。','explanation':'无修改计划和语义记录。','evidence':[{'block_id':'b0002','quote':'付款为100元。'}],'recommendation':'重新生成计划。','proposed_clause':'旧版建议：付款为【金额】元。'}]})
run('validate_review.py','--task-dir',legacy,'--index-dir',SKILL/'law_index');run('render_report.py','--task-dir',legacy)
write(ROOT/'quality-fixture-results.json',{'results':results,'fixtures_digest':digest(read(SKILL/'tests/fixtures/quality_cases.json'))})
print(json.dumps({'root':str(ROOT),'matrix_cases':len(results),'legacy_fixture':True},ensure_ascii=False))
