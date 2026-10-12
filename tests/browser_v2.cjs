const {chromium}=require('playwright'),fs=require('fs'),path=require('path'),crypto=require('crypto');
const {pathToFileURL}=require('url');const {spawnSync}=require('child_process');
const skillRoot=path.resolve(__dirname,'..');const testRoot=process.env.CONTRACT_REVIEW_TEST_DIR;if(!testRoot)throw Error('Set CONTRACT_REVIEW_TEST_DIR to the build_quality_fixtures.py output root.');const root=process.cwd(),fixtures=path.join(testRoot,'quality-browser'),resultDir=path.join(testRoot,'quality-browser-results');fs.mkdirSync(resultDir,{recursive:true});
const checks=[],errors=[];const check=(name,value)=>{checks.push({name,passed:!!value});if(!value)throw Error(name)};
const snap=p=>p.evaluate(()=>window.reviewEditor.export());
const py=(script,...args)=>spawnSync(process.env.REVIEW_PYTHON||'python',['-B','-X','utf8',path.join(skillRoot,'scripts',script),...args],{encoding:'utf8'});
async function open(context,name){const p=await context.newPage();p.on('pageerror',e=>errors.push(e.message));p.on('dialog',d=>d.accept());await p.goto(pathToFileURL(path.join(fixtures,name,'contract_review.html')).href);await p.waitForFunction(()=>Boolean(window.reviewEditor));return p;}
async function preview(p){await p.locator('.card').first().evaluate(e=>e.open=true);await p.locator('[data-apply]').first().click();}
async function download(p,filename){await p.locator('#workflowTools').evaluate(e=>e.open=true);const wait=p.waitForEvent('download');await p.locator('#downloadRevisions').click();const d=await wait;await d.saveAs(filename);await p.locator('#confirmDownload').click();}
(async()=>{
 const b=await chromium.launch({channel:'msedge',headless:true});
 try{
 const ctx=await b.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});
 const p=await open(ctx,'purchase_group');check('合成采购报告加载无错误',await p.locator('.card').count()===1);
 const before=await snap(p);await preview(p);
 check('关联修改完整预览两个位置',await p.locator('#planRows details').count()===2);
 check('预览含旧全文新全文和差异',await p.locator('#planRows pre').count()===4&&await p.locator('.plan-diff del').count()>0&&await p.locator('.plan-diff ins').count()>0);
 check('满足条件后才允许整组确认',await p.locator('#applyPlan').isEnabled());
 // Force a bad second position while maintaining the transport digest. The runtime
 // preflight must still reject the whole plan before any state is committed.
 await p.evaluate(async()=>{window.testOriginalPlan=JSON.parse(JSON.stringify(DATA.risks[0].edit_plan));const q=DATA.risks[0].edit_plan;q.edits[1].expected_original='错误的第二步原文';const payload={...q};delete payload.compiled_digest;q.compiled_digest=await ClausePlanTools.hash(payload);});
 await p.locator('#applyPlan').click();await p.waitForFunction(()=>document.querySelector('#editorStatus').textContent.includes('计划未应用'));
 check('任一步失败时全部文本和记录不变',JSON.stringify((await snap(p)).current_nodes)===JSON.stringify(before.current_nodes)&&(await snap(p)).operations.length===0);
 await p.evaluate(()=>{Object.assign(DATA.risks[0].edit_plan,window.testOriginalPlan)});await preview(p);await p.locator('#applyPlan').click();
 await p.waitForFunction(()=>window.reviewEditor.export().operations.length===2);
 const applied=await snap(p);check('实际两处文本统一为30日且无60日',!Object.values(applied.current_nodes).join('').includes('60日')&&applied.current_nodes.b0002.includes('30日')&&applied.current_nodes.b0003.includes('30日'));
 check('保留原有保修权利',applied.current_nodes.b0004===before.current_nodes.b0004);
 check('修改具有统一组且默认待确认',Object.keys(applied.plan_groups).length===1&&applied.operations.every(o=>o.group_id===applied.operations[0].group_id&&o.decision==='pending'));
 check('应用后风险仍需复审',Object.values(applied.risk_status).every(x=>x.status==='needs_re_review'));
 check('禁止重复应用同组',await p.locator('#applyPlan').isDisabled());
 await p.locator('#undoBtn').click();check('一次撤销恢复整组全部原文',JSON.stringify((await snap(p)).current_nodes)===JSON.stringify(before.current_nodes)&&(await snap(p)).operations.every(o=>o.status==='undone'));
 await p.locator('#redoBtn').click();check('一次恢复整组且保留历史',JSON.stringify((await snap(p)).current_nodes)===JSON.stringify(applied.current_nodes)&&(await snap(p)).history.length>applied.history.length);
 await p.locator('#closePlan').click();await p.locator('#displayMode').selectOption('clean');check('清洁模式保留相同当前稿',JSON.stringify((await snap(p)).current_nodes)===JSON.stringify(applied.current_nodes)&&await p.locator('#contractRoot del').count()===0);await p.locator('#displayMode').selectOption('revision');
 await p.locator('#editEnabled').check();await p.locator('[data-node="b0004"]').click();await p.locator('#editText').fill(before.current_nodes.b0004+' 🧾 测试备注。');await p.locator('#applyEdit').click();
 check('原有人工编辑及Unicode修订继续工作',(await snap(p)).current_nodes.b0004.includes('🧾')&&(await snap(p)).operations.at(-1).source==='manual');
 await p.locator('#undoBtn').click();check('人工修改与计划组可分别撤销',(await snap(p)).current_nodes.b0004===before.current_nodes.b0004&&(await snap(p)).operations.slice(0,2).every(o=>o.status==='active'));
 await p.locator('#redoBtn').click();await p.locator('[data-node="b0004"]').click();await p.locator('#editText').fill('');await p.locator('#applyEdit').click();check('文字删除仍工作',(await snap(p)).current_nodes.b0004==='');await p.locator('#undoBtn').click();
 await p.locator('[data-node="b0004"]').click();await p.locator('#insertClause').click();await p.locator('#editText').fill('新增合成测试条款，不是实际合同约定。');await p.locator('#applyEdit').click();
 check('原有独立条款插入继续工作',Object.values((await snap(p)).current_nodes).includes('新增合成测试条款，不是实际合同约定。'));
 await p.locator('#editEnabled').uncheck();await p.locator('#docSearch').fill('货款');await p.waitForTimeout(200);check('正文搜索仍工作',await p.locator('mark.search-hit').count()>0);await p.locator('#docSearch').fill('');
 await p.locator('#workflowTools').evaluate(e=>e.open=true);await p.locator('#finishEditing').click();check('未保存记录仍阻止完成编辑',(await p.locator('#completionText').textContent()).includes('未保存'));
 const pendingFile=path.join(resultDir,'pending.json');await download(p,pendingFile);const pending=JSON.parse(fs.readFileSync(pendingFile,'utf8'));
 check('实际下载包含整组快照和所有历史',Object.keys(pending.plan_groups).length===1&&pending.history.length>0);
 const validated=py('revisions.py','validate','--task-dir',path.join(fixtures,'purchase_group'),'--revisions',pendingFile);check('下载记录通过Python独立重放',validated.status===0);
 const p2=await open(ctx,'purchase_group');await p2.locator('#workflowTools').evaluate(e=>e.open=true);await p2.locator('#importRevisions').setInputFiles(pendingFile);await p2.waitForFunction(()=>window.reviewEditor.export().operations.length>0);
 check('重新打开导入恢复完整文本与组',JSON.stringify((await snap(p2)).current_nodes)===JSON.stringify(pending.current_nodes)&&Object.keys((await snap(p2)).plan_groups).length===1);
 const broken=JSON.parse(JSON.stringify(pending));broken.operations[0].status='undone';const brokenFile=path.join(resultDir,'partial-group.json');fs.writeFileSync(brokenFile,JSON.stringify(broken));
 await p2.locator('#importRevisions').setInputFiles(brokenFile);await p2.waitForFunction(()=>document.querySelector('#editorStatus').textContent.includes('导入失败'));
 check('部分撤销的组在导入时被拒绝',JSON.stringify((await snap(p2)).current_nodes)===JSON.stringify(pending.current_nodes));
 await p.locator('#confirmEdits').click();check('最终确认不宣称风险已解决',Object.values((await snap(p)).risk_status).every(x=>x.status==='needs_re_review'));
 const confirmedFile=path.join(resultDir,'confirmed.json');await download(p,confirmedFile);await p.locator('#finishEditing').click();check('完成编辑保留新Word交接流程',(await p.locator('#handoffText').inputValue()).includes('只应用已确认')&&(await p.locator('#handoffText').inputValue()).includes('不要覆盖原文件'));
 const source=JSON.parse(fs.readFileSync(path.join(fixtures,'purchase_group/contract.json'),'utf8'));const word=path.join(resultDir,'test-only-'+Date.now()+'.docx');
 const exported=py('apply_docx.py','--original',source.source_file,'--task-dir',path.join(fixtures,'purchase_group'),'--revisions',confirmedFile,'--output',word);check('浏览器真实组记录可供Word执行器使用',exported.status===0&&fs.existsSync(word));
 const extractedDir=path.join(resultDir,'word-content-check');const extracted=py('extract_contract.py','--input',word,'--task-dir',extractedDir);check('导出Word可重新解析',extracted.status===0);
 const wordText=JSON.parse(fs.readFileSync(path.join(extractedDir,'contract.json'),'utf8'));const confirmed=JSON.parse(fs.readFileSync(confirmedFile,'utf8'));
 const materialDir=path.join(resultDir,'word-expected-'+Date.now());const materialized=py('revisions.py','materialize','--task-dir',path.join(fixtures,'purchase_group'),'--revisions',confirmedFile,'--out-dir',materialDir);
 check('导出Word实际正文与确认稿一致',materialized.status===0&&wordText.full_text===JSON.parse(fs.readFileSync(path.join(materialDir,'contract.json'),'utf8')).full_text);
 check('合成原Word没有被改写',crypto.createHash('sha256').update(fs.readFileSync(source.source_file)).digest('hex')===source.file_sha256);
 const input=await open(ctx,'lease_blind');await preview(input);check('缺少业务条件时应用按钮禁用',await input.locator('#applyPlan').isDisabled());
 const originalInput=await snap(input);await input.locator('[data-plan-question="rent"]').fill('3000元');await input.locator('#savePlanDraft').click();
 check('补充输入只存草稿不改正文',JSON.stringify((await snap(input)).current_nodes)===JSON.stringify(originalInput.current_nodes)&&(await snap(input)).operations.length===0&&Object.values((await snap(input)).plan_drafts)[0].answers.rent==='3000元');
 check('填入数字后不自动通过语义检查',await input.locator('#applyPlan').isDisabled());await input.locator('#requestPlanReview').click();check('只生成真实重新核验请求',(await input.locator('#handoffText').inputValue()).includes('重新生成并核验')&&(await snap(input)).operations.length===0);
 const finalLease=await open(ctx,'lease_blind_confirmed');await preview(finalLease);await finalLease.locator('#applyPlan').click();await finalLease.waitForFunction(()=>window.reviewEditor.export().operations.length===1);
 check('重新生成核验后的单处计划正确应用',(await snap(finalLease)).current_nodes.b0002.includes('叁仟元整')&&!(await snap(finalLease)).current_nodes.b0002.includes('贰仟'));
 const negative=await open(ctx,'service_rights_loss');await preview(negative);check('丢失退款权利方案被阻断',await negative.locator('#applyPlan').isDisabled()&&(await negative.locator('#planWarnings').textContent()).includes('退款'));
 const legacy=await open(ctx,'legacy');check('旧JSON在新版中正确展示旧建议',await legacy.locator('.card').count()===1&&(await legacy.locator('.clause .body').textContent()).includes('旧版建议'));await preview(legacy);check('旧建议未核验时拒绝盲目应用',await legacy.locator('#applyPlan').isDisabled());
 const mobileCtx=await b.newContext({viewport:{width:390,height:844}}),mobile=await open(mobileCtx,'purchase_group');await preview(mobile);
 check('新版统一预览窄屏无页面溢出',await mobile.evaluate(()=>innerWidth===390&&document.documentElement.scrollWidth<=innerWidth+1));
 await mobile.screenshot({path:path.join(resultDir,'mobile-plan.png'),fullPage:false});await p2.locator('#importRevisions').setInputFiles(confirmedFile);await p2.waitForTimeout(100);await preview(p2);await p2.screenshot({path:path.join(resultDir,'desktop-plan.png'),fullPage:false});
 check('浏览器全过程无JS异常',errors.length===0);
 fs.writeFileSync(path.join(resultDir,'results.json'),JSON.stringify({checks,errors,test_word:word,original_sha256:source.file_sha256,word_ui_render_verified:false},null,2));console.log(JSON.stringify({passed:checks.length,errors}));
 }finally{await b.close();}
})().catch(e=>{fs.writeFileSync(path.join(resultDir,'failure.json'),JSON.stringify({checks,errors,error:e.stack},null,2));console.error(e);process.exit(1)});
