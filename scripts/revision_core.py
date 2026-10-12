"""Deterministic V2 revision protocol. Offsets are Unicode code points, not UTF-16."""
from __future__ import annotations
import copy
import hashlib
import re
from common import build_full_text

def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

def nodes_for(contract):
    if contract.get('nodes'):
        return copy.deepcopy(contract['nodes'])
    nodes = []
    for block in contract['blocks']:
        bid = block['block_id']
        if block.get('kind') == 'table' and block.get('cells'):
            cursor = 0
            for ri, row in enumerate(block['cells']):
                for ci, cell in enumerate(row):
                    text = cell['text']
                    nodes.append({'node_id': f'{bid}-r{ri}-c{ci}', 'block_id': bid,
                                  'kind': 'cell', 'row': ri, 'col': ci, 'text': text,
                                  'block_start': cursor, 'editable': cell.get('editable', False),
                                  'locator': cell.get('locator')})
                    cursor += len(text) + (3 if ci < len(row)-1 else 0)
                cursor += 1 if ri < len(block['cells'])-1 else 0
        else:
            nodes.append({'node_id': bid, 'block_id': bid, 'kind': 'readonly' if block['kind']=='table' else 'paragraph',
                          'text': block['text'], 'block_start': 0,
                          'editable': block.get('editable', block['kind'] != 'table'),
                          'locator': block.get('locator')})
    _, offsets = build_full_text(contract['blocks'])
    for node in nodes:
        node['full_start'] = offsets[node['block_id']][0] + node.get('block_start', 0)
    return nodes

def document_for(contract):
    nodes = nodes_for(contract)
    full, _ = build_full_text(contract['blocks'])
    return {'schema_version': 2,
            'identity': {'file_sha256': contract['file_sha256'], 'content_sha256': sha(full)},
            'source_name': contract['source_name'], 'source_file': contract.get('source_file', ''),
            'original_nodes': nodes}

def replay(document, revision, confirmed_only=False):
    if not isinstance(revision, dict) or revision.get('schema_version') != 2:
        raise ValueError('不支持的修订文件版本。')
    if revision.get('contract') != document['identity']:
        raise ValueError('修订文件与原始合同校验信息不匹配，已阻止加载。')
    original = {n['node_id']: n['text'] for n in document['original_nodes']}
    if revision.get('base_nodes') != original:
        raise ValueError('修订文件中的原文快照与合同不匹配。')
    operations = revision.get('operations')
    if not isinstance(operations, list) or len(operations)>10000 or not isinstance(revision.get('history'), list):
        raise ValueError('修订操作或历史格式无效。')
    nodes = copy.deepcopy(document['original_nodes'])
    ids = set()
    historical_nodes={n['node_id']:n for n in nodes}
    undone=[];seen_undone=False
    for op in operations:
        if not isinstance(op, dict) or not op.get('id') or op['id'] in ids:
            raise ValueError('修改编号缺失或重复。')
        ids.add(op['id'])
        if op.get('status') not in {'active','undone','abandoned'} or op.get('decision') not in {'pending','confirmed','rejected'}:
            raise ValueError('修订状态不合法。')
        if op.get('source') not in {'manual','ai'} or not isinstance(op.get('perspective'), dict) or not op.get('time'):
            raise ValueError('修改来源、视角或时间缺失。')
        # Validate even inactive branches: they may be replayed by Redo later.
        kind=op.get('type');before=op.get('before_text');after=op.get('after_text')
        start,end=op.get('start'),op.get('end');inserted=op.get('inserted_text')
        if not isinstance(before,str) or not isinstance(after,str) or not isinstance(inserted,str) or type(start)is not int or type(end)is not int or not 0<=start<=end<=len(before):
            raise ValueError('历史修改内容或位置不合法。')
        if before[start:end]!=op.get('removed_text') or before[:start]+inserted+before[end:]!=after:
            raise ValueError('历史修改片段与前后文本不一致。')
        if kind=='insert_node':
            if not re.fullmatch(r'n-[A-Za-z0-9_-]+',op.get('node_id','')) or op['node_id'] in historical_nodes or before!='' or op.get('anchor_node_id') not in historical_nodes:
                raise ValueError('历史新增节点或锚点不合法。')
            anchor=historical_nodes[op['anchor_node_id']]
            if anchor.get('kind')=='cell' and op['anchor_node_id']!=[n for n in document['original_nodes'] if n['block_id']==anchor['block_id']][-1]['node_id']:
                raise ValueError('历史新增条款位于表格内部，不能恢复。')
            historical_nodes[op['node_id']]={'node_id':op['node_id'],'editable':True}
        elif kind not in {'insert','delete','replace'} or not historical_nodes.get(op.get('node_id'),{}).get('editable'):
            raise ValueError('历史节点不可编辑或修改类型未知。')
        if op['status']=='undone':
            seen_undone=True;undone.append(op['id'])
        elif op['status']=='active' and seen_undone:
            raise ValueError('恢复分支与有效操作顺序冲突。')
        if op['status'] != 'active' or op['decision'] == 'rejected':
            continue
        if confirmed_only and op['decision'] != 'confirmed':
            raise ValueError('存在未确认修改；请先由用户确认，不能自动生成最终 Word。')
        kind = op.get('type')
        if kind == 'insert_node':
            if not re.fullmatch(r'n-[A-Za-z0-9_-]+', op.get('node_id','')) or any(n['node_id']==op['node_id'] for n in nodes):
                raise ValueError('新增节点编号不合法或重复。')
            anchor = next((i for i,n in enumerate(nodes) if n['node_id']==op.get('anchor_node_id')), None)
            if anchor is None or not isinstance(op.get('after_text'), str) or op.get('before_text')!='':
                raise ValueError('新增条款锚点或内容无效。')
            # Only paragraphs, or the final cell of a table, can be insert anchors.
            if anchor+1 < len(nodes) and nodes[anchor+1]['block_id'] == nodes[anchor]['block_id']:
                raise ValueError('不能在表格单元格之间插入段落。')
            nodes.insert(anchor+1, {'node_id':op['node_id'], 'block_id':op['node_id'], 'kind':'paragraph',
                                   'text':op['after_text'], 'editable':True,'inserted':True,'anchor_node_id':op['anchor_node_id']})
        elif kind in {'insert','delete','replace'}:
            node = next((n for n in nodes if n['node_id']==op.get('node_id')), None)
            if not node or not node.get('editable'):
                raise ValueError('修改节点不存在或为只读结构。')
            if node['text'] != op.get('before_text'):
                raise ValueError('连续修改的前文校验失败，存在冲突。')
            start, end = op.get('start'), op.get('end')
            if type(start) is not int or type(end) is not int or not 0 <= start <= end <= len(node['text']):
                raise ValueError('修改位置越界。')
            replacement = op.get('inserted_text')
            if not isinstance(replacement,str) or node['text'][start:end] != op.get('removed_text'):
                raise ValueError('删除片段与原文不匹配。')
            after = node['text'][:start] + replacement + node['text'][end:]
            if after != op.get('after_text'):
                raise ValueError('修改后内容与操作不一致。')
            node['text'] = after
        else:
            raise ValueError('未知修改类型。')
    if revision.get('current_nodes') != {n['node_id']:n['text'] for n in nodes}:
        raise ValueError('保存的当前稿与操作重放结果不一致。')
    if revision.get('redo_stack',[])!=list(reversed(undone)):
        raise ValueError('恢复栈与已撤销历史不一致。')
    future=copy.deepcopy(nodes)
    for op in [o for o in operations if o['status']=='undone']:
        if op['type']=='insert_node':
            at=next((i for i,n in enumerate(future) if n['node_id']==op['anchor_node_id']),None)
            if at is None:raise ValueError('已撤销条款的恢复锚点不存在。')
            future.insert(at+1,{'node_id':op['node_id'],'block_id':op['node_id'],'kind':'paragraph','text':op['after_text'],'editable':True})
        else:
            node=next((n for n in future if n['node_id']==op['node_id']),None)
            if not node or node['text']!=op['before_text']:
                raise ValueError('已撤销操作的前文无法连续恢复。')
            node['text']=op['after_text']
    for node in nodes:
        node['changed'] = node.get('inserted',False) or node['text'] != original.get(node['node_id'])
    return nodes

def contract_from_nodes(original, nodes):
    result = copy.deepcopy(original)
    by_block = {}
    for node in nodes:
        by_block.setdefault(node['block_id'], []).append(node)
    blocks = []
    old = {b['block_id']:b for b in original['blocks']}
    for bid, group in by_block.items():
        if bid in old:
            block = copy.deepcopy(old[bid])
        else:
            block = {'block_id':bid,'kind':'para'}
        if group[0]['kind']=='cell':
            rows = []
            for node in group:
                while len(rows) <= node['row']:
                    rows.append([])
                rows[node['row']].append(node['text'])
            block['text'] = '\n'.join(' | '.join(row) for row in rows)
            if block.get('cells'):
                for node in group:
                    block['cells'][node['row']][node['col']]['text'] = node['text']
        else:
            block['text'] = group[0]['text']
        blocks.append(block)
    result['blocks'] = blocks
    result['full_text'], result['block_offsets'] = build_full_text(blocks)
    result['char_count'] = len(result['full_text'])
    result.pop('nodes', None)
    result['nodes'] = nodes_for(result)
    result['derived_from_revisions'] = True
    return result
