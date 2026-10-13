"""Edit text islands while preserving actual tab/break elements and attributes."""
import copy,re
from extract_contract import W,_docx_paragraph_text
def control_signature(text):return re.findall(r'[\t\n]',text)
def validate_controls(before,after):
    if control_signature(before)!=control_signature(after):raise ValueError('普通文字可编辑，但Tab/换行结构必须保留。请保留分隔符或由WorkBuddy处理结构变更。')
def islands(paragraph):
    groups=[[]]
    def walk(parent):
        for child in parent:
            if child.tag in {W+'del',W+'moveFrom',W+'pPr',W+'rPr'}:continue
            if child.tag==W+'r':
                for leaf in child:
                    if leaf.tag==W+'t':groups[-1].append((parent,child,leaf))
                    elif leaf.tag in {W+'tab',W+'br',W+'cr'}:groups.append([])
            else:walk(child)
    walk(paragraph);return groups
def replace_plain_islands(paragraph,before,after):
    validate_controls(before,after)
    if _docx_paragraph_text(paragraph)!=before:raise ValueError('Word原文与快照不匹配')
    parts=re.split(r'[\t\n]',after);groups=islands(paragraph)
    if len(parts)!=len(groups):raise ValueError('Word结构分隔与解析内容不匹配')
    if any(text and not group for group,text in zip(groups,parts)):
        split_control_runs(paragraph)
        for index,(group,text) in enumerate(zip(groups,parts)):
            if text and not group:insert_at_island(paragraph,index,text)
        groups=islands(paragraph)
    for group,target in zip(groups,parts):
        old=''.join(leaf.text or '' for _,_,leaf in group)
        if old==target:continue
        a=0;tail=0
        while a<min(len(old),len(target)) and old[a]==target[a]:a+=1
        while tail<min(len(old)-a,len(target)-a) and old[-1-tail]==target[-1-tail]:tail+=1
        end=len(old)-tail;replacement=target[a:len(target)-tail if tail else len(target)]
        offset=0;inserted=False
        for _,_,leaf in group:
            value=leaf.text or '';stop=offset+len(value)
            if not inserted and offset<=a<=stop:
                leaf.text=value[:a-offset]+replacement+(value[end-offset:] if end<stop else '');inserted=True
            elif offset<end and stop>a:leaf.text=value[:max(0,a-offset)]+value[max(0,end-offset):]
            leaf.set('{http://www.w3.org/XML/1998/namespace}space','preserve');offset=stop
    if _docx_paragraph_text(paragraph)!=after:raise ValueError('Word文字岛修改后校验失败')
def insert_at_island(paragraph,index,text,tracker=None):
    import xml.etree.ElementTree as ET
    controls=[]
    def walk(parent):
        for child in parent:
            if child.tag in {W+'del',W+'moveFrom',W+'pPr',W+'rPr'}:continue
            if child.tag==W+'r':
                if any(c.tag in {W+'tab',W+'br',W+'cr'} for c in child):controls.append((parent,child))
            else:walk(child)
    walk(paragraph)
    if controls:
        parent,anchor=controls[0 if index==0 else index-1];at=list(parent).index(anchor)+(0 if index==0 else 1)
    else:parent=paragraph;anchor=ET.Element(W+'r');at=len(paragraph)
    run=ET.Element(W+'r',dict(anchor.attrib));props=anchor.find(W+'rPr')
    if props is not None:
        props=copy.deepcopy(props)
        for change in props.findall(W+'rPrChange'):props.remove(change)
        run.append(props)
    leaf=ET.SubElement(run,W+'t');leaf.text=text;leaf.set('{http://www.w3.org/XML/1998/namespace}space','preserve')
    parent.insert(at,tracker.wrap('ins',run) if tracker else run)
def split_control_runs(paragraph):
    def walk(parent):
        for run in list(parent):
            if run.tag in {W+'del',W+'moveFrom',W+'pPr',W+'rPr'}:continue
            if run.tag!=W+'r':walk(run);continue
            if not any(c.tag in {W+'tab',W+'br',W+'cr'} for c in run):continue
            pieces=[]
            for child in run:
                if child.tag==W+'rPr':continue
                new=__import__('xml.etree.ElementTree',fromlist=['Element']).Element(W+'r',dict(run.attrib));props=run.find(W+'rPr')
                if props is not None:
                    props=copy.deepcopy(props)
                    if pieces:
                        for change in props.findall(W+'rPrChange'):props.remove(change)
                    new.append(props)
                new.append(copy.deepcopy(child));pieces.append(new)
            index=list(parent).index(run);parent.remove(run)
            for new in pieces:parent.insert(index,new);index+=1
    walk(paragraph)
