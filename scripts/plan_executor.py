"""Execute a validated plan on a copy, commit the group only after full replay."""
from __future__ import annotations
import copy,uuid
from common import now_iso
from plan_quality import verify_compiled
from revision_core import document_for,replay

def execution_steps(plan,nodes):
    by_id={n['node_id']:n['text'] for n in nodes};groups={};steps=[]
    for e in plan['edits']:groups.setdefault(e['target_node_id'],[]).append(e)
    for id,edits in groups.items():
        if plan.get('execution_protocol')!=2 and edits[0]['operation']!='insert_clause':
            before=by_id[id];after=next(n['after'] for n in plan['preview_nodes'] if n['node_id']==id)
            steps.append({'kind':'replace','node_id':id,'before':before,'after':after,'start':0,'end':len(before),'removed':before,'inserted':after,'edit_ids':[e['edit_id'] for e in edits]});continue
        for e in sorted(edits,key=lambda e:e.get('start',0),reverse=True):
            if e['operation']=='insert_clause':steps.append({'kind':'insert','anchor':id,'before':'','after':e['replacement_text'],'start':0,'end':0,'removed':'','inserted':e['replacement_text'],'edit_ids':[e['edit_id']]});continue
            before=by_id[id];start,end=e['start'],e['end'];after=before[:start]+e['replacement_text']+before[end:]
            steps.append({'kind':'replace','node_id':id,'before':before,'after':after,'start':start,'end':end,'removed':before[start:end],'inserted':e['replacement_text'],'edit_ids':[e['edit_id']]});by_id[id]=after
    return steps
def execute_plan(contract,revision,plan,accept_negotiation=False):
    document=document_for(contract);current=replay(document,revision)
    compiled=verify_compiled(plan,{'nodes':current,'blocks':[],'file_sha256':contract['file_sha256']})
    if compiled.get('proposed_terms') and not accept_negotiation:raise ValueError('须明确接受拟议谈判条件，不能把推荐值当成既定事实。')
    for group in revision.get('plan_groups',{}).values():
        active=any(op.get('group_id')==group['group_id'] and op['status']=='active' for op in revision['operations'])
        if active and group['plan_fingerprint']==compiled['plan_fingerprint']:raise ValueError('同一修改计划已应用，不能重复执行。')
    proposed=copy.deepcopy(revision);groups=proposed.setdefault('plan_groups',{})
    abandoned=set(proposed.get('redo_stack',[]))
    for op in proposed['operations']:
        if op['id'] in abandoned:op['status']='abandoned'
    proposed['redo_stack']=[]
    gid='group-'+uuid.uuid4().hex;operation_ids=[]
    for step in execution_steps(compiled,current):
        before,after=step['before'],step['after'];edit_ids=step['edit_ids']
        if step['kind']=='insert':
            nid='n-'+uuid.uuid4().hex;target=step['anchor']
            op={'type':'insert_node','node_id':nid,'anchor_node_id':target,'start':0,'end':0,'removed_text':'','inserted_text':after}
            anchor=next(i for i,n in enumerate(current) if n['node_id']==target);current.insert(anchor+1,{'node_id':nid,'block_id':nid,'kind':'paragraph','text':after,'editable':True,'inserted':True,'anchor_node_id':target})
        else:
            target=step['node_id']
            node=next(n for n in current if n['node_id']==target)
            if node['text']!=before:raise ValueError('整组执行前原文发生冲突。')
            op={'type':'replace' if step['inserted'] else 'delete','node_id':target,'start':step['start'],'end':step['end'],'removed_text':step['removed'],'inserted_text':step['inserted']}
            node['text']=after
        oid='rev-'+uuid.uuid4().hex;operation_ids.append(oid)
        proposed['operations'].append({**op,'id':oid,'before_text':before,'after_text':after,'status':'active','decision':'pending',
                   'source':'ai','perspective':copy.deepcopy(proposed.get('perspective',{'mode':'neutral'})),'time':now_iso(),
                   'group_id':gid,'plan_id':compiled['plan_id'],'edit_ids':edit_ids,'risk_id':compiled.get('risk_identity',{}).get('display_id',compiled.get('risk_id')),'analysis_risk_id':compiled.get('risk_identity',{}).get('analysis_id',compiled.get('risk_id')),
                   'reason':compiled.get('reason',''),'review_id':compiled.get('review_id','')})
    groups[gid]={'group_id':gid,'plan_id':compiled['plan_id'],'plan_fingerprint':compiled['plan_fingerprint'],
                 'operation_ids':operation_ids,'snapshot':compiled,'accepted_negotiation_terms':copy.deepcopy(compiled.get('proposed_terms',[]))}
    proposed['current_nodes']={n['node_id']:n['text'] for n in current}
    proposed.setdefault('history',[]).append({'action':'apply_plan','group_id':gid,'time':now_iso(),'risk_status':'needs_re_review'})
    proposed.setdefault('risk_status',{})[compiled.get('risk_id') or compiled['plan_id']]={'status':'needs_re_review','group_id':gid}
    replay(document,proposed)
    return proposed
def verify_group_steps(group,operations,nodes):
    expected=execution_steps(group['snapshot'],nodes);actual=[o for o in operations if o.get('group_id')==group['group_id']]
    if len(actual)!=len(expected):raise ValueError('关联组动作数与正式计划不一致')
    # Old snapshots use the original merged protocol; new partial operations
    # retain the precise reviewed range.
    for step,op in zip(expected,actual):
        keys={'before_text':step['before'],'after_text':step['after'],'edit_ids':step['edit_ids']}
        if step['kind']=='insert':keys['anchor_node_id']=step['anchor']
        else:keys.update(node_id=step['node_id'],start=step['start'],end=step['end'],removed_text=step['removed'],inserted_text=step['inserted'])
        if any(op.get(k)!=v for k,v in keys.items()):raise ValueError('关联组执行记录超出已核验计划的文字或范围')

def validate_groups(revision):
    groups=revision.get('plan_groups',{})
    if not isinstance(groups,dict):raise ValueError('关联修改组格式错误。')
    operations=revision['operations'];lookup={o.get('id'):o for o in operations};indices={o.get('id'):i for i,o in enumerate(operations)}
    for gid,group in groups.items():
        if not isinstance(group,dict) or group.get('group_id')!=gid:raise ValueError('关联修改组ID不一致。')
        ids=group.get('operation_ids')
        if not isinstance(ids,list) or not ids or len(ids)!=len(set(ids)) or any(x not in lookup for x in ids):raise ValueError('关联修改组步骤不完整。')
        if [o['id'] for o in operations if o.get('group_id')==gid]!=ids:raise ValueError('关联修改组成员不一致。')
        if [indices[x] for x in ids]!=list(range(indices[ids[0]],indices[ids[0]]+len(ids))):raise ValueError('关联修改组必须连续记录。')
        if len({lookup[x].get('status') for x in ids})!=1 or len({lookup[x].get('decision') for x in ids})!=1:raise ValueError('关联修改组不能部分撤销、确认或拒绝。')
        snapshot=group.get('snapshot',{})
        if snapshot.get('proposed_terms') and group.get('accepted_negotiation_terms')!=snapshot['proposed_terms']:raise ValueError('推荐谈判条件尚未获确认')
        if group.get('plan_fingerprint')!=snapshot.get('plan_fingerprint') or group.get('plan_id')!=snapshot.get('plan_id'):raise ValueError('关联修改组计划快照不一致。')
        if any(lookup[x].get('plan_id')!=group.get('plan_id') for x in ids):raise ValueError('关联修改动作计划ID不一致。')
    if any(o.get('group_id') not in groups for o in operations if o.get('group_id')):raise ValueError('关联修改步骤缺少整组记录。')

def set_group_status(revision,group_id,status):
    value=copy.deepcopy(revision);group=value.get('plan_groups',{}).get(group_id)
    if not group:raise ValueError('关联修改组不存在。')
    selected=[o for o in value['operations'] if o['id'] in group['operation_ids']]
    if status=='undone':
        for o in reversed(selected):o['status']='undone';value['redo_stack'].append(o['id'])
    elif status=='active':
        for o in selected:
            if not value['redo_stack'] or value['redo_stack'].pop()!=o['id']:raise ValueError('关联修改恢复顺序冲突。')
            o['status']='active'
    else:raise ValueError('未知组状态')
    return value
