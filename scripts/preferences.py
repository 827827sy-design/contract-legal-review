"""WorkBuddy review preferences. Writes require explicit user confirmation."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
from common import force_utf8_stdio, now_iso

KINDS = {'law_requirement', 'company_policy', 'negotiation', 'experience'}

def config_path(directory=None):
    root = directory or os.environ.get('WORKBUDDY_REVIEW_CONFIG_DIR')
    return (Path(root).expanduser() if root else Path.home() / '.workbuddy' / 'user_data' / 'contract-legal-review') / 'preferences.json'

def load(directory=None):
    path = config_path(directory)
    if not path.exists():
        return {'schema_version': 2, 'configured': False, 'preferences': [], 'history': []}
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('schema_version') != 2 or not isinstance(data.get('preferences'), list):
        raise ValueError('偏好配置格式不正确，请先恢复备份。')
    ids = set()
    for item in data['preferences']:
        if not isinstance(item, dict) or item.get('kind') not in KINDS or not isinstance(item.get('rule'), str):
            raise ValueError('偏好记录缺少来源类型或规则。')
        if not item.get('id') or item['id'] in ids:
            raise ValueError('偏好编号缺失或重复。')
        ids.add(item['id'])
    return data

def save(data, directory=None):
    path = config_path(directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive temporary file, atomic replace; never claim success before replace.
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False, suffix='.tmp') as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)
        temporary = Path(fp.name)
    try:
        if path.exists():
            (path.with_suffix('.json.bak')).write_bytes(path.read_bytes())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path

def active_for(data, contract_type):
    return [p for p in data['preferences'] if p.get('enabled', True) and
            (not p.get('contract_types') or contract_type in p['contract_types'])]

def main():
    force_utf8_stdio()
    ap = argparse.ArgumentParser()
    ap.add_argument('action', choices=['status','list','init','upsert','disable','enable','delete','context'])
    ap.add_argument('--config-dir')
    ap.add_argument('--input', help='JSON object with id,kind,rule,contract_types,basis (local references)')
    ap.add_argument('--id')
    ap.add_argument('--contract-type', default='通用合同')
    ap.add_argument('--confirmed', action='store_true', help='Only after the human confirms these changes')
    ap.add_argument('--skip', action='store_true')
    args = ap.parse_args()
    data = load(args.config_dir)
    if args.action in {'status','list','context'}:
        print(json.dumps({'path': str(config_path(args.config_dir)), 'configured': data['configured'],
                          'first_use_question': '' if data['configured'] else '是否有需要长期遵循的合同审查偏好、企业制度或历史审查经验？如有，可以提供具体规则及相关依据；如没有，则使用默认中立审查标准。',
                          'preferences': active_for(data, args.contract_type) if args.action == 'context' else data['preferences']}, ensure_ascii=False, indent=2))
        return
    if not args.confirmed:
        ap.error('持久化写入需要用户确认；确认后传入 --confirmed。')
    before = json.loads(json.dumps(data['preferences']))
    if args.action == 'upsert':
        if not args.input:
            ap.error('upsert requires --input')
        item = json.loads(Path(args.input).read_text(encoding='utf-8'))
        if item.get('kind') not in KINDS or not item.get('id') or not item.get('rule', '').strip():
            ap.error('偏好必须包含 id、kind 和非空 rule。')
        if not isinstance(item.get('contract_types', []), list) or not isinstance(item.get('basis', []), list):
            ap.error('contract_types 与 basis 必须是数组。')
        item['enabled'] = item.get('enabled', True)
        item['updated_at'] = now_iso()
        data['preferences'] = [p for p in data['preferences'] if p['id'] != item['id']] + [item]
    elif args.action in {'delete','enable','disable'}:
        matches = [p for p in data['preferences'] if p['id'] == args.id]
        if not matches:
            ap.error('偏好编号不存在。')
        if args.action == 'delete':
            data['preferences'] = [p for p in data['preferences'] if p['id'] != args.id]
        else:
            matches[0]['enabled'] = args.action == 'enable'
    elif args.action == 'init' and not args.skip:
        ap.error('无偏好时使用 init --skip；已有规则请使用 upsert。')
    data['configured'] = True
    data['history'].append({'time': now_iso(), 'action': args.action, 'id': args.id, 'before': before, 'after': data['preferences']})
    print(json.dumps({'saved': True, 'path': str(save(data, args.config_dir))}, ensure_ascii=False))

if __name__ == '__main__':
    main()
