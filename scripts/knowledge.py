"""Versioned local legal resources, separate from preferences and execution."""
import json,hashlib,datetime
from pathlib import Path
from common import read_json
CORE_COUNTS={'minfadian':1260,'laodonghetongfa':98,'gongsifa':266}
def content_digest(articles):return hashlib.sha256(json.dumps(articles,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def load_records(index_dir):
    directory=Path(index_dir);result={}
    paths=list(sorted(directory.glob('*.json')))+list(sorted((directory/'extensions').glob('*.json')))
    for path in paths:
        rec=read_json(path)
        if not isinstance(rec,dict) or not rec.get('law_id') or not isinstance(rec.get('articles'),list):raise ValueError('法律资源格式不完整：'+str(path))
        id=rec['law_id']
        if id in result:raise ValueError('法律版本ID重复，扩展不能悄然覆盖现有版本：'+id)
        core=path.parent==directory and id in CORE_COUNTS
        expected=CORE_COUNTS.get(id) if core else rec.get('article_count')
        unique=len({a.get('article_no') for a in rec['articles']})==len(rec['articles'])
        complete=bool(expected) and rec.get('article_count')==expected==len(rec['articles']) and unique and {a.get('no') for a in rec['articles']}==set(range(1,expected+1))
        verification=rec.get('verification',{})
        verified=core or bool(verification.get('status')=='verified' and verification.get('verified_at') and rec.get('source_url') and verification.get('content_sha256')==content_digest(rec['articles']))
        rec['_resource_verified']=verified;rec['_complete']=complete and verified;rec['_path']=str(path);result[id]=rec
    return result
def temporal_status(record,date):
    if not date:return {'status':'unconfirmed','reason':'订立/履约时间或适用规则尚未确认；旧法引用不能直接认定错误。'}
    try:
        value=datetime.date.fromisoformat(date);start=record.get('effective_from',record.get('effective_date'));end=record.get('effective_to')
        if not start:return {'status':'unconfirmed','reason':'资源缺少施行日期'}
        inside=value>=datetime.date.fromisoformat(start) and (not end or value<=datetime.date.fromisoformat(end))
        return {'status':'within_period' if inside else 'requires_transition_review','reason':'日期落在资源标注期间内，仍需确认具体适用规则。' if inside else '日期跨越资源标注期间，需核验过渡和适用规则，不能自动认定违法。'}
    except ValueError:return {'status':'unconfirmed','reason':'日期格式或资源期间待核实。'}
def context(index_dir,contract_type,date=None):
    resources=load_records(index_dir)
    return {'contract_type':contract_type,'resources':[{'law_id':id,'version':r.get('version'),'verified':r['_resource_verified'],'complete':r['_complete'],'temporal':temporal_status(r,date)} for id,r in resources.items()],
     'extension_directory':str(Path(index_dir)/'extensions'),'scope':'只可引用已核验、完整的本地法律资源；未收录的专业法律和历史适用问题须待核验。企业偏好不属于法律资源。'}
