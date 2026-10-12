"""Tracked text editing invariants, synthetic data only."""
import copy,sys,unittest,xml.etree.ElementTree as ET
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from extract_contract import W,_docx_paragraph_text,paragraph_features
from docx_tracked import Tracker,replace_tracked

def xml(text):return ET.fromstring('<w:p xmlns:w="'+W[1:-1]+'">'+text+'</w:p>')
def reject_new(root,ids):
    for parent in list(root.iter()):
        for child in list(parent):
            if child.get(W+'id') not in ids:continue
            index=list(parent).index(child)
            if child.tag==W+'ins':parent.remove(child)
            elif child.tag==W+'del':
                parent.remove(child)
                for node in child.iter(W+'delText'):node.tag=W+'t'
                for node in child:parent.insert(index,node);index+=1
    return root

class Tracked(unittest.TestCase):
    def assert_edit(self,p,after):
        before=_docx_paragraph_text(p);original=copy.deepcopy(p)
        old={n.get(W+'id'):(n.tag,dict(n.attrib)) for n in p.iter() if n.tag in {W+'ins',W+'del'}}
        old_deletions={n.get(W+'id'):ET.tostring(n) for n in p.iter(W+'del')}
        tracker=Tracker(p,'Synthetic Test');replace_tracked(p,before,after,tracker)
        self.assertEqual(_docx_paragraph_text(p),after)
        for n in p.iter():
            if n.get(W+'id') in old:self.assertEqual((n.tag,dict(n.attrib)),old[n.get(W+'id')])
            if n.get(W+'id') in old_deletions:self.assertEqual(ET.tostring(n),old_deletions[n.get(W+'id')])
        self.assertEqual(len(tracker.ids),len(set(tracker.ids)))
        self.assertFalse(set(tracker.ids)&set(old))
        restored=reject_new(copy.deepcopy(p),set(tracker.ids))
        self.assertEqual(_docx_paragraph_text(restored),before)
        # Original deletion history and comment anchors remain intact.
        self.assertEqual([ET.tostring(n) for n in restored.iter(W+'del')],[ET.tostring(n) for n in original.iter(W+'del')])
        for kind in ['commentRangeStart','commentRangeEnd','commentReference','bookmarkStart','bookmarkEnd']:
            self.assertEqual([dict(n.attrib) for n in p.iter(W+kind)],[dict(n.attrib) for n in original.iter(W+kind)])
        return p
    def test_replace_existing_insertion_and_preserve_deleted_history(self):
        p=xml('<w:r><w:t>付款</w:t></w:r><w:del w:id="1" w:author="Old"><w:r><w:delText>10</w:delText></w:r></w:del><w:ins w:id="2" w:author="New"><w:r><w:rPr><w:b/></w:rPr><w:t>7</w:t></w:r></w:ins><w:r><w:t>天</w:t></w:r>')
        self.assertTrue(paragraph_features(p)['editable']);self.assert_edit(p,'付款5天')
    def test_cross_runs_and_comments(self):
        p=xml('<w:commentRangeStart w:id="1"/><w:r><w:t>甲方付款</w:t></w:r><w:ins w:id="2"><w:r><w:t>7天</w:t></w:r><w:r><w:t>内</w:t></w:r></w:ins><w:commentRangeEnd w:id="1"/><w:r><w:commentReference w:id="1"/></w:r><w:r><w:t>完成。</w:t></w:r>')
        self.assert_edit(p,'甲方付款【期限】完成。')
    def test_insert_delete_whole_empty_unicode_and_multiple_texts(self):
        for before,after in [('abc','Xabc'),('abc','abcX'),('abc','aXbc'),('abc',''),('','🧾'),('🧾付款7天','🧾付款5天'),('abc','xyz')]:
            p=xml('<w:ins w:id="9"><w:r><w:t>'+before[:1]+'</w:t><w:t>'+before[1:]+'</w:t></w:r></w:ins>')
            self.assert_edit(p,after)
    def test_nested_deletion_t_is_never_current_text(self):
        p=xml('<w:ins w:id="1"><w:r><w:t>7</w:t></w:r><w:del w:id="2"><w:r><w:t>10</w:t></w:r></w:del></w:ins>')
        self.assertEqual(_docx_paragraph_text(p),'7');self.assert_edit(p,'5')
    def test_second_edit_reopens_tracked_output(self):
        p=self.assert_edit(xml('<w:ins w:id="3"><w:r><w:t>7天</w:t></w:r></w:ins>'),'5天')
        self.assert_edit(p,'3天')
    def test_format_history_is_retained_once_when_run_is_split(self):
        p=xml('<w:r><w:rPr><w:b/><w:rPrChange w:id="10" w:author="Old format"><w:rPr><w:i/></w:rPr></w:rPrChange></w:rPr><w:t>abc</w:t></w:r>')
        original=ET.tostring(next(p.iter(W+'rPrChange')))
        self.assert_edit(p,'aXc')
        changes=list(p.iter(W+'rPrChange'))
        self.assertEqual(len(changes),1);self.assertEqual(ET.tostring(changes[0]),original)
    def test_complex_structures_stay_guarded_with_specific_reason(self):
        for data,label in [('<w:r><w:fldChar/></w:r>','Word字段'),('<w:r><w:drawing/></w:r>','图片'),('<w:pPr><w:rPr><w:del w:id="1"/></w:rPr></w:pPr><w:r><w:t>合并</w:t></w:r>','段落合并')]:
            p=xml(data);features=paragraph_features(p)
            self.assertFalse(features['editable']);self.assertIn(label,features['read_only_reason'])
            with self.assertRaises(ValueError):replace_tracked(p,_docx_paragraph_text(p),'new',Tracker(p))

if __name__=='__main__':unittest.main(verbosity=2)
