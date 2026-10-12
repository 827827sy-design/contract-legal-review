"""Validate, materialize and prepare re-review without touching the input contract."""
from __future__ import annotations
import argparse
import json
import uuid
from pathlib import Path
from common import force_utf8_stdio, read_json, write_json
from revision_core import document_for, replay, contract_from_nodes

def main():
    force_utf8_stdio()
    ap=argparse.ArgumentParser()
    ap.add_argument('action',choices=['validate','materialize','compare'])
    ap.add_argument('--task-dir',required=True)
    ap.add_argument('--revisions')
    ap.add_argument('--out-dir')
    ap.add_argument('--prior-review')
    ap.add_argument('--current-review')
    args=ap.parse_args()
    task=Path(args.task_dir)
    if args.action=='compare':
        old=read_json(Path(args.prior_review)); new=read_json(Path(args.current_review))
        # Do not infer that absence means resolution: WorkBuddy must supply a disposition.
        mapping=new.get('review_meta',{}).get('risk_resolution',[])
        valid={'resolved','remaining','new','needs_confirmation'}
        if any(m.get('status') not in valid for m in mapping):
            raise ValueError('复审分类不合法。')
        prior={r['risk_id'] for r in old['risks']}
        present={r['risk_id'] for r in new['risks']}
        if any(m.get('current_risk_id') and m['current_risk_id'] not in present or m.get('prior_risk_id') and m['prior_risk_id'] not in prior for m in mapping):
            raise ValueError('复审分类引用了不存在的风险编号。')
        output={'dispositions':mapping,'unclassified_prior_risks':sorted(prior-{m.get('prior_risk_id') for m in mapping}),
                'note':'未分类或缺席不能自动认定已解决；须由 WorkBuddy 基于新合同语义审查。'}
        write_json(task/'risk_comparison.json',output)
        print(json.dumps(output,ensure_ascii=False)); return
    original=read_json(task/('base_contract.json' if (task/'base_contract.json').exists() else 'contract.json'))
    revision=read_json(Path(args.revisions))
    nodes=replay(document_for(original),revision)
    if args.action=='validate':
        print(json.dumps({'valid':True,'operations':len(revision['operations']),
                          'changed_nodes':sum(n['changed'] for n in nodes),
                          'pending':sum(o['status']=='active' and o['decision']=='pending' for o in revision['operations'])},ensure_ascii=False)); return
    out=Path(args.out_dir) if args.out_dir else task/'review_runs'/uuid.uuid4().hex[:12]
    if out.resolve()==task.resolve() or out.exists() and any(out.iterdir()):
        raise ValueError('复审必须使用新的空任务目录，不能覆盖已有记录。')
    current=contract_from_nodes(original,nodes)
    write_json(out/'contract.json',current)
    write_json(out/'base_contract.json',original)
    write_json(out/'revisions.json',revision)
    (out/'contract.txt').write_text(current['full_text'],encoding='utf-8')
    if (task/'review_result.json').exists():
        write_json(out/'prior_review.json',read_json(task/'review_result.json'))
    print(json.dumps({'task_dir':str(out),'requires_ai_analysis':True,
                      'original_preserved':True,'revision_history_preserved':True},ensure_ascii=False))

if __name__=='__main__':
    main()
