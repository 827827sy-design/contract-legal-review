/* Fixed offline V2 editor. Text positions are Unicode code points. */
(() => {
'use strict';
if (!DATA.editor) return;
const doc=DATA.editor.document, original=doc.original_nodes;
const cp=s=>Array.from(String(s)), clone=o=>JSON.parse(JSON.stringify(o));
const canonical=o=>Array.isArray(o)?o.map(canonical):o&&typeof o==='object'?Object.fromEntries(Object.keys(o).sort().map(k=>[k,canonical(o[k])])):o;
const equal=(a,b)=>JSON.stringify(canonical(a))===JSON.stringify(canonical(b));
const base=Object.fromEntries(original.map(n=>[n.node_id,n.text]));
const reviewNodes=DATA.editor.review_nodes||doc.original_nodes;
const reviewById=Object.fromEntries(reviewNodes.map(n=>[n.node_id,n]));
const reviewId=DATA.meta.review_id||doc.identity.content_sha256,riskKey=id=>reviewId+':'+id;
const marksByNode=new Map();
for(const r of risks)for(const e of r.evidence||[]){if(e.no_text||!e.has_span||!e.span)continue;for(const n of reviewNodes){const start=Math.max(0,e.span[0]-n.full_start),end=Math.min(cp(n.text).length,e.span[1]-n.full_start);if(end>start){if(!marksByNode.has(n.node_id))marksByNode.set(n.node_id,[]);marksByNode.get(n.node_id).push({start,end,r,e});}}}
const names={neutral:'中立',party_a:'甲方',party_b:'乙方',custom:'自定义'};
let model={schema_version:2,contract:clone(doc.identity),base_nodes:base,operations:[],history:[],redo_stack:[],risk_decisions:{},perspective:clone(DATA.meta.perspective||{mode:'neutral',focus:''})};
let current=clone(original),savedSnapshot=null,pendingDownload=null,fileHandle=null,editDraft=null,selectedNode=null,dirty=false;
let planSelection=null,planBusy=false;
const cacheKey='contract-review-v2:'+doc.identity.file_sha256+':'+doc.identity.content_sha256;
const event=(action,detail={})=>model.history.push({time:new Date().toISOString(),action,...detail});
const revision=()=>({...clone(model),current_nodes:Object.fromEntries(current.map(n=>[n.node_id,n.text]))});
const serialized=()=>JSON.stringify(revision());
function replay(value) {
 if (!value || value.schema_version!==2 || !equal(value.contract,doc.identity) || !equal(value.base_nodes,base)) throw Error('修订文件与当前原始合同不匹配，已阻止导入。');
 if (!Array.isArray(value.operations)||value.operations.length>10000||!Array.isArray(value.history)||!Array.isArray(value.redo_stack)||typeof value.risk_decisions!=='object') throw Error('修订结构或历史记录无效。');
 ClausePlanTools.validateGroups(value);
 const nodes=clone(original),ids=new Set(),historical=new Map(original.map(n=>[n.node_id,n]));
 const undone=[];let seenUndone=false;
 for(const op of value.operations) {
  if(!op||typeof op.id!=='string'||ids.has(op.id)||!['active','undone','abandoned'].includes(op.status)||!['pending','confirmed','rejected'].includes(op.decision)||!['manual','ai'].includes(op.source)||typeof op.perspective!=='object'||!op.time)throw Error('修改编号、来源或状态不合法。');
  ids.add(op.id);
  if(typeof op.before_text!=='string'||typeof op.after_text!=='string'||typeof op.inserted_text!=='string'||!Number.isInteger(op.start)||!Number.isInteger(op.end)||op.start<0||op.end<op.start||op.end>cp(op.before_text).length)throw Error('历史修改内容或位置不合法。');
  const before=cp(op.before_text);
  if(before.slice(op.start,op.end).join('')!==op.removed_text||before.slice(0,op.start).join('')+op.inserted_text+before.slice(op.end).join('')!==op.after_text)throw Error('历史修改片段与前后文本不一致。');
  if(op.type==='insert_node'){
   if(!/^n-[A-Za-z0-9_-]+$/.test(op.node_id)||historical.has(op.node_id)||op.before_text!==''||!historical.has(op.anchor_node_id))throw Error('历史新增节点或锚点不合法。');
   const anchor=historical.get(op.anchor_node_id);if(anchor.kind==='cell'&&original.filter(n=>n.block_id===anchor.block_id).at(-1).node_id!==op.anchor_node_id)throw Error('历史插入位置位于表格内部。');historical.set(op.node_id,{editable:true});
  }else if(!['insert','delete','replace'].includes(op.type)||!historical.get(op.node_id)?.editable)throw Error('历史节点不可编辑或类型不合法。');
  if(op.status==='undone'){seenUndone=true;undone.push(op.id);}else if(op.status==='active'&&seenUndone)throw Error('恢复分支与有效操作顺序冲突。');
  if(op.status!=='active'||op.decision==='rejected')continue;
  const group=value.plan_groups?.[op.group_id];if(group&&op.id===group.operation_ids[0])ClausePlanTools.preflight(group.snapshot,nodes);
  if(op.type==='insert_node') {
   const index=nodes.findIndex(n=>n.node_id===op.anchor_node_id);
   if(index<0||!/^n-[A-Za-z0-9_-]+$/.test(op.node_id)||nodes.some(n=>n.node_id===op.node_id)||op.before_text!==''||typeof op.after_text!=='string'||(nodes[index+1]&&nodes[index+1].block_id===nodes[index].block_id))throw Error('新增条款锚点不可靠。');
   nodes.splice(index+1,0,{node_id:op.node_id,block_id:op.node_id,kind:'paragraph',text:op.after_text,editable:true,inserted:true,anchor_node_id:op.anchor_node_id});
  } else {
   const node=nodes.find(n=>n.node_id===op.node_id);
   if(!['insert','delete','replace'].includes(op.type)||!node?.editable||node.text!==op.before_text)throw Error('原文节点已变更或不可编辑，存在冲突。');
   const chars=cp(node.text),{start,end}=op;
   if(!Number.isInteger(start)||!Number.isInteger(end)||start<0||end<start||end>chars.length||typeof op.inserted_text!=='string'||chars.slice(start,end).join('')!==op.removed_text)throw Error('精确位置或原文片段校验失败。');
   const after=chars.slice(0,start).join('')+op.inserted_text+chars.slice(end).join('');
   if(after!==op.after_text)throw Error('修改后内容与操作不一致。');
   node.text=after;
  }
 }
 if(!equal(Object.fromEntries(nodes.map(n=>[n.node_id,n.text])),value.current_nodes))throw Error('当前稿与历史操作重放不一致。');
 if(!equal(value.redo_stack,[...undone].reverse()))throw Error('恢复栈与已撤销历史不一致。');
 const future=clone(nodes);
 for(const op of value.operations.filter(o=>o.status==='undone')){
  if(op.type==='insert_node'){const at=future.findIndex(n=>n.node_id===op.anchor_node_id);if(at<0)throw Error('已撤销条款的恢复锚点不存在。');future.splice(at+1,0,{node_id:op.node_id,block_id:op.node_id,kind:'paragraph',text:op.after_text,editable:true});}
  else{const node=future.find(n=>n.node_id===op.node_id);if(!node||node.text!==op.before_text)throw Error('已撤销操作的前文无法连续恢复。');node.text=op.after_text;}
 }
 return nodes;
}
function restore(value,fromFile=false) {
 const nodes=replay(value);model=clone(value);delete model.current_nodes;current=nodes;
 savedSnapshot=fromFile?serialized():null;pendingDownload=null;editDraft=null;
 persist();renderDocument();renderCards();updateStatus();
}
function persist() {
 try{localStorage.setItem(cacheKey,JSON.stringify(revision()));}catch{$('#cacheNotice').textContent='浏览器临时恢复不可用，请主动保存修订 JSON。';}
 dirty=Boolean(model.operations.length||model.history.length||Object.keys(model.risk_decisions).length)&&serialized()!==savedSnapshot;
}
function status(message,error=false){const el=$('#editorStatus');el.textContent=message;el.classList.toggle('error',error);}
function updateStatus(){
 dirty=Boolean(model.operations.length||model.history.length||Object.keys(model.risk_decisions).length)&&serialized()!==savedSnapshot;
 $('#saveState').textContent=dirty?'有未保存记录':!model.operations.length&&!model.history.length?'尚无修改':fileHandle?'已写入所选文件':'修订文件已导入或用户已确认下载';
 $('#undoBtn').disabled=!model.operations.some(o=>o.status==='active');
 $('#redoBtn').disabled=!model.redo_stack.length;
 $('#revisionCount').textContent=model.operations.filter(o=>o.status==='active').length+' 项有效修改';
 $('#restoreOriginal').disabled=!model.operations.some(o=>o.status==='active');
 renderHistory();
}
function invalidate(){persist();renderDocument();renderCards();updateStatus();}
function nodeChanged(n){return reviewById[n.node_id]?.text!==n.text;}
function riskStale(r){if(r.edit_plan&&Object.entries(r.edit_plan.scope_node_texts||{}).some(([id,text])=>current.find(n=>n.node_id===id)?.text!==text))return true;if((r.evidence||[]).some(e=>e.no_text)&&current.some(n=>n.inserted&&!reviewById[n.node_id]))return true;return (r.evidence||[]).some(e=>{
 const lo=e.span?.[0],hi=e.span?.[1];
 return reviewNodes.filter(n=>e.block_id===n.block_id||(lo!==undefined&&n.full_start<hi&&n.full_start+cp(n.text).length>lo)).some(n=>current.find(x=>x.node_id===n.node_id)?.text!==n.text);
 });}
function currentMarkup(n,lo,hi){
 const b=cp(n.text),marks=nodeChanged(n)?[]:marksByNode.get(n.node_id)||[];
 const points=[...new Set([lo,hi,...marks.flatMap(m=>[m.start,m.end]).filter(p=>p>lo&&p<hi)])].sort((x,y)=>x-y);
 return points.slice(0,-1).map((start,i)=>{const end=points[i+1],cover=marks.filter(m=>m.start<=start&&m.end>=end);const text=esc(b.slice(start,end).join(''));return cover.length?'<span tabindex="0" role="button" class="mk mk-'+esc(cover[0].r.severity)+' '+cover.map(m=>'m-'+m.r.risk_id+'-'+m.e.i).join(' ')+'">'+text+'</span>':text;}).join('');
}
function diffSegments(before,after){
 const a=cp(before),b=cp(after);let prefix=0,tail=0;
 while(prefix<Math.min(a.length,b.length)&&a[prefix]===b[prefix])prefix++;
 while(tail<Math.min(a.length-prefix,b.length-prefix)&&a[a.length-1-tail]===b[b.length-1-tail])tail++;
 const x=a.slice(prefix,a.length-tail),y=b.slice(prefix,b.length-tail),segments=[];
 const push=(type,text)=>{if(!text)return;if(segments.at(-1)?.type===type)segments.at(-1).text+=text;else segments.push({type,text});};
 push('same',a.slice(0,prefix).join(''));
 if(x.length*y.length<=250000){
  const width=y.length+1,table=new Uint32Array((x.length+1)*width);
  for(let i=x.length-1;i>=0;i--)for(let j=y.length-1;j>=0;j--)table[i*width+j]=x[i]===y[j]?1+table[(i+1)*width+j+1]:Math.max(table[(i+1)*width+j],table[i*width+j+1]);
  let i=0,j=0;while(i<x.length||j<y.length){if(i<x.length&&j<y.length&&x[i]===y[j]){push('same',x[i++]);j++;}else if(i<x.length&&(j===y.length||table[(i+1)*width+j]>=table[i*width+j+1]))push('delete',x[i++]);else push('insert',y[j++]);}
 }else{push('delete',x.join(''));push('insert',y.join(''));}
 push('same',tail?a.slice(a.length-tail).join(''):'');return segments;
}
function textMarkup(n){
 const old=base[n.node_id]??'',now=n.text;
 if(old===now||$('#displayMode').value==='clean')return currentMarkup(n,0,cp(now).length);
 let offset=0;return diffSegments(old,now).map(part=>{if(part.type==='delete')return '<del class="revision-deleted" aria-label="删除文字">'+esc(part.text)+'</del>';const length=cp(part.text).length,html=currentMarkup(n,offset,offset+length);offset+=length;return part.type==='insert'?'<ins class="revision-added" aria-label="新增文字">'+html+'</ins>':html;}).join('');
}
function nodeNotice(n){
 if(!n.editable)return '<small class="readonly-note">暂不能编辑：'+esc(n.read_only_reason||'复杂Word结构')+'</small>';
 return n.has_existing_revisions?'<small class="revision-note">含原有 Word 修订，可继续编辑；导出时保留旧记录并追加修改。</small>':'';
}
function renderDocument(){
 clearSearch();const groups=new Map();current.forEach(n=>{if(!groups.has(n.block_id))groups.set(n.block_id,[]);groups.get(n.block_id).push(n)});
 let html='';
 for(const [bid,nodes] of groups){
  if(nodes[0].kind==='cell'){
   const rows=new Map();for(const n of nodes){if(!rows.has(n.row))rows.set(n.row,[]);rows.get(n.row).push(n)}
   html+='<table class="blk blk-table" data-bid="'+esc(bid)+'"><tbody>'+[...rows].map(([row,cells])=>'<tr>'+cells.map(n=>'<td data-node="'+esc(n.node_id)+'" tabindex="0" class="editable-node'+(nodeChanged(n)?' changed-node':'')+'">'+textMarkup(n)+nodeNotice(n)+'</td>').join('')+'</tr>').join('')+'</tbody></table>';
  }else {const n=nodes[0];html+='<div class="blk editable-node'+(nodeChanged(n)?' changed-node':'')+'" data-node="'+esc(n.node_id)+'" data-bid="'+esc(bid)+'" tabindex="0">'+textMarkup(n)+(nodeChanged(n)?'<small class="stale-note">已修改，原审查需重新核实</small>':'')+nodeNotice(n)+'</div>';}
 }
 $('#contractRoot').innerHTML=html+'<div id="contractEnd" class="blk" aria-label="合同末尾"></div>';
 $('#targetNode').innerHTML=current.map(n=>'<option value="'+esc(n.node_id)+'">'+esc(n.node_id+' · '+n.text.slice(0,30))+'</option>').join('');
 if(selectedNode&&current.some(n=>n.node_id===selectedNode))$('#targetNode').value=selectedNode;
 if($('#docSearch').value.trim())searchDoc();
}
function delta(before,after){const a=cp(before),b=cp(after);let start=0,tail=0;
 while(start<Math.min(a.length,b.length)&&a[start]===b[start])start++;
 while(tail<Math.min(a.length-start,b.length-start)&&a[a.length-1-tail]===b[b.length-1-tail])tail++;
 return {start,end:a.length-tail,removed_text:a.slice(start,a.length-tail).join(''),inserted_text:b.slice(start,b.length-tail).join('')};
}
function commitOperation(op){
 if(model.operations.length>=10000)throw Error('修改记录已达到上限，请保存并返回 WorkBuddy 整理。');
 const proposed=clone(model),abandoned=new Set(proposed.redo_stack);proposed.operations.forEach(o=>{if(abandoned.has(o.id))o.status='abandoned'});proposed.redo_stack=[];
 const id='rev-'+Date.now()+'-'+model.operations.length;
 op={id,status:'active',decision:'pending',time:new Date().toISOString(),perspective:clone(DATA.meta.perspective||{mode:'neutral',focus:''}),review_id:reviewId,reason:$('#editReason').value||'用户确认的文本修订',risk_id:editDraft?.risk_id||null,...op};
 proposed.operations.push(op);
 // Build after-state once, then independently replay all recorded operations.
 let next=clone(current);
 if(op.type==='insert_node'){const index=next.findIndex(n=>n.node_id===op.anchor_node_id);next.splice(index+1,0,{node_id:op.node_id,block_id:op.node_id,kind:'paragraph',text:op.after_text,editable:true,inserted:true,anchor_node_id:op.anchor_node_id});}
 else {const target=next.find(n=>n.node_id===op.node_id);if(!target||target.text!==op.before_text)throw Error('原文已变化，请重新选择修改位置。');target.text=op.after_text;}
 proposed.current_nodes=Object.fromEntries(next.map(n=>[n.node_id,n.text]));current=replay(proposed);delete proposed.current_nodes;model=proposed;
 event('apply',{revision_id:op.id});invalidate();$('#editPanel').hidden=true;editDraft=null;status('修改已记录，尚未最终确认或保存。');
}
function openManual(nodeId){
 const node=current.find(n=>n.node_id===nodeId);if(!node)return;
 selectedNode=nodeId;if(!node.editable){editDraft=null;$('#editPanel').hidden=true;status('此段暂不能直接编辑：'+(node.read_only_reason||'复杂Word结构')+'。请返回聊天处理该结构。',true);return;}
 editDraft={node_id:nodeId,before_text:node.text,source:'manual',mode:'replace'};
 $('#editPanel').hidden=false;$('#targetNode').value=nodeId;$('#editMode').value='replace';$('#editText').value=node.text;$('#editBefore').textContent=node.text;$('#editReason').value='人工编辑';$('#editText').focus();
}
function suggestion(r){showPlan(r);}
function applyDraft(){
 try{
  if(!editDraft)throw Error('请先选择修改位置。');
  if(editDraft.source==='ai')throw Error('AI建议必须通过修改计划校验和整组确认，不能从解释文字直接应用。');
  const node=current.find(n=>n.node_id===$('#targetNode').value);if(!node)throw Error('必须人工选择目标位置。');
  const mode=$('#editMode').value,text=$('#editText').value;
  if(mode==='insert'){
   const index=current.indexOf(node);if(current[index+1]?.block_id===node.block_id)throw Error('请选择表格最后一个单元格，条款将插入整张表格之后。');
   if(!text.trim())throw Error('新增条款不能为空。');
   commitOperation({type:'insert_node',node_id:'n-'+Date.now()+'-'+model.operations.length,anchor_node_id:node.node_id,before_text:'',after_text:text,start:0,end:0,removed_text:'',inserted_text:text,source:editDraft.source});return;
  }
  if(!node.editable)throw Error('复杂结构只读，请改选常见段落或单元格。');
  if(editDraft.before_text!==null&&editDraft.node_id===node.node_id&&node.text!==editDraft.before_text)throw Error('编辑期间目标文本发生改变，请重新选择。');
  let after=text;
  if(mode==='partial'){
   if(node.node_id!==editDraft.node_id||!Number.isInteger(editDraft.start))throw Error('局部修改没有可靠范围，请选择整段替换并核对全文。');
   const chars=cp(node.text);if(chars.slice(editDraft.start,editDraft.end).join('')!==editDraft.expected)throw Error('目标原文不匹配，禁止自动应用。');
   after=chars.slice(0,editDraft.start).join('')+text+chars.slice(editDraft.end).join('');
  }
  if(after===node.text){status('内容未变化，没有生成修改记录。');return;}
  const change=delta(node.text,after),type=change.removed_text?(change.inserted_text?'replace':'delete'):'insert';
  commitOperation({type,node_id:node.node_id,before_text:node.text,after_text:after,...change,source:editDraft.source});
 }catch(error){status(error.message,true);}
}
function transaction(change){const old=clone(model),oldNodes=clone(current);try{change();refreshFromOperations();}catch(error){model=old;current=oldNodes;status('操作已取消，原状态保留：'+error.message,true);}}
function undo(){transaction(()=>{const op=[...model.operations].reverse().find(o=>o.status==='active');if(!op)return;const ids=op.group_id?model.plan_groups[op.group_id].operation_ids:[op.id];for(const id of [...ids].reverse()){model.operations.find(o=>o.id===id).status='undone';model.redo_stack.push(id);}event('undo',{revision_id:op.id,group_id:op.group_id||null});});}
function redo(){transaction(()=>{const last=model.redo_stack.at(-1),op=model.operations.find(o=>o.id===last);if(!op)return;const ids=op.group_id?model.plan_groups[op.group_id].operation_ids:[last];for(const id of ids){if(model.redo_stack.pop()!==id)throw Error('整组恢复顺序冲突。');model.operations.find(o=>o.id===id).status='active';}event('redo',{revision_id:last,group_id:op.group_id||null});});}
function refreshFromOperations(){
 let nodes=clone(original);
 for(const op of model.operations){if(op.status!=='active'||op.decision==='rejected')continue;
  if(op.type==='insert_node'){const at=nodes.findIndex(n=>n.node_id===op.anchor_node_id);nodes.splice(at+1,0,{node_id:op.node_id,block_id:op.node_id,kind:'paragraph',text:op.after_text,editable:true,inserted:true,anchor_node_id:op.anchor_node_id});}
  else{const node=nodes.find(n=>n.node_id===op.node_id);if(!node||node.text!==op.before_text)throw Error('历史操作存在冲突，已停止恢复。');node.text=op.after_text;}}
 const value={...clone(model),current_nodes:Object.fromEntries(nodes.map(n=>[n.node_id,n.text]))};current=replay(value);invalidate();
}
function renderHistory(){
 $('#historyList').innerHTML=model.operations.map(o=>'<li><strong>'+esc(o.id)+'</strong> · '+esc(o.node_id)+' · '+(o.status==='active'?'有效':o.status==='undone'?'已撤销':'已分支保留')+' · '+(o.decision==='confirmed'?'已确认':'待确认')+'<div>'+esc(o.reason)+' · '+esc(o.time)+'</div></li>').join('')||'<li>尚无修改。历史不会因撤销而删除。</li>';
}
const planNames={ready:'可提交确认',needs_input:'需补充条件',coordinated_review:'需关联修改',manual_review:'需人工复核'};
function showPlan(r){
 planSelection=r;const p=r.edit_plan;
 $('#planPanel').hidden=false;$('#planTitle').textContent=r.risk_id+' · '+r.title;
 if(!p){$('#planState').textContent='旧版建议尚未通过质量审查';$('#planWarnings').textContent='保留展示。请返回WorkBuddy生成正式修改计划；不从证据推测替换范围。';$('#planRows').innerHTML='';$('#planQuestions').innerHTML='';$('#planImpacts').textContent='';$('#applyPlan').disabled=true;return;}
 let runtime='';try{if(p.can_apply)ClausePlanTools.preflight(p,current);}catch(e){runtime=e.message;}
 const drafted=model.plan_drafts?.[p.plan_id];if(drafted?.needs_regeneration&&drafted.draft_id!==p.raw_plan?.input_draft_id)runtime='新增条件尚未重新生成、核验条款。';
 if(Object.values(model.plan_groups||{}).some(g=>g.plan_fingerprint===p.plan_fingerprint&&model.operations.some(o=>o.group_id===g.group_id&&o.status==='active')))runtime='本计划已应用，不能重复执行。';
 $('#planState').textContent=runtime?('当前不可应用 · '+runtime+' · 风险仍待复审'):(planNames[p.readiness]||'需人工复核')+' · '+p.quality_result+' · 应用后仍待复审';
 $('#planWarnings').innerHTML=[...new Set([...p.blockers,...(runtime?[runtime]:[])])].map(t=>'<p>'+esc(t)+'</p>').join('')||'<p>所有系统检查条件已满足，请逐项核对后确认整组应用。</p>';
 $('#planRows').innerHTML=p.edits.map(e=>{const node=current.find(n=>n.node_id===e.target_node_id),before=e.expected_node_text??'',after=e.operation==='insert_clause'?e.replacement_text:(p.preview_nodes.find(n=>n.node_id===e.target_node_id)?.after??e.replacement_text);
  const diff=e.draft_pending?'':diffSegments(e.operation==='insert_clause'?'':before,after).map(s=>s.type==='delete'?'<del>'+esc(s.text)+'</del>':s.type==='insert'?'<ins>'+esc(s.text)+'</ins>':esc(s.text)).join('');
  return '<details open><summary>'+esc(e.target_node_id)+' · '+esc({partial:'局部替换',replace:'整段替换',delete_clause:'删除条款文字',insert_clause:'新增条款'}[e.operation])+'</summary><p>计划基准原文</p><pre>'+esc(before)+'</pre><p>'+(e.draft_pending?'尚待条件确认后生成正式文字':'修改后正式文字'+(after?'':'（删除，保留段落结构）'))+'</p><pre>'+esc(e.draft_pending?'':after)+'</pre><p>新增及删除差异</p><div class="plan-diff">'+diff+'</div>'+(!node||node.text!==before?'<p class="plan-error">当前原文已变化，禁止按旧计划应用。</p>':'')+'<p>修改原因：'+esc(p.reason)+'；关联节点：'+esc((e.dependencies||[]).join('、')||'未列出')+'</p></details>';}).join('');
 const targetIds=new Set(Object.keys(p.scope_node_texts||{}));
 const affected=risks.filter(x=>x.risk_id!==r.risk_id&&(Object.keys(x.edit_plan?.scope_node_texts||{}).some(id=>targetIds.has(id))||(x.evidence||[]).some(e=>current.some(n=>n.block_id===e.block_id&&targetIds.has(n.node_id))))).map(x=>x.risk_id+' '+x.title);
 $('#planImpacts').textContent='可能受到影响的其他风险：'+(affected.join('；')||'分析未列出；不能据此保证不存在关联。');
 $('#planQuestions').innerHTML=(p.questions||[]).filter(q=>q&&typeof q==='object').map(q=>'<label>'+esc(q.question)+(q.required?'（必填）':'')+(q.impact?'<small>'+esc(q.impact)+'</small>':'')+(Array.isArray(q.options)?'<ul>'+q.options.map(o=>'<li>'+esc(typeof o==='string'?o:(o.label||o.value||''))+(o?.impact?'：'+esc(o.impact):'')+'</li>').join('')+'</ul>':'')+'<textarea data-plan-question="'+esc(q.id)+'">'+esc(drafted?.answers?.[q.id]??q.answer??'')+'</textarea></label>').join('');
 $('#applyPlan').disabled=!p.can_apply||Boolean(runtime);$('#savePlanDraft').disabled=!(p.questions||[]).length;$('#planPanel').focus();
}
function savePlanDraft(){
 const p=planSelection?.edit_plan;if(!p){status('旧版建议需由WorkBuddy生成计划。',true);return;}
 if(!p.plan_id||['__proto__','constructor','prototype'].includes(p.plan_id)){status('计划ID不合法，需重新生成。',true);return;}
 const answers=Object.fromEntries([...$('#planQuestions').querySelectorAll('[data-plan-question]')].map(el=>[el.dataset.planQuestion,el.value.trim()]));
 model.plan_drafts??={};const draft_id='draft-'+crypto.randomUUID();model.plan_drafts[p.plan_id]={draft_id,plan_id:p.plan_id,plan_fingerprint:p.plan_fingerprint,answers,needs_regeneration:true,time:new Date().toISOString()};
 event('save_plan_draft',{plan_id:p.plan_id,draft_id,answers:clone(answers),plan_fingerprint:p.plan_fingerprint});invalidate();$('#applyPlan').disabled=true;status('条件已保存为待完善草稿；尚未修改合同，需保存JSON并返回WorkBuddy重新生成、核验受影响计划。');
}
async function applyPlan(){
 if(planBusy)return;planBusy=true;$('#applyPlan').disabled=true;
 try{
  const r=planSelection,p=r?.edit_plan;if(!p)throw Error('没有经过校验的修改计划。');
  if(p.source_file_sha256!==doc.identity.file_sha256)throw Error('修改计划与当前原始合同不匹配。');
  const before=serialized();await ClausePlanTools.verify(p);if(before!==serialized())throw Error('核验期间编辑状态已变化，请重新预览。');
  const drafted=model.plan_drafts?.[p.plan_id];if(drafted?.needs_regeneration&&drafted.draft_id!==p.raw_plan?.input_draft_id)throw Error('补充条件尚未完成重新核验。');
  if(Object.values(model.plan_groups||{}).some(g=>g.plan_fingerprint===p.plan_fingerprint&&model.operations.some(o=>o.group_id===g.group_id&&o.status==='active')))throw Error('同一计划已应用，禁止重复应用。');
  const steps=ClausePlanTools.preflight(p,current);
  if(!confirm('确认应用本计划的全部 '+p.edits.length+' 项动作？修改会整组记录，可整体撤销；风险仍需复审。'))return;
  const proposed=clone(model),next=clone(current),abandoned=new Set(proposed.redo_stack);proposed.operations.forEach(o=>{if(abandoned.has(o.id))o.status='abandoned'});proposed.redo_stack=[];
  const gid='group-'+crypto.randomUUID(),ids=[];
  for(const step of steps){const id='rev-'+crypto.randomUUID();ids.push(id);let op;
   if(step.kind==='insert'){const nid='n-'+crypto.randomUUID(),at=next.findIndex(n=>n.node_id===step.anchor);next.splice(at+1,0,{node_id:nid,block_id:nid,kind:'paragraph',text:step.after,editable:true,inserted:true,anchor_node_id:step.anchor});op={type:'insert_node',node_id:nid,anchor_node_id:step.anchor};}
   else {const n=next.find(n=>n.node_id===step.node_id);if(n.text!==step.before)throw Error('整组执行原文冲突。');n.text=step.after;op={type:step.after?'replace':'delete',node_id:step.node_id};}
   proposed.operations.push({...op,id,group_id:gid,plan_id:p.plan_id,edit_ids:step.edit_ids,status:'active',decision:'pending',source:'ai',perspective:clone(DATA.meta.perspective||{mode:'neutral'}),time:new Date().toISOString(),review_id:reviewId,risk_id:r.risk_id,reason:p.reason,before_text:step.before,after_text:step.after,start:0,end:cp(step.before).length,removed_text:step.before,inserted_text:step.after});
  }
  proposed.plan_groups??={};proposed.plan_groups[gid]={group_id:gid,plan_id:p.plan_id,plan_fingerprint:p.plan_fingerprint,operation_ids:ids,snapshot:clone(p)};
  proposed.risk_status??={};proposed.risk_status[riskKey(r.risk_id)]={status:'needs_re_review',group_id:gid};proposed.history.push({action:'apply_plan',group_id:gid,time:new Date().toISOString(),risk_status:'needs_re_review'});
  proposed.current_nodes=Object.fromEntries(next.map(n=>[n.node_id,n.text]));const verified=replay(proposed);delete proposed.current_nodes;model=proposed;current=verified;invalidate();showPlan(r);status('整组修改已记录，全部保持待确认；原风险及关联风险仍需复审。');
 }catch(e){status('计划未应用：'+e.message,true);}
 finally{planBusy=false;}
}
$('#applyPlan').addEventListener('click',applyPlan);$('#savePlanDraft').addEventListener('click',savePlanDraft);$('#closePlan').addEventListener('click',()=>{$('#planPanel').hidden=true;planSelection=null;});
$('#requestPlanReview').addEventListener('click',()=>{savePlanDraft();$('#handoffPanel').hidden=false;$('#handoffText').value='请读取原合同、已有审查结果及我保存的revisions.json中的plan_drafts。只重新生成并核验补充条件影响的修改计划与关联范围，保留原有编辑和历史；必要时请求更多条件。将输入draft_id绑定到新计划input_draft_id并重新进行10项语义审查，不把待完善草稿当成已应用修改，不把应用当成风险已解决。';});
function decorateCards(){
 for(const card of document.querySelectorAll('.card')){
  const r=risks.find(r=>r.risk_id===card.dataset.risk),body=card.querySelector('.card-body');if(!r||!body)continue;
  const source={legal:'法律风险',company_policy:'企业制度',negotiation:'商务谈判建议',experience:'用户经验'}[r.risk_source||'legal'];
  const stale=riskStale(r),rejected=model.risk_decisions[riskKey(r.risk_id)]?.decision==='rejected';
  const draft=model.plan_drafts?.[r.edit_plan?.plan_id],needsInputReview=draft?.needs_regeneration&&draft.draft_id!==r.edit_plan?.raw_plan?.input_draft_id;
  if(stale||needsInputReview){const note=body.querySelector('.suggestion-note');if(note)note.textContent='当前正文或补充条件已变化，原方案不可直接应用；风险保持待复审。';const copy=body.querySelector('[data-copy]');if(copy)copy.disabled=true;const tag=body.querySelector('.clause-nav span');if(tag)tag.textContent='原计划需重新核验';}
  body.insertAdjacentHTML('afterbegin','<div class="risk-origin">'+esc(source)+(stale?' · 此处已修改，建议重新审查':'')+(rejected?' · 暂不采纳':'')+'</div>');
  const p=r.edit_plan,action=!p?'核验旧版建议':p.readiness==='needs_input'?'完善条款':p.readiness==='coordinated_review'?'查看关联修改方案':p.can_apply?'预览修改':'查看人工复核事项';
  body.insertAdjacentHTML('beforeend','<div class="suggestion-actions"><button class="btn" data-apply="'+esc(r.risk_id)+'">'+action+'</button><button class="btn" data-reject="'+esc(r.risk_id)+'">'+(rejected?'恢复待确认':'暂不采纳')+'</button></div>');
 }
}
const oldRender=renderCards;renderCards=function(){oldRender();decorateCards();};
const oldLocate=locate;locate=function(r,j=0){if(riskStale(r)){clearLocation();state.selected=r.risk_id;$('#locStatus').textContent='此处内容已修改，旧原文定位已停用，请重新审查。';return;}oldLocate(r,j);};
function handoff(kind){
 const mode=$('#perspectiveSelect').value,focus=$('#perspectiveFocus').value.trim();
 if(kind==='perspective'){model.perspective={...model.perspective,mode,focus};event('perspective_request',{mode,focus});persist();updateStatus();}
 const originalFile=doc.source_file||doc.source_name;
 let text;
 if(kind==='word')text='请读取原始 DOCX '+JSON.stringify(originalFile)+' 及我保存的 revisions.json。先校验合同标识、操作历史和每处原文，只应用已确认的有效修改，生成新的 DOCX，保留原有Word修订与批注，含旧修订的文字段落追加新的原生修订，不接受或拒绝旧记录。尽可能保留原排版并逐项核验。对于未确认或冲突项先提示我，不要自行决定；不要覆盖原文件。如需所有新增修改均带Word原生修订，请使用apply_docx.py的 --track-changes。';
 else if(kind==='perspective')text='请读取原始合同 '+JSON.stringify(originalFile)+'、已有审查任务和保存的 revisions.json，以'+names[mode]+'视角重新分析；重点：'+(focus||'按该视角核查权利义务')+'。先确认真实甲乙方主体。复用解析及已核验法条，客观法律判断不随立场改变；保存修改历史，创建新的审查运行目录，对与现有修改冲突的建议让我选择。浏览器尚未完成重新审查。';
 else text='请读取原始合同 '+JSON.stringify(originalFile)+'、我保存的 revisions.json 和已有审查结果。用 revisions.py 校验并还原当前有效修改稿，在新的任务目录重新审查，明确已解决、仍然存在、新增及待确认风险，保留全部修订与审查历史。未确认修改可以用于复审草稿，但不得自动作为最终 Word。';
 $('#handoffPanel').hidden=false;$('#handoffText').value=text;$('#handoffText').focus();$('#handoffText').select();
 if(kind==='perspective')status('已生成请求，当前报告仍为'+names[DATA.meta.perspective?.mode||'neutral']+'视角；请先保存，再返回 WorkBuddy 重新分析。');
}
async function copyText(text){try{await navigator.clipboard.writeText(text);toast('指令已复制');}catch{$('#handoffText').focus();$('#handoffText').select();toast('已选中指令，请按 Ctrl+C / Command+C 复制');}}
async function saveNative(){
 try{
  if(typeof window.showSaveFilePicker!=='function')throw Error('浏览器不支持直接写入，请使用下载修订 JSON。');
  if(!fileHandle)fileHandle=await window.showSaveFilePicker({suggestedName:'revisions.json',excludeAcceptAllOption:true,types:[{description:'修订记录',accept:{'application/json':['.json']}}]});
  if(!fileHandle.name?.toLowerCase().endsWith('.json')||fileHandle.name===doc.source_name){fileHandle=null;throw Error('仅允许保存为独立 JSON 文件，不能覆盖原始合同。');}
  const snapshot=serialized(),stream=await fileHandle.createWritable();await stream.write(snapshot);await stream.close();
  savedSnapshot=snapshot;pendingDownload=null;updateStatus();status('修订记录已成功写入所选本地文件。');
 }catch(error){status(error.name==='AbortError'?'已取消保存；修改尚未保存。':'保存失败：'+error.message,true);}
}
function download(){
 try{const snapshot=serialized(),blob=new Blob([snapshot],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='revisions.json';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);pendingDownload=snapshot;$('#confirmDownload').hidden=false;status('已发起 revisions.json 下载。请检查下载文件后点击“确认文件已保存”；当前尚未标记保存成功。');}
 catch(error){status('下载失败：'+error.message,true);}
}
function finish(){
 $('#workflowTools').open=true;
 if(!model.operations.length&&!model.history.length){$('#completion').hidden=false;$('#completionText').textContent='尚无修改，无需生成修改后的 Word。可返回 WorkBuddy 继续审查。';return;}
 if(dirty){$('#completion').hidden=false;$('#completionText').textContent='存在未保存记录。请先写入本地文件，或下载 JSON 并确认文件保存后，再完成编辑。';status('完成编辑前，请先保存修订记录。',true);return;}
 const active=model.operations.filter(o=>o.status==='active'),pending=active.filter(o=>o.decision==='pending');
 $('#completionList').innerHTML=active.map(o=>'<li>'+esc(o.node_id)+' · '+(o.decision==='confirmed'?'已确认修改':'待确认修改')+' · '+esc(o.reason||o.id)+'</li>').join('')+Object.values(model.risk_decisions).filter(x=>x.decision==='rejected').map(x=>'<li>暂不采纳：'+esc(x.risk_id||'历史风险')+' · '+esc(x.review_id||'原审查')+'</li>').join('');
 $('#completion').hidden=false;$('#completionText').textContent='有效修改 '+active.length+' 项，其中待最终确认 '+pending.length+' 项；暂不采纳 '+Object.values(model.risk_decisions).filter(x=>x.decision==='rejected').length+' 项。返回 WorkBuddy 生成新 Word；保存记录与生成 Word 是两个独立操作。';handoff('word');
}
$('#editEnabled').addEventListener('change',()=>{status($('#editEnabled').checked?'编辑已开启：点击段落或常见单元格，再确认修改。':'阅读模式：点击风险标记定位。');});
$('#contractRoot').addEventListener('click',e=>{const el=e.target.closest('[data-node]');if(el){selectedNode=el.dataset.node;if($('#editEnabled').checked){e.stopImmediatePropagation();openManual(selectedNode);}}},true);
$('#contractRoot').addEventListener('keydown',e=>{if(e.key==='Enter'&&$('#editEnabled').checked&&e.target.matches('[data-node]')){e.preventDefault();openManual(e.target.dataset.node);}});
$('#insertClause').addEventListener('click',()=>{const node=current.find(n=>n.node_id===selectedNode)||current[current.length-1];if(!node){status('合同无节点，不能插入。',true);return;}openManual(node.node_id);if(!editDraft){editDraft={node_id:node.node_id,before_text:node.text,source:'manual'};$('#editPanel').hidden=false;$('#targetNode').value=node.node_id;}$('#editMode').value='insert';$('#editText').value='';$('#editBefore').textContent='将在所选节点所在段落或表格之后插入新条款。';});
$('#targetNode').addEventListener('change',()=>{const node=current.find(n=>n.node_id===$('#targetNode').value);if(!node)return;selectedNode=node.node_id;editDraft={...editDraft,node_id:node.node_id,before_text:node.text,mode:'replace',start:null,end:null};$('#editBefore').textContent=node.text;$('#editMode').value='replace';status('你已选择新节点；整段替换前请核对全部原文。');});
$('#applyEdit').addEventListener('click',applyDraft);$('#cancelEdit').addEventListener('click',()=>{$('#editPanel').hidden=true;editDraft=null;});
$('#displayMode').addEventListener('change',renderDocument);$('#undoBtn').addEventListener('click',undo);$('#redoBtn').addEventListener('click',redo);
$('#restoreOriginal').addEventListener('click',()=>{if(!confirm('恢复原始内容会撤销全部有效修改，并保留历史。继续？'))return;transaction(()=>{model.redo_stack=[];[...model.operations].reverse().forEach(o=>{if(o.status==='active'||o.status==='undone'){o.status='undone';model.redo_stack.push(o.id)}});event('restore_original');});});
$('#confirmEdits').addEventListener('click',()=>{model.operations.filter(o=>o.status==='active').forEach(o=>o.decision='confirmed');event('confirm_active');persist();updateStatus();status('当前有效修改已确认。请重新保存修订记录。');});
$('#riskList').addEventListener('click',e=>{const b=e.target.closest('[data-apply],[data-edit-suggestion],[data-reject]');if(!b)return;
 const id=b.dataset.apply||b.dataset.editSuggestion||b.dataset.reject,r=risks.find(r=>r.risk_id===id);if(!r)return;
 if(b.dataset.reject){const key=riskKey(id);model.risk_decisions[key]={decision:model.risk_decisions[key]?.decision==='rejected'?'pending':'rejected',time:new Date().toISOString(),perspective:clone(DATA.meta.perspective||{mode:'neutral'}),review_id:reviewId,risk_id:id};event('risk_decision',{risk_id:id,review_id:reviewId});persist();renderCards();updateStatus();if(model.operations.some(o=>o.risk_id===id&&o.review_id===reviewId&&o.status==='active'))status('已更新采纳决定；此前应用的修改仍保留，请用撤销或人工编辑处理。');}
 else suggestion(r,Boolean(b.dataset.editSuggestion));
});
$('#saveNative').addEventListener('click',saveNative);$('#downloadRevisions').addEventListener('click',download);
$('#confirmDownload').addEventListener('click',()=>{if(!pendingDownload||pendingDownload!==serialized()){status('下载后又有修改，请重新下载最新记录。',true);return;}savedSnapshot=pendingDownload;pendingDownload=null;$('#confirmDownload').hidden=true;updateStatus();status('已记录你对下载文件保存成功的确认。');});
$('#importRevisions').addEventListener('change',async e=>{const file=e.target.files[0];if(!file)return;try{if(file.size>20*1024*1024)throw Error('修订文件超过 20MB。');const value=JSON.parse(await file.text());for(const g of Object.values(value.plan_groups||{}))await ClausePlanTools.verify(g.snapshot);replay(value);if(dirty&&model.operations.length&&!confirm('导入将替换当前浏览器编辑状态。请确保现有记录已保存；继续？'))return;restore(value,true);status('修订文件校验通过，编辑状态与历史已恢复。');}catch(error){status('导入失败：'+error.message,true);}e.target.value='';});
$('#perspectiveRequest').addEventListener('click',()=>handoff('perspective'));$('#rereviewRequest').addEventListener('click',()=>handoff('rereview'));$('#copyHandoff').addEventListener('click',()=>copyText($('#handoffText').value));$('#finishEditing').addEventListener('click',finish);
$('#saveNative').disabled=typeof window.showSaveFilePicker!=='function';
$('#preferencesInfo').textContent=DATA.editor.context.preferences_configured?'已加载 '+(DATA.editor.context.preferences||[]).length+' 项适用偏好。查看、修改或禁用请返回 WorkBuddy。':'未配置长期偏好。首次审查请由 WorkBuddy 询问；可跳过并采用默认中立标准。';
$('#perspectiveSelect').value=model.perspective.mode||'neutral';
window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
if(DATA.editor.revision){try{restore(DATA.editor.revision,true);}catch(error){status(error.message,true);}}
else{
 renderDocument();renderCards();updateStatus();
 try{const cached=localStorage.getItem(cacheKey);if(cached){$('#cacheNotice').textContent='发现本合同的临时恢复记录。请恢复后主动保存 JSON。';$('#restoreCache').hidden=false;$('#restoreCache').onclick=()=>{try{restore(JSON.parse(cached),false);$('#restoreCache').hidden=true;status('已恢复浏览器临时记录，仍需保存 JSON。');}catch(error){status(error.message,true);}};}}catch{}
}
window.reviewEditor={export:revision,validate:replay,restore,identity:clone(doc.identity)};
})();
