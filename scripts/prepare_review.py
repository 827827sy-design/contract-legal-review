"""Build context for WorkBuddy; perspective changes still require actual agent analysis."""
from __future__ import annotations
import argparse
import copy
import json
import re
from pathlib import Path
from common import force_utf8_stdio, now_iso, read_json, write_json
from preferences import load, active_for, config_path

PERSPECTIVES = {'neutral','party_a','party_b','custom'}

def party_candidates(contract):
    candidates = {'party_a': [], 'party_b': []}
    for block in contract['blocks']:
        for label,key in [('甲方','party_a'),('乙方','party_b')]:
            match = re.search(label + r'\s*[（(][^）)]*[）)]\s*[:：]\s*([^\n；;]+)|' + label + r'\s*[:：]\s*([^\n；;]+)',block['text'])
            if match:
                candidates[key].append({'name': (match.group(1) or match.group(2)).strip(), 'block_id':block['block_id'], 'quote':match.group(0)})
    return candidates

def main():
    force_utf8_stdio()
    ap = argparse.ArgumentParser()
    ap.add_argument('--task-dir', required=True)
    ap.add_argument('--contract-type', default='通用合同')
    ap.add_argument('--perspective', choices=sorted(PERSPECTIVES), default='neutral')
    ap.add_argument('--focus', default='')
    ap.add_argument('--party-a', default='')
    ap.add_argument('--party-b', default='')
    ap.add_argument('--confirm-parties', action='store_true')
    ap.add_argument('--config-dir')
    ap.add_argument('--new-run', action='store_true', help='Copy parsed contract and revisions into a new review run without overwriting history')
    args = ap.parse_args()
    task = Path(args.task_dir)
    contract = read_json(task / 'contract.json')
    prefs = load(args.config_dir)
    context = {'schema_version':2,'created_at':now_iso(),'contract_type':args.contract_type,
               'perspective':{'mode':args.perspective,'focus':args.focus,
                              'party_a':args.party_a,'party_b':args.party_b,'parties_confirmed':args.confirm_parties},
               'party_candidates':party_candidates(contract),
               'preferences':active_for(prefs,args.contract_type), 'preferences_configured':prefs['configured'],
               'preferences_path':str(config_path(args.config_dir)),
               'legal_invariant':'法律强制要求独立于立场；企业制度、谈判偏好与经验不构成违法依据。'}
    if args.new_run:
        import uuid
        new = task / 'review_runs' / uuid.uuid4().hex[:12]
        new.mkdir(parents=True)
        for name in ['contract.json','contract.txt','base_contract.json','revisions.json']:
            if (task/name).exists():
                (new/name).write_bytes((task/name).read_bytes())
        if (task/'review_result.json').exists():
            (new/'prior_review.json').write_bytes((task/'review_result.json').read_bytes())
        task = new
    write_json(task/'review_context.json',context)
    print(json.dumps({'task_dir':str(task),'context_file':str(task/'review_context.json'),
                      'requires_ai_analysis':True,'perspective':context['perspective'],
                      'preferences_configured':prefs['configured']},ensure_ascii=False))

if __name__=='__main__':
    main()
