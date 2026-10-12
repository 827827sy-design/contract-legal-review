/* Real Edge/Chromium acceptance test. Playwright is a development dependency. */
const {chromium}=require('playwright');
const assert=require('assert/strict'),fs=require('fs'),path=require('path'),crypto=require('crypto');
const {pathToFileURL}=require('url');
const {spawnSync}=require('child_process');
const skillRoot=path.resolve(__dirname,'..');
function py(script,...args){const result=spawnSync(process.env.REVIEW_PYTHON||'python',['-B','-X','utf8',path.join(skillRoot,'scripts',script),...args],{encoding:'utf8'});assert.equal(result.status,0,result.stdout+result.stderr);return result.stdout;}
const configuredRoot=process.env.CONTRACT_REVIEW_TEST_DIR;
if(!configuredRoot)throw Error('Set CONTRACT_REVIEW_TEST_DIR to test_v2.py fixture directory.');
const pointer=path.join(configuredRoot,'latest-fixtures.txt');
const root=fs.existsSync(pointer)?fs.readFileSync(pointer,'utf8'):configuredRoot;
const url=pathToFileURL(path.join(root,'task','contract_review.html')).href;
const fileHash=()=>crypto.createHash('sha256').update(fs.readFileSync(path.join(root,'original.docx'))).digest('hex');
const initialHash=fileHash(),checks=[],errors=[];
const check=(name,condition)=>{assert.ok(condition,name);checks.push(name)};
const snap=p=>p.evaluate(()=>window.reviewEditor.export());
const value=async(p,id)=>(await snap(p)).current_nodes[id];
async function open(context,href=url){const p=await context.newPage();p.on('pageerror',e=>errors.push(e.message));p.on('dialog',d=>d.accept());await p.goto(href);await p.waitForFunction(()=>Boolean(window.reviewEditor));return p;}
async function manual(p,id,text){await p.locator('#editEnabled').check();await p.locator(`[data-node="${id}"]`).click();await p.locator('#editText').fill(text);await p.locator('#applyEdit').click();}
async function risk(p,title){const card=p.locator('.card').filter({has:p.locator('h3',{hasText:title})});await card.locator(':scope > summary').click();return card;}
(async()=>{
 const browser=await chromium.launch({channel:process.env.REVIEW_BROWSER_CHANNEL||'msedge',headless:true});
 const context=await browser.newContext({viewport:{width:1500,height:1050},acceptDownloads:true});
 let p=await open(context);
 check('no template injection',await p.evaluate(()=>!window.__injected)&&await p.locator('img').count()===0);
 check('neutral default',(await snap(p)).perspective.mode==='neutral');
 check('complex cells preserved readonly',await p.locator('[data-node="b0006-r2-c0"] .readonly-note').count()===1);
 let card=await risk(p,'重复原文的第二处');await card.locator('[data-apply]').click();
 check('AI suggestion picks exact second occurrence',await p.locator('#targetNode').inputValue()==='b0004');
 await p.locator('#applyEdit').click();
 check('duplicate first occurrence unchanged',await value(p,'b0003')==='付款金额为100元。');
 check('AI suggestion actually applied',await value(p,'b0004')==='付款金额为120元。');
 check('replacement displays red deletion and green insertion',await p.locator('[data-node="b0004"] del').count()>0&&await p.locator('[data-node="b0004"] ins').count()>0);
 await p.locator('#displayMode').selectOption('clean');check('clean and revision mode share state',(await p.locator('[data-node="b0004"]').textContent()).includes('付款金额为120元。')&&await p.locator('[data-node="b0004"] del').count()===0);await p.locator('#displayMode').selectOption('revision');
 const beforeUndo=(await snap(p)).history.length;await p.locator('#undoBtn').click();check('undo restores original',await value(p,'b0004')==='付款金额为100元。');await p.locator('#redoBtn').click();check('redo restores revision and retains history',await value(p,'b0004')==='付款金额为120元。'&&(await snap(p)).history.length>beforeUndo);
 await manual(p,'b0004','付款金额为150元。');await manual(p,'b0004','付款金额为160元。');check('continuous changes in same paragraph',await value(p,'b0004')==='付款金额为160元。');
 await manual(p,'b0004','');check('text deletion supported',await value(p,'b0004')==='');await p.locator('#undoBtn').click();check('deletion undo',await value(p,'b0004')==='付款金额为160元。');
 check('modified risk does not retain stale original highlight',await p.locator('[data-node="b0004"] .mk').count()===0);
 await p.locator('#editEnabled').uncheck();
 card=p.locator('.card').filter({has:p.locator('h3',{hasText:'重复原文的第二处'})});await card.locator('[data-apply]').click();check('conflicting new advice requires manual target',(await p.locator('#editorStatus').textContent()).includes('原文已修改')&&await p.locator('#targetNode').inputValue()==='');await p.locator('#cancelEdit').click();
 card=await risk(p,'缺失条款插入位置');await card.locator('[data-apply]').click();check('missing clause has table insertion anchor',await p.locator('#targetNode').inputValue()==='b0006-r2-c0');await p.locator('#applyEdit').click();check('AI missing clause inserted as independent paragraph',Object.values((await snap(p)).current_nodes).includes('新增合成条款，不涉及真实主体。'));
 await manual(p,'b0006-r1-c1','新单元格 🧾');check('common table cell revision',await value(p,'b0006-r1-c1')==='新单元格 🧾');
 await p.locator('[data-node="b0006-r2-c0"]').click();check('merged cell editing blocked',await p.locator('#editPanel').isHidden());
 await p.locator('[data-node="b0005"]').click();await p.locator('#editText').fill('含有 🧾 新字符。');await p.locator('#applyEdit').click();check('Unicode positions preserved',await value(p,'b0005')==='含有 🧾 新字符。');
 await p.locator('#docSearch').fill('付款');await p.waitForTimeout(250);check('search remains usable',await p.locator('mark.search-hit').count()>0);await p.locator('#docSearch').fill('');
 await p.locator('#editEnabled').uncheck();card=await risk(p,'企业偏好');await card.locator('[data-edit-suggestion]').click();await p.locator('#editText').fill('甲方：合成甲公司【住所地待确认】');await p.locator('#applyEdit').click();check('edit suggestion then apply is real',await value(p,'b0002')==='甲方：合成甲公司【住所地待确认】；乙方：合成乙公司');
 card=await risk(p,'恶意内容应作为数据');await card.locator('[data-reject]').click();check('not adopted decision persists',Object.values((await snap(p)).risk_decisions).some(x=>x.decision==='rejected'));
 await p.locator('#workflowTools').evaluate(e=>e.open=true);
 const operationsBefore=(await snap(p)).operations.length;
 for(const mode of ['party_a','party_b','custom']){await p.locator('#perspectiveSelect').selectOption(mode);await p.locator('#perspectiveFocus').fill('回款');await p.locator('#perspectiveRequest').click();check('real '+mode+' review request, no fake review',(await p.locator('#handoffText').inputValue()).includes('浏览器尚未完成重新审查')&&(await snap(p)).operations.length===operationsBefore);}
 await p.locator('#confirmEdits').click();check('explicit confirmation recorded',(await snap(p)).operations.filter(o=>o.status==='active').every(o=>o.decision==='confirmed'));
 await p.locator('#finishEditing').click();check('finish blocked while unsaved',(await p.locator('#completionText').textContent()).includes('未保存'));
 const wait=p.waitForEvent('download');await p.locator('#downloadRevisions').click();const downloaded=await wait;const revisionFile=path.join(root,'browser-revisions.json');await downloaded.saveAs(revisionFile);
 check('fallback downloads actual valid JSON',JSON.parse(fs.readFileSync(revisionFile,'utf8')).schema_version===2);
 check('download does not falsely claim saved',(await p.locator('#saveState').textContent()).includes('未保存'));
 await p.locator('#confirmDownload').click();check('explicit download confirmation recorded',!(await p.locator('#saveState').textContent()).includes('未保存'));
 await p.locator('#finishEditing').click();check('Word handoff says new file and confirmed changes',(await p.locator('#handoffText').inputValue()).includes('只应用已确认')&&(await p.locator('#handoffText').inputValue()).includes('不要覆盖原文件'));
 await p.locator('#rereviewRequest').click();check('re-review request preserves old history',(await p.locator('#handoffText').inputValue()).includes('保留全部修订与审查历史'));
 const final=await snap(p);await p.screenshot({path:path.join(root,'desktop-editor.png'),fullPage:true});await p.close();
 // Apply the actual browser-downloaded log in Python, then build a fresh review fixture.
 py('revisions.py','validate','--task-dir',path.join(root,'task'),'--revisions',revisionFile);
 const word=path.join(root,'browser-modified.docx');py('apply_docx.py','--original',path.join(root,'original.docx'),'--task-dir',path.join(root,'task'),'--revisions',revisionFile,'--output',word);check('browser JSON is consumed by actual Python Word export',fs.existsSync(word));
 const cross=path.join(root,'cross-rereview');py('revisions.py','materialize','--task-dir',path.join(root,'task'),'--revisions',revisionFile,'--out-dir',cross);
 py('prepare_review.py','--task-dir',cross,'--perspective','party_a','--config-dir',path.join(root,'pref-skip'));
 const template=JSON.parse(fs.readFileSync(path.join(root,'task','review_draft.json'),'utf8')).risks[0];
 const newRisks=[1,2,3].map(i=>({...template,risk_id:'new-'+i,title:'复审合成风险'+i,evidence:[{block_id:'b0004',quote:'付款金额为160元。'}]}));
 fs.writeFileSync(path.join(cross,'review_draft.json'),JSON.stringify({contract_type:'买卖合同',scope_limitation:'纯合成数据，仅测试复审接口，不代表 AI 法律判断。',risks:newRisks}));
 py('validate_review.py','--task-dir',cross,'--index-dir',path.join(skillRoot,'law_index'));py('render_report.py','--task-dir',cross);
 const reviewed=await open(context,pathToFileURL(path.join(cross,'contract_review.html')).href);
 check('fresh re-review preserves all edit operations',(await snap(reviewed)).operations.length===final.operations.length);
 check('fresh re-review keeps original-relative red green tracks',await reviewed.locator('[data-node="b0004"] del').count()>0&&await reviewed.locator('[data-node="b0004"] ins').count()>0);
 check('fresh re-review validates current positions',await reviewed.locator('[data-node="b0004"] .mk').count()>0&&await reviewed.locator('[data-node="b0004"] .stale-note').count()===0);
 check('fresh party A report shows true perspective',(await reviewed.locator('#demoLabel').textContent()).includes('甲方视角'));
 const third=reviewed.locator('#card-R003');await third.locator(':scope > summary').click();check('new risk IDs do not inherit old rejection',!(await third.locator('.risk-origin').textContent()).includes('暂不采纳'));
 await reviewed.close();
 p=await open(context);await p.locator('#workflowTools').evaluate(e=>e.open=true);await p.locator('#importRevisions').setInputFiles(revisionFile);await p.waitForFunction(()=>document.querySelector('#editorStatus').textContent.includes('编辑状态与历史已恢复')||document.querySelector('#editorStatus').textContent.includes('导入失败'));
 console.log('Import status:',await p.locator('#editorStatus').textContent());
 check('close reopen import restores state',await value(p,'b0004')==='付款金额为160元。'&&(await snap(p)).operations.length===final.operations.length);
 const bad=JSON.parse(fs.readFileSync(revisionFile,'utf8'));bad.contract.file_sha256='bad';const badPath=path.join(root,'wrong-contract.json');fs.writeFileSync(badPath,JSON.stringify(bad));await p.locator('#importRevisions').setInputFiles(badPath);await p.waitForFunction(()=>document.querySelector('#editorStatus').textContent.includes('不匹配'));
 check('wrong contract import blocked',(await p.locator('#editorStatus').textContent()).includes('不匹配')&&await value(p,'b0004')==='付款金额为160元。');
 const malformed=JSON.parse(fs.readFileSync(revisionFile,'utf8'));malformed.operations.find(o=>o.status==='active').before_text='bad';fs.writeFileSync(badPath,JSON.stringify(malformed));await p.locator('#importRevisions').setInputFiles(badPath);await p.waitForFunction(()=>document.querySelector('#editorStatus').textContent.includes('导入失败')&&!document.querySelector('#editorStatus').textContent.includes('不匹配'));check('conflicting operation import blocked',(await p.locator('#editorStatus').textContent()).includes('导入失败'));
 await manual(p,'b0004','付款金额为170元。');await p.close();p=await open(context);await p.locator('#workflowTools').evaluate(e=>e.open=true);await p.locator('#restoreCache').click();check('temporary browser recovery preserves unsaved edit',await value(p,'b0004')==='付款金额为170元。'&&(await p.locator('#saveState').textContent()).includes('未保存'));
 await p.locator('#restoreOriginal').click();check('restore original retains history',await value(p,'b0004')==='付款金额为100元。'&&(await snap(p)).operations.length===final.operations.length+1);
 await p.close();
 // Fault injection tests the real save handler's failure path; no native-dialog claim.
 const failContext=await browser.newContext();await failContext.addInitScript(()=>{window.showSaveFilePicker=async()=>({name:'revisions.json',createWritable:async()=>({write:async()=>{},close:async()=>{throw Error('injected disk write failure')}})});});p=await open(failContext);await manual(p,'b0004','保存失败测试');await p.locator('#workflowTools').evaluate(e=>e.open=true);await p.locator('#saveNative').click();await p.waitForFunction(()=>document.querySelector('#editorStatus').textContent.includes('injected disk write failure'));check('failed write never claims saved',(await p.locator('#editorStatus').textContent()).includes('保存失败')&&(await p.locator('#saveState').textContent()).includes('未保存'));await failContext.close();
 const fallbackContext=await browser.newContext({viewport:{width:390,height:844},acceptDownloads:true});await fallbackContext.addInitScript(()=>{window.showSaveFilePicker=undefined;});p=await open(fallbackContext);await p.locator('#workflowTools').evaluate(e=>e.open=true);check('unsupported local-write API has download fallback',await p.locator('#saveNative').isDisabled()&&await p.locator('#downloadRevisions').isVisible());await p.screenshot({path:path.join(root,'mobile-editor.png'),fullPage:true});await fallbackContext.close();
 const legacy=await open(context,pathToFileURL(path.join(root,'legacy','contract_review.html')).href);check('V1 data renders in upgraded editor',await legacy.locator('.card').count()===4);await legacy.close();
 const standalone=await context.newPage();standalone.on('pageerror',e=>errors.push(e.message));await standalone.goto(pathToFileURL(path.join(skillRoot,'tests','fixtures','v1_report.html')).href);check('original standalone V1 report still works',await standalone.locator('.card').count()===3);await standalone.close();
 check('original DOCX remains byte identical',initialHash===fileHash());check('no browser JavaScript errors',errors.length===0);
 fs.writeFileSync(path.join(root,'browser_results.json'),JSON.stringify({tests:checks.length,checks,errors,browser:await browser.version(),native_picker_manual_test:false},null,2));
 console.log(JSON.stringify({passed:checks.length,errors,browser:await browser.version()}));await browser.close();
})().catch(error=>{console.error(error);process.exit(1)});
