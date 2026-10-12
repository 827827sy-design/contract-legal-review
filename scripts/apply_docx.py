"""WorkBuddy-side confirmed revision export. Never overwrites original DOCX."""
from __future__ import annotations
import argparse
import copy
import io
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from common import read_json, file_sha256, force_utf8_stdio
from revision_core import document_for,replay
from extract_contract import W,_docx_paragraph_text
from docx_tracked import Tracker,replace_tracked

def replace_text(paragraph,before,after):
    if _docx_paragraph_text(paragraph)!=before:
        raise ValueError('Word 结构原文与解析快照不匹配。')
    if '\n' in after or '\t' in after:
        raise ValueError('自动 Word 导出不支持段内换行/制表符变更，请让 WorkBuddy 人工处理结构。')
    texts=list(paragraph.iter(W+'t'))
    if not texts:
        run=ET.SubElement(paragraph,W+'r');texts=[ET.SubElement(run,W+'t')]
    a,b=0,0
    while a<min(len(before),len(after)) and before[a]==after[a]:a+=1
    while b<min(len(before)-a,len(after)-a) and before[-1-b]==after[-1-b]:b+=1
    end=len(before)-b;replacement=after[a:len(after)-b if b else len(after)]
    offset=0; inserted=False
    for text in texts:
        value=text.text or ''; stop=offset+len(value)
        if not inserted and offset<=a<=stop:
            left=value[:a-offset];right=value[max(0,end-offset):] if end<stop else ''
            text.text=left+replacement+right;inserted=True
        elif offset<end and stop>a:
            text.text=value[:max(0,a-offset)]+value[max(0,end-offset):]
        text.set('{http://www.w3.org/XML/1998/namespace}space','preserve')
        offset=stop
    if _docx_paragraph_text(paragraph)!=after:
        raise ValueError('Word 文字更新校验失败。')

def main():
    force_utf8_stdio();ap=argparse.ArgumentParser()
    ap.add_argument('--original',required=True);ap.add_argument('--task-dir',required=True)
    ap.add_argument('--revisions',required=True);ap.add_argument('--output',required=True)
    ap.add_argument('--track-changes',action='store_true',help='普通段落的修改也以Word原生修订记录；已有修订的修改始终追加修订')
    ap.add_argument('--author',default='Contract Review',help='新增Word修订的作者名')
    args=ap.parse_args();src=Path(args.original);out=Path(args.output);task=Path(args.task_dir)
    if out.resolve()==src.resolve() or out.exists():raise ValueError('输出必须是新的文件，禁止覆盖原始合同或已有 Word。')
    contract=read_json(task/('base_contract.json' if (task/'base_contract.json').exists() else 'contract.json'))
    if file_sha256(src)!=contract['file_sha256']:raise ValueError('原始 DOCX 校验和不匹配。')
    revision=read_json(Path(args.revisions));nodes=replay(document_for(contract),revision,confirmed_only=True)
    if src.suffix.lower()!='.docx':raise ValueError('自动导出仅支持 DOCX。其他格式请由 WorkBuddy 转换。')
    with zipfile.ZipFile(src) as archive:
        original_xml=archive.read('word/document.xml')
        namespaces={}
        for _,(prefix,uri) in ET.iterparse(io.BytesIO(original_xml),events=['start-ns']):
            namespaces[prefix]=uri
            if not prefix.startswith('ns'):ET.register_namespace(prefix,uri)
        root=ET.fromstring(original_xml);body=root.find(W+'body');original_elements=list(body)
        tracker=Tracker(root,args.author)
        anchors={};last_body_element=None
        for node in nodes:
            if node.get('inserted'):
                anchor=last_body_element if node['anchor_node_id'] in anchors else None
                if anchor is None:raise ValueError('新增条款 Word 锚点不可用。')
                p=ET.Element(W+'p');run=ET.Element(W+'r');t=ET.SubElement(run,W+'t');t.text=node['text'];t.set('{http://www.w3.org/XML/1998/namespace}space','preserve')
                p.append(tracker.wrap('ins',run) if args.track_changes else run)
                if '\n' in node['text'] or '\t' in node['text']:raise ValueError('新增条款须为单段文本。')
                body.insert(list(body).index(anchor)+1,p);anchors[node['node_id']]=p;last_body_element=p;continue
            loc=node.get('locator')
            if not loc:
                if node['changed']:raise ValueError('旧解析结果缺少 Word 节点映射，请重新解析原始 DOCX。')
                continue
            element=original_elements[loc['body_index']];anchors[node['node_id']]=element;last_body_element=element
            paragraph=element if loc['kind']=='paragraph' else element.findall(W+'tr')[loc['row']].findall(W+'tc')[loc['col']].find(W+'p')
            if node['changed']:
                has_revisions=any(n.tag in {W+'ins',W+'del',W+'rPrChange',W+'pPrChange'} for n in paragraph.iter())
                if has_revisions or args.track_changes:
                    replace_tracked(paragraph,revision['base_nodes'][node['node_id']],node['text'],tracker)
                else:replace_text(paragraph,revision['base_nodes'][node['node_id']],node['text'])
        payload=ET.tostring(root,encoding='utf-8',xml_declaration=True)
        # ET omits unused namespace declarations referenced by mc:Ignorable.
        ignorable=root.get('{http://schemas.openxmlformats.org/markup-compatibility/2006}Ignorable','').split()
        for prefix in ignorable:
            if prefix in namespaces and ('xmlns:'+prefix+'=').encode() not in payload:
                root.set('xmlns:'+prefix,namespaces[prefix])
        payload=ET.tostring(root,encoding='utf-8',xml_declaration=True)
        out.parent.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(out,'x',zipfile.ZIP_DEFLATED) as target:
            for info in archive.infolist():target.writestr(info,payload if info.filename=='word/document.xml' else archive.read(info.filename))
    # Verify actual output text before reporting success; source is never written.
    print(f'已生成新文件：{out}。新增Word修订标记 {len(tracker.ids)} 个；原有修订与批注保留，未接受或拒绝。')

if __name__=='__main__':main()
