# -*- coding: utf-8 -*-
"""search_law.py — 法律知识库检索（主题 / 条号 / 关键词）。

不把三部法律全文塞进模型上下文；只返回命中的条文。

用法：
  # 按主题（返回该主题下所有条号 + 条文）
  python search_law.py --index-dir law_index --topic "格式条款" "违约责任"

  # 按条号（精确取条文，用于校验/引用）
  python search_law.py --index-dir law_index --article "民法典:第四百九十六条" "劳动合同法:第十七条"

  # 按关键词（在指定法律或全部法律中全文检索）
  python search_law.py --index-dir law_index --keyword "违约金" --law minfadian

  # 列出所有主题
  python search_law.py --index-dir law_index --list-topics

输出 JSON 到 stdout，每条命中含 law_id / law_name / version / article_no / chapter / text。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import force_utf8_stdio, read_json

force_utf8_stdio()


def load_indexes(index_dir: Path) -> dict:
    idx = {}
    for p in sorted(Path(index_dir).glob("*.json")):
        rec = read_json(p)
        idx[rec["law_id"]] = rec
    return idx


def art_record(law, a):
    return {
        "law_id": law["law_id"],
        "law_name": law["law_name"],
        "version": law["version"],
        "effective_date": law.get("effective_date", ""),
        "status": law.get("status", ""),
        "article_no": a["article_no"],
        "chapter": a.get("chapter", ""),
        "text": a["text"],
    }


def resolve_index_dir(p: str) -> Path:
    """相对 CWD 找不到时，回落到 skill 根目录下的 law_index。"""
    cand = Path(p)
    if cand.exists():
        return cand
    fallback = Path(__file__).resolve().parent.parent / p
    if fallback.exists():
        return fallback
    fallback2 = Path(__file__).resolve().parent.parent / "law_index"
    if fallback2.exists():
        return fallback2
    return cand


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index-dir", required=True)
    ap.add_argument("--topic", nargs="*", default=[])
    ap.add_argument("--article", nargs="*", default=[], help="格式 law_id:条号，如 minfadian:第四百九十六条")
    ap.add_argument("--keyword", nargs="*", default=[])
    ap.add_argument("--law", nargs="*", default=[], help="限定 law_id；为空表示全部")
    ap.add_argument("--list-topics", action="store_true")
    ap.add_argument("--max-per-topic", type=int, default=60)
    args = ap.parse_args()

    indexes = load_indexes(resolve_index_dir(args.index_dir))
    if not indexes:
        print(json.dumps({"error": f"知识库目录无 JSON: {args.index_dir}"}, ensure_ascii=False))
        sys.exit(1)

    if args.list_topics:
        out = {}
        for lid, law in indexes.items():
            out[lid] = {
                "law_name": law["law_name"],
                "version": law["version"],
                "article_count": law["article_count"],
                "topics": {t: len(v) for t, v in law.get("topic_index", {}).items()},
            }
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return

    target_laws = args.law or list(indexes.keys())
    results = {"requested": {"topic": args.topic, "article": args.article,
                             "keyword": args.keyword, "law": target_laws},
               "hits": [], "not_found": []}
    seen = set()

    def add(rec):
        key = (rec["law_id"], rec["article_no"])
        if key not in seen:
            seen.add(key)
            results["hits"].append(rec)

    # 主题检索
    for topic in args.topic:
        for lid in target_laws:
            law = indexes.get(lid)
            if not law:
                continue
            nos = law.get("topic_index", {}).get(topic, [])
            if not nos:
                continue
            by_no = {a["article_no"]: a for a in law["articles"]}
            for no in nos[:args.max_per_topic]:
                if no in by_no:
                    add(art_record(law, by_no[no]))

    # 条号检索（精确）
    for spec in args.article:
        if ":" not in spec:
            results["not_found"].append({"spec": spec, "reason": "格式应为 law_id:条号"})
            continue
        lid, no = spec.split(":", 1)
        law = indexes.get(lid.strip())
        if not law:
            results["not_found"].append({"spec": spec, "reason": f"未知 law_id: {lid}"})
            continue
        by_no = {a["article_no"]: a for a in law["articles"]}
        a = by_no.get(no.strip())
        if a:
            add(art_record(law, a))
        else:
            results["not_found"].append({"spec": spec, "reason": "该法律中不存在此条号"})

    # 关键词检索
    for kw in args.keyword:
        for lid in target_laws:
            law = indexes.get(lid)
            if not law:
                continue
            for a in law["articles"]:
                if kw in a["text"]:
                    add(art_record(law, a))

    results["hit_count"] = len(results["hits"])
    print(json.dumps(results, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
