/* Deterministic instantiation of explicitly pre-reviewed fact fields. */
(()=>{'use strict';const clone=x=>JSON.parse(JSON.stringify(x)),H=x=>ClausePlanTools.hash(x);
function fieldValue(r,value){
 if(typeof value!=='string')throw Error('填写值须为文字');value=value.trim();
 if(!value||Array.from(value).length>(r.max_length||80)||/[\r\n\t{}<>【】]/.test(value))throw Error('字段为空、过长或包含不允许的内容');
 if(r.kind==='date'){if(!/^\d{4}-\d{2}-\d{2}$/.test(value)||Number(value.slice(0,4))<1||!Number.isFinite(Date.parse(value+'T00:00:00Z'))||new Date(value+'T00:00:00Z').toISOString().slice(0,10)!==value)throw Error('请填写有效YYYY-MM-DD日期');}
 else if(r.kind==='decimal'){const cents=x=>BigInt(String(x).split('.')[0])*100n+BigInt((String(x).split('.')[1]||'').padEnd(2,'0'));if(!/^\d+(\.\d{1,2})?$/.test(value)||![r.min,r.max].every(x=>/^\d+(\.\d{1,2})?$/.test(String(x)))||cents(value)<cents(r.min)||cents(value)>cents(r.max))throw Error('数字超出已审查范围或格式无效');}
 else if(r.kind!=='short_text'||!r.max_length||r.max_length>80||!/^[\p{L}\p{M}\p{N}_（）() @./+\-]+$/u.test(value))throw Error('短事实字段不能含条款分隔符或引号；复杂文字需要语义核验');return value;
}
function derive(template,values){const p=clone(template),rules=p.field_bindings||[],policy=p.semantic_review?.field_policy;delete p.materialization;
 if(!rules.length||!policy?.approved||JSON.stringify([...Object.keys(values)].sort())!==JSON.stringify(rules.map(r=>r.id).sort())||JSON.stringify([...policy.field_ids].sort())!==JSON.stringify(Object.keys(values).sort()))throw Error('字段规则尚未完成预审');
 for(const r of rules){const marker='{{field:'+r.id+'}}',value=fieldValue(r,values[r.id]),q=p.questions?.find(q=>q.id===r.question_id);
  if(r.semantic_effect!=='fact_only'||!q||!r.edit_ids?.length)throw Error('仅允许按已审查规则填写事实字段');
  for(const id of r.edit_ids){const e=p.edits.find(e=>e.edit_id===id);if(!e?.replacement_text?.includes(marker))throw Error('字段修改位置未完整绑定');e.replacement_text=e.replacement_text.split(marker).join(value);}
  Object.assign(q,{answer:value,confirmed:true,answer_source:'用户确认事实，按预审字段规则填写'});
 }return p;
}
async function fingerprint(raw,scope,analysis,basis){const keys=['plan_id','risk_id','reason','questions','edits','business_terms','required_edit_node_ids','postconditions','amount_records','literal_bracket_terms','related_risk_ids','source_revision_basis','risk_context','input_draft_id','source_file_sha256','condition_changes'];
 const p=Object.fromEntries(keys.map(k=>[k,raw[k]??null]));for(const k of ['field_bindings','materialization','no_edit_reason'])if(Object.hasOwn(raw,k))p[k]=raw[k];
 const relevant=analysis?{edges:(analysis.edges||[]).filter(e=>Object.hasOwn(scope,e.from)||Object.hasOwn(scope,e.to)),obligations:(analysis.obligations||[]).filter(o=>o.node_ids?.some(id=>Object.hasOwn(scope,id)))}:null;
 return H({plan:p,scope_node_texts:scope,analysis:relevant,risk_basis:basis||[]});
}
async function verifyMaterialization(p){const m=p.raw_plan?.materialization;if(!m?.facts_confirmed||m.template?.materialization)throw Error('字段填写未获确认');
 const derived=derive(m.template,m.values),actual=clone(p.raw_plan);delete actual.materialization;
 if(await H(derived)!==await H(actual))throw Error('草案超出预审字段替换范围');
 if(p.semantic_review_mode!=='pre_reviewed_field_materialization'||p.raw_plan.semantic_review?.plan_fingerprint!==m.template.semantic_review?.plan_fingerprint||p.plan_fingerprint!==await fingerprint(p.raw_plan,p.scope_node_texts,p.analysis,p.risk_basis))throw Error('字段来源与原语义审查不匹配');
}
async function instantiate(template,values){
 const payload=clone(template);delete payload.compiled_digest;
 if(await H(payload)!==template.compiled_digest||template.checks.some(c=>c.result!=='pass'&&!['formal_text','business'].includes(c.code)))throw Error('原草案还有字段之外的问题，不能直接填写应用');
 const raw=derive(template.raw_plan,values);raw.materialization={template:clone(template.raw_plan),values:clone(values),facts_confirmed:true};
 if(raw.questions.some(q=>q.required!==false&&!q.confirmed))throw Error('仍有必要条件尚未确认');
 const p=clone(template);p.raw_plan=raw;p.questions=raw.questions;p.materialization=raw.materialization;p.semantic_review_mode='pre_reviewed_field_materialization';
 p.edits=p.edits.map(e=>({...e,replacement_text:raw.edits.find(x=>x.edit_id===e.edit_id).replacement_text}));
 const after={...p.scope_node_texts};for(const e of [...p.edits].sort((a,b)=>b.start-a.start)){if(e.operation==='insert_clause')continue;const a=Array.from(after[e.target_node_id]);after[e.target_node_id]=a.slice(0,e.start).join('')+e.replacement_text+a.slice(e.end).join('');}
 for(const e of p.edits)if(/【[^】]+】|\{\{[^}]+\}\}|_{2,}|（示例文本）|\(示例文本\)/.test(e.replacement_text))throw Error('仍有未完成文字');
 for(const c of raw.postconditions||[]){const text=c.node_ids.map(id=>after[id]).join('\n');if(c.type==='absent'?text.includes(c.text):!text.includes(c.text))throw Error('字段填写后的文字条件未满足');}
 p.preview_nodes=Object.keys(after).filter(id=>after[id]!==p.scope_node_texts[id]).map(id=>({node_id:id,before:p.scope_node_texts[id],after:after[id]}));
 p.plan_fingerprint=await fingerprint(raw,p.scope_node_texts,p.analysis,p.risk_basis);p.can_apply=true;p.readiness=p.edits.length>1?'coordinated_review':'ready';p.quality_result='已满足系统检查条件';p.blockers=[];
 p.checks=p.checks.map(c=>['formal_text','business'].includes(c.code)?{...c,result:'pass',reason:'已按预审字段规则填入并由用户确认事实，未新增语义审查'}:c);
 p.validation={...p.validation,business_terms_confirmed:true};p.compiled_digest=await H(Object.fromEntries(Object.entries(p).filter(([k])=>k!=='compiled_digest')));return p;
}
window.ProposalTools={fieldValue,derive,instantiate,verifyMaterialization,fingerprint};})();
