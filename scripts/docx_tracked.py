"""Append text revisions without accepting/rejecting an existing Word revision.

Plain runs are split in their existing container. Existing ins/del metadata,
deleted history, comments and bookmarks stay in place. Rejecting only the IDs
created here restores the prior visible text; current visible text is checked.
"""
from __future__ import annotations
import copy
from datetime import datetime,timezone
from extract_contract import W,_docx_paragraph_text,paragraph_features
import xml.etree.ElementTree as ET

SPACE='{http://www.w3.org/XML/1998/namespace}space'

class Tracker:
    def __init__(self,root,author='Contract Review'):
        ids=[int(n.get(W+'id')) for n in root.iter() if (n.get(W+'id') or '').isdigit()]
        self.next_id=max(ids,default=-1)+1
        self.author=author
        self.date=datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')
        self.ids=[]
    def wrap(self,kind,run):
        element=ET.Element(W+kind,{W+'id':str(self.next_id),W+'author':self.author,W+'date':self.date})
        self.ids.append(str(self.next_id));self.next_id+=1;element.append(run)
        return element

def text_run(template,text,deleted=False,keep_format_history=False):
    run=ET.Element(W+'r',dict(template.attrib))
    props=template.find(W+'rPr')
    if props is not None:
        props=copy.deepcopy(props)
        if not keep_format_history:
            for change in list(props.findall(W+'rPrChange')):props.remove(change)
        run.append(props)
    t=ET.SubElement(run,W+('delText' if deleted else 't'));t.text=text;t.set(SPACE,'preserve')
    return run

def visible_runs(paragraph):
    result=[]
    def walk(parent):
        for child in parent:
            if child.tag in {W+'del',W+'moveFrom',W+'pPr',W+'rPr'}:continue
            if child.tag==W+'r':
                value=''.join(t.text or '' for t in child.findall(W+'t'))
                if value:result.append((parent,child,value))
                elif any(c.tag in {W+'tab',W+'br',W+'cr'} for c in child):result.append((parent,child,'\t' if child.find(W+'tab') is not None else '\n'))
            else:walk(child)
    walk(paragraph)
    return result

def replace_tracked(paragraph,before,after,tracker):
    if not paragraph_features(paragraph)['editable']:
        raise ValueError('Word段落结构仍不支持安全修订：'+paragraph_features(paragraph)['read_only_reason'])
    if _docx_paragraph_text(paragraph)!=before:raise ValueError('Word修订段落与解析快照不匹配。')
    if any(c in before or c in after for c in ['\n','\t']):
        import re
        from docx_controls import validate_controls,split_control_runs,insert_at_island
        validate_controls(before,after);split_control_runs(paragraph)
        old_parts=re.split('([\t\n])',before);new_parts=re.split('([\t\n])',after);offset=0
        for index,(old,new) in enumerate(zip(old_parts,new_parts)):
            if old!=new:
                value=_docx_paragraph_text(paragraph)
                if not old:insert_at_island(paragraph,index//2,new,tracker)
                else:_replace_range(paragraph,offset,offset+len(old),new,tracker)
                if _docx_paragraph_text(paragraph)!=value[:offset]+new+value[offset+len(old):]:raise ValueError('Word文字片段修订校验失败')
            offset+=len(new)
        if _docx_paragraph_text(paragraph)!=after:raise ValueError('Word结构文字修订校验失败')
        return
    if before==after:return
    start=0
    while start<min(len(before),len(after)) and before[start]==after[start]:start+=1
    tail=0
    while tail<min(len(before)-start,len(after)-start) and before[-1-tail]==after[-1-tail]:tail+=1
    end=len(before)-tail
    replacement=after[start:len(after)-tail if tail else len(after)]
    _replace_range(paragraph,start,end,replacement,tracker)
    if _docx_paragraph_text(paragraph)!=after:raise ValueError('Word原生修订的当前文字校验失败。')

def _replace_range(paragraph,start,end,replacement,tracker):
    runs=visible_runs(paragraph);offset=0;inserted=False
    for parent,run,value in runs:
        stop=offset+len(value)
        control=any(c.tag in {W+'tab',W+'br',W+'cr'} for c in run)
        insert_here=not inserted and not control and offset<=start<=stop
        lo=max(start,offset);hi=min(end,stop)
        if not control and (hi>lo or insert_here):
            left=max(0,min(len(value),start-offset));right=max(left,min(len(value),end-offset))
            pieces=[]
            original_pieces=[]
            if value[:left]:
                left_run=text_run(run,value[:left],keep_format_history=True);pieces.append(left_run);original_pieces.append(left_run)
            if value[left:right]:
                deleted_run=text_run(run,value[left:right],True,not original_pieces);pieces.append(tracker.wrap('del',deleted_run));original_pieces.append(deleted_run)
            if insert_here:
                if replacement:pieces.append(tracker.wrap('ins',text_run(run,replacement)))
                inserted=True
            if value[right:]:pieces.append(text_run(run,value[right:],keep_format_history=not original_pieces))
            index=list(parent).index(run);parent.remove(run)
            for piece in pieces:parent.insert(index,piece);index+=1
        offset=stop
    if not inserted:
        if _docx_paragraph_text(paragraph):raise ValueError('未找到Word修订插入位置。')
        if replacement:paragraph.append(tracker.wrap('ins',text_run(ET.Element(W+'r'),replacement)))
