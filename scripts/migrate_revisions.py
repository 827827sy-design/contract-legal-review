"""Migrate untouched phantom prefix tabs emitted from paragraph tab-stop settings."""
import copy,argparse
from pathlib import Path
from common import read_json,write_json,now_iso
from revision_core import document_for,replay
def migrate(document,revision):
    value=copy.deepcopy(revision)
    if value.get('contract')==document['identity']:return value,False
    if value.get('contract',{}).get('file_sha256')!=document['identity']['file_sha256']:raise ValueError('原始合同文件不匹配，不能迁移修订')
    changes={};base=value.get('base_nodes',{})
    if set(base)!={n['node_id'] for n in document['original_nodes']}:raise ValueError('旧修订节点集合不匹配，不能迁移')
    for n in document['original_nodes']:
        id=n['node_id'];old=base[id]
        if old==n['text']:continue
        count=n.get('legacy_layout_tabstop_count',0)
        if not count or old!='\t'*count+n['text']:raise ValueError('旧原文差异不是已核验的格式Tab声明，需WorkBuddy核对')
        if value.get('current_nodes',{}).get(id)!=old or any(o.get('node_id')==id for o in value.get('operations',[])):raise ValueError('旧修订修改过表示发生变化的段落，需WorkBuddy核验，不能猜测范围')
        changes[id]=n['text']
    for group in value.get('plan_groups',{}).values():
        if set(group.get('snapshot',{}).get('scope_node_texts',{}))&set(changes):raise ValueError('旧计划关联范围包含表示变化的段落，保留旧文件并重新核验该计划')
    if not changes:raise ValueError('合同内容标识不匹配且没有可核验迁移差异')
    value['contract']=copy.deepcopy(document['identity']);value['base_nodes'].update(changes);value['current_nodes'].update(changes)
    value['history'].append({'action':'migrate_layout_tab_representation','time':now_iso(),'changed_nodes':list(changes),'semantic_review_performed':False})
    replay(document,value);return value,True
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--task-dir',required=True);ap.add_argument('--revisions',required=True);ap.add_argument('--output',required=True);a=ap.parse_args()
    p=Path(a.output)
    if p.exists() or p.resolve()==Path(a.revisions).resolve():raise ValueError('必须保存为新的JSON文件，禁止覆盖旧记录')
    c=read_json(Path(a.task_dir)/'contract.json');value,changed=migrate(document_for(c),read_json(Path(a.revisions)));write_json(p,value);print('已迁移并校验旧修订；请使用新的JSON。' if changed else '无需迁移，校验通过。')
if __name__=='__main__':main()
