"""Deterministic fields in a pre-reviewed semantic envelope; no new model claim."""
import copy,re,datetime
from decimal import Decimal,InvalidOperation
def field_value(rule,value):
    if not isinstance(value,str):raise ValueError('填写值须为文字')
    value=value.strip();kind=rule.get('kind')
    if not value or len(value)>rule.get('max_length',80) or re.search(r'[\r\n\t{}<>【】]',value):raise ValueError('字段为空、过长或含不允许的结构内容')
    if kind=='date':
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):raise ValueError('日期需采用YYYY-MM-DD')
        datetime.date.fromisoformat(value)
    elif kind=='decimal':
        if not re.fullmatch(r'\d+(?:\.\d{1,2})?',value) or 'min' not in rule or 'max' not in rule:raise ValueError('金额/数字需在已审查的数值范围内')
        number=Decimal(value)
        if not Decimal(str(rule['min']))<=number<=Decimal(str(rule['max'])):raise ValueError('数字超出已审查字段范围')
    elif kind=='short_text':
        if not rule.get('max_length') or rule['max_length']>80:raise ValueError('文字字段缺少有效长度范围')
        import unicodedata
        if any(unicodedata.category(char)[0] not in {'L','M','N'} and char not in '_（）() @./+-' for char in value):raise ValueError('短事实字段不能含条款分隔符或引号；复杂文字请重新核验')
    else:raise ValueError('此字段变化需语义复核')
    return value
def derive(template,values):
    rules=template.get('field_bindings',[])
    if not rules or not isinstance(values,dict) or set(values)!={r.get('id') for r in rules}:raise ValueError('填写字段与已审查规则不一致')
    p=copy.deepcopy(template);p.pop('materialization',None)
    policy=p.get('semantic_review',{}).get('field_policy',{})
    if policy.get('approved') is not True or set(policy.get('field_ids',[]))!=set(values):raise ValueError('字段规则未经过必要语义审查')
    questions={q['id']:q for q in p.get('questions',[])};edit_by_id={e['edit_id']:e for e in p.get('edits',[])}
    for rule in rules:
        id=rule['id'];marker='{{field:'+id+'}}';value=field_value(rule,values[id])
        if rule.get('semantic_effect')!='fact_only' or rule.get('question_id') not in questions:raise ValueError('仅允许预审过的事实字段；商务机制变化需返回WorkBuddy')
        targets=rule.get('edit_ids',[])
        if not targets or any(eid not in edit_by_id or marker not in (edit_by_id[eid].get('replacement_text') or '') for eid in targets):raise ValueError('字段没有完整绑定修改位置')
        for eid in targets:edit_by_id[eid]['replacement_text']=edit_by_id[eid]['replacement_text'].replace(marker,value)
        q=questions[rule['question_id']];q.update(answer=value,confirmed=True,answer_source='用户确认事实，按预审字段规则填写')
    return p
def instantiate(template,values):
    p=derive(template,values);p['materialization']={'template':copy.deepcopy(template),'values':copy.deepcopy(values),'facts_confirmed':True};return p
def validate_materialization(plan,contract,analysis,basis):
    m=plan.get('materialization')
    if not isinstance(m,dict) or m.get('facts_confirmed') is not True:return False
    template=m.get('template')
    if not isinstance(template,dict) or template.get('materialization'):return False
    from plan_quality import evaluate_plan
    try:
        inspected=evaluate_plan(template,contract,analysis,basis)
        if any(c['result']!='pass' and c['code'] not in {'formal_text','business'} for c in inspected['checks']):return False
        expected=derive(template,m.get('values'));actual=copy.deepcopy(plan);actual.pop('materialization',None)
        return actual==expected
    except (ValueError,TypeError,KeyError):return False
