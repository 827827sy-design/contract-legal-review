# -*- coding: utf-8 -*-
"""extract_contract.py — 合同解析：DOCX / PDF / TXT / MD / DOC -> contract.json

输出结构：
{
  "source_file": "...", "file_sha256": "...", "file_type": "docx",
  "parse_status": "ok" | "partial" | "failed",
  "parse_notes": [...],
  "title_guess": "...",
  "blocks": [ {"block_id": "b0001", "kind": "para|heading|table|...", "text": "..."} ],
  "full_text": "...", "block_offsets": {"b0001": [start, end]}
}

设计原则：
- 优先标准库；DOCX 用 zipfile+xml.etree 解析（DOCX 即 OOXML zip）。
- PDF 需要 pypdf（第三方，装在隔离 venv）；缺失时降级为 failed 并给出提示。
- DOC（老式二进制）无法用标准库可靠解析：尝试检测并提示转换，不猜测。
- 每个段落分配稳定 block_id；表格按行拼接为文本块（保留单元格分隔）。
- 无法可靠提取文字时 parse_status 置为 partial/failed，不伪造内容。
"""
from __future__ import annotations

import argparse
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (force_utf8_stdio, build_full_text, file_sha256, now_iso,
                    write_json, merge_log, norm_ws)

force_utf8_stdio()

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

def editable_paragraph(element):
    unsupported = {'drawing','object','fldChar','instrText','del','ins','tab','br','cr','sdt'}
    return not any(node.tag.split('}')[-1] in unsupported for node in element.iter())


# ---------------------------------------------------------------- DOCX

def _docx_paragraph_text(p_el) -> str:
    texts = []
    for node in p_el.iter():
        tag = node.tag
        if tag == f"{W}t":
            texts.append(node.text or "")
        elif tag == f"{W}tab":
            texts.append("\t")
        elif tag in (f"{W}br", f"{W}cr"):
            texts.append("\n")
    return "".join(texts)


def _para_style(p_el) -> str:
    pPr = p_el.find(f"{W}pPr")
    if pPr is not None:
        st = pPr.find(f"{W}pStyle")
        if st is not None:
            return st.get(f"{W}val", "") or ""
    return ""


def extract_docx(path: Path):
    blocks, notes = [], []
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if "word/document.xml" not in names:
            raise ValueError("DOCX 缺少 word/document.xml")
        xml_bytes = z.read("word/document.xml")
    root = ET.fromstring(xml_bytes)
    body = root.find(f"{W}body")
    if body is None:
        raise ValueError("DOCX 无 body")

    def walk(container):
        for body_index, el in enumerate(container):
            if el.tag == f"{W}p":
                txt = _docx_paragraph_text(el)
                style = _para_style(el)
                kind = "heading" if (style.lower().startswith("heading")
                                     or style.startswith("标题")
                                     or style in ("Title", "Subtitle")) else "para"
                blocks.append({"kind": kind, "text": txt, "style": style,
                               "editable": editable_paragraph(el),
                               "locator": {"body_index":body_index,"kind":"paragraph"}})
            elif el.tag == f"{W}tbl":
                rows_txt, structured = [], []
                for row_index, tr in enumerate(el.findall(f"{W}tr")):
                    cells, structured_row = [], []
                    for col_index, tc in enumerate(tr.findall(f"{W}tc")):
                        cell = " ".join(
                            _docx_paragraph_text(p)
                            for p in tc.findall(f"{W}p")
                        ).strip()
                        cells.append(cell)
                        paragraphs = tc.findall(f"{W}p")
                        safe = (len(paragraphs)==1 and editable_paragraph(paragraphs[0]) and
                                _docx_paragraph_text(paragraphs[0])==cell and
                                not tc.findall(f'.//{W}gridSpan') and not tc.findall(f'.//{W}vMerge') and
                                not tc.findall(f'.//{W}tbl'))
                        structured_row.append({'text':cell,'editable':safe,
                                               'locator':{'body_index':body_index,'row':row_index,'col':col_index,'kind':'cell'}})
                    rows_txt.append(" | ".join(cells))
                    structured.append(structured_row)
                blocks.append({"kind": "table", "text": "\n".join(rows_txt), "cells":structured})

    walk(body)
    return blocks, notes


# ---------------------------------------------------------------- TXT / MD

def extract_text(path: Path):
    raw = path.read_bytes()
    text = None
    for enc in ("utf-8-sig", "utf-8", "gb18030", "big5"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("utf-8", errors="replace")
    blocks = []
    for line in text.splitlines():
        s = line.rstrip()
        if not s.strip():
            continue
        kind = "para"
        m = re.match(r"^\s*(#{1,6})\s+", s)
        if m:
            kind = "heading"
            s = re.sub(r"^\s*#{1,6}\s+", "", s)
        blocks.append({"kind": kind, "text": s})
    return blocks, []


# ---------------------------------------------------------------- PDF

def extract_pdf(path: Path):
    try:
        from pypdf import PdfReader
    except ImportError:
        raise RuntimeError("PDF 解析需要 pypdf；请在隔离环境安装：pip install pypdf")
    reader = PdfReader(str(path))
    blocks, notes = [], []
    empty_pages = 0
    for i, page in enumerate(reader.pages):
        try:
            txt = page.extract_text() or ""
        except Exception as e:
            notes.append(f"第{i+1}页文本提取异常: {e}")
            empty_pages += 1
            continue
        if not txt.strip():
            empty_pages += 1
            notes.append(f"第{i+1}页无可提取文本（可能是扫描图片页，需 OCR 或人工检查）")
            continue
        for line in txt.splitlines():
            s = line.strip()
            if s:
                blocks.append({"kind": "para", "text": s, "page": i + 1})
    if empty_pages and empty_pages >= len(reader.pages):
        raise RuntimeError("PDF 所有页面均无可提取文本（疑似扫描件），需 OCR 或人工检查")
    if empty_pages:
        notes.append(f"共 {len(reader.pages)} 页，其中 {empty_pages} 页无文本")
    return blocks, notes


# ---------------------------------------------------------------- DOC (legacy)

def extract_doc(path: Path):
    raw = path.read_bytes()[:8]
    if raw[:4] == b"PK\x03\x04":
        return extract_docx(path)  # 实为 docx 改扩展名
    if raw[:5] == b"%PDF-":
        return extract_pdf(path)
    raise RuntimeError(
        "旧式 .doc（OLE2 二进制）无法用标准库可靠解析。请先另存为 .docx 或 .pdf 后重试；"
        "不要用文本方式强行读取，以免得到乱码。"
    )


# ---------------------------------------------------------------- 主流程

EXTRACTORS = {
    ".docx": extract_docx,
    ".txt": extract_text,
    ".md": extract_text,
    ".pdf": extract_pdf,
    ".doc": extract_doc,
}


def guess_title(blocks):
    for b in blocks[:15]:
        t = b["text"].strip()
        if not t:
            continue
        if b.get("kind") == "heading" and 2 <= len(t) <= 60:
            return t
        if ("合同" in t or "协议" in t or "约定书" in t) and 2 <= len(t) <= 60:
            return t
    for b in blocks[:5]:
        t = b["text"].strip()
        if 2 <= len(t) <= 60:
            return t
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="合同文件路径")
    ap.add_argument("--task-dir", required=True, help="任务输出目录")
    args = ap.parse_args()

    src = Path(args.input)
    task_dir = Path(args.task_dir)
    task_dir.mkdir(parents=True, exist_ok=True)

    if not src.exists():
        print(f"[FAIL] 输入文件不存在: {src}")
        sys.exit(2)

    ext = src.suffix.lower()
    status, notes = "ok", []
    blocks = []
    if ext not in EXTRACTORS:
        status = "failed"
        notes.append(f"不支持的文件类型 {ext}（支持 .docx/.doc/.pdf/.txt/.md）")
    else:
        try:
            blocks, notes = EXTRACTORS[ext](src)
        except Exception as e:
            status = "failed"
            notes.append(f"解析失败: {e}")

    # 清洗：去掉全空块，分配稳定 block_id
    cleaned = []
    for i, b in enumerate(blocks):
        txt = b.get("text", "")
        if txt is None:
            continue
        if not txt.strip() and b.get("kind") != "table":
            continue
        cleaned.append({
            "block_id": f"b{i+1:04d}",
            "kind": b.get("kind", "para"),
            "text": txt,
            **({"style": b["style"]} if b.get("style") else {}),
            **({"page": b["page"]} if b.get("page") else {}),
            **{k:b[k] for k in ('cells','locator','editable') if k in b},
        })
    blocks = cleaned

    if status == "ok" and not blocks:
        status = "failed"
        notes.append("未提取到任何文本块")
    elif status == "ok" and any("无可提取文本" in n or "无文本" in n or "异常" in n for n in notes):
        status = "partial"

    full_text, offsets = build_full_text(blocks)
    contract = {
        "source_file": str(src.resolve()),
        "source_name": src.name,
        "file_type": ext.lstrip(".") or "unknown",
        "file_sha256": file_sha256(src) if src.exists() else "",
        "parse_status": status,
        "parse_notes": notes,
        "title_guess": guess_title(blocks) if blocks else "",
        "block_count": len(blocks),
        "char_count": len(full_text),
        "extracted_at": now_iso(),
        "blocks": blocks,
        "full_text": full_text,
        "block_offsets": offsets,
    }
    from revision_core import nodes_for
    contract['schema_version'] = 2
    contract['nodes'] = nodes_for(contract)
    write_json(task_dir / "contract.json", contract)

    # 同时输出纯文本，方便模型阅读（不进入 HTML 渲染管线）
    (task_dir / "contract.txt").write_text(full_text, encoding="utf-8")

    summary = {
        "source_name": src.name,
        "file_type": contract["file_type"],
        "parse_status": status,
        "block_count": len(blocks),
        "char_count": len(full_text),
        "title_guess": contract["title_guess"],
        "notes": notes,
    }
    merge_log(task_dir, "extract_contract", summary)
    print(f"[{status.upper()}] {src.name}: {len(blocks)} 块, {len(full_text)} 字符"
          + (f"; 标题猜测: {contract['title_guess']}" if contract['title_guess'] else ""))
    for n in notes:
        print(f"  - {n}")
    if status == "failed":
        sys.exit(1)


if __name__ == "__main__":
    main()
