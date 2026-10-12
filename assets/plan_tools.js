/* Fixed, DOM-free preflight for compiled plans. WorkBuddy owns semantics. */
(() => {
'use strict';
const cp=s=>Array.from(s),clone=x=>JSON.parse(JSON.stringify(x));
const canonical=x=>Array.isArray(x)?x.map(canonical):x&&typeof x==='object'?Object.fromEntries(Object.keys(x).sort().map(k=>[k,canonical(x[k])])):x;
const equal=(a,b)=>JSON.stringify(canonical(a))===JSON.stringify(canonical(b));
async function hash(value){const bytes=new TextEncoder().encode(JSON.stringify(canonical(value)));const result=await crypto.subtle.digest('SHA-256',bytes);return [...new Uint8Array(result)].map(x=>x.toString(16).padStart(2,'0')).join('');}
async function verify(plan){
 if(!globalThis.crypto?.subtle?.digest)throw Error('浏览器不支持本地计划指纹核验，请使用支持Web Crypto的现代浏览器。');
 if(!plan||!plan.can_apply||!Array.isArray(plan.checks)||plan.checks.some(c=>c.result!=='pass'))throw Error('计划未满足系统应用条件，需补充或重新核验。');
 const payload=clone(plan);delete payload.compiled_digest;
 if(await hash(payload)!==plan.compiled_digest)throw Error('计划内容已变化，需返回WorkBuddy重新校验。');
 if(plan.raw_plan?.semantic_review?.plan_fingerprint!==plan.plan_fingerprint)throw Error('语义审查与计划不匹配。');
}
function preflight(plan,nodes){
 if(!plan?.can_apply)throw Error('修改计划尚不可应用。');
 const byId=new Map(nodes.map(n=>[n.node_id,n]));
 for(const [id,text] of Object.entries(plan.scope_node_texts||{}))if(byId.get(id)?.text!==text)throw Error('相关条款已修改，计划需重新核验：'+id);
 const grouped=new Map(),ids=new Set();
 for(const e of plan.edits||[]){
  const n=byId.get(e.target_node_id);if(!n||ids.has(e.edit_id)||n.text!==e.expected_node_text)throw Error('整组目标、原文或动作ID校验失败。');ids.add(e.edit_id);
  if(!['partial','replace','insert_clause','delete_clause'].includes(e.operation)||typeof e.replacement_text!=='string')throw Error('计划操作或正式文本错误。');
  if(e.operation!=='insert_clause'&&!n.editable)throw Error('计划含只读目标。');
  if(e.operation==='insert_clause'){
   if(e.expected_original!==n.text||nodes.filter(x=>x.block_id===n.block_id).at(-1).node_id!==n.node_id||!e.replacement_text.trim())throw Error('插入锚点或文字错误。');
  }else if(!Number.isInteger(e.start)||!Number.isInteger(e.end)||e.start<0||e.end<e.start||e.end>cp(n.text).length||cp(n.text).slice(e.start,e.end).join('')!==e.expected_original)throw Error('局部位置或原文不匹配。');
  const a=grouped.get(n.node_id)||[];a.push(e);grouped.set(n.node_id,a);
 }
 const steps=[];
 for(const [id,edits] of grouped){
  for(let i=0;i<edits.length;i++)for(const b of edits.slice(i+1)){const a=edits[i];if(a.operation!=='partial'||b.operation!=='partial'||Math.max(a.start,b.start)<Math.min(a.end,b.end)||a.start===b.start)throw Error('关联修改范围冲突。');}
  const before=byId.get(id).text;
  if(edits[0].operation==='insert_clause'){steps.push({kind:'insert',anchor:id,before:'',after:edits[0].replacement_text,edit_ids:edits.map(e=>e.edit_id)});continue;}
  let after=before;
  for(const e of [...edits].sort((a,b)=>b.start-a.start)){const a=cp(after);after=a.slice(0,e.start).join('')+e.replacement_text+a.slice(e.end).join('');}
  if(after===before)throw Error('计划没有产生文字变化。');
  if(!plan.preview_nodes.some(n=>n.node_id===id&&n.before===before&&n.after===after))throw Error('组内执行结果与核验预览不同。');
  steps.push({kind:'replace',node_id:id,before,after,edit_ids:edits.map(e=>e.edit_id)});
 }
 if(!steps.length)throw Error('计划缺少执行步骤。');return steps;
}
function validateGroups(value){
 const groups=value.plan_groups||{},ops=value.operations;
 if(typeof groups!=='object'||Array.isArray(groups)||groups===null)throw Error('关联修改组格式错误。');
 for(const [gid,g] of Object.entries(groups)){
  const actual=ops.filter(o=>o.group_id===gid),ids=g.operation_ids;
  if(g.group_id!==gid||!Array.isArray(ids)||!ids.length||new Set(ids).size!==ids.length||!equal(actual.map(o=>o.id),ids))throw Error('关联修改组步骤不完整。');
  const first=ops.indexOf(actual[0]);if(actual.some((o,i)=>ops[first+i]!==o))throw Error('关联修改组记录不连续。');
  if(new Set(actual.map(o=>o.status)).size!==1||new Set(actual.map(o=>o.decision)).size!==1)throw Error('关联修改组不能部分撤销、确认或拒绝。');
  if(!g.snapshot?.can_apply||g.plan_fingerprint!==g.snapshot.plan_fingerprint||g.plan_id!==g.snapshot.plan_id||g.snapshot.source_file_sha256!==value.contract.file_sha256||actual.some(o=>o.plan_id!==g.plan_id))throw Error('关联修改计划快照或原文件不匹配。');
 }
 if(ops.some(o=>o.group_id&&!groups[o.group_id]))throw Error('关联修改动作缺少整组记录。');
}
window.ClausePlanTools={hash,verify,preflight,validateGroups};
})();
