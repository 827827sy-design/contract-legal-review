# -*- coding: utf-8 -*-
"""common.py — contract-legal-review 共享工具（仅标准库）。

提供：中文数字转换、文本规范化、原文定位（quote -> full_text span）、
JSON/日志读写、文件哈希、任务目录管理。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------- 编码与输出

def force_utf8_stdio() -> None:
    """Windows 控制台默认 GBK，强制 UTF-8 避免中文输出乱码。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


# ---------------------------------------------------------------- 中文数字

CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
            "六": 6, "七": 7, "八": 8, "九": 9, "两": 2}
CN_UNIT = {"十": 10, "百": 100, "千": 1000}


def cn2int(s: str) -> int:
    """中文数字转整数（1-9999）。失败抛 ValueError。"""
    s = s.strip()
    if s.isdigit():
        return int(s)
    total, num = 0, 0
    for ch in s:
        if ch in CN_DIGIT:
            num = CN_DIGIT[ch]
        elif ch in CN_UNIT:
            unit = CN_UNIT[ch]
            if num == 0:
                num = 1
            total += num * unit
            num = 0
        else:
            raise ValueError(f"非法中文数字字符 {ch!r} in {s!r}")
    if total == 0 and num == 0:
        raise ValueError(f"空数字 {s!r}")
    return total + num


ART_NO_RE = re.compile(r"第[一二三四五六七八九十百千零〇0-9]+条")


# ---------------------------------------------------------------- 文本规范化

# 标点等价表：部分政府网站使用半角替代字符（｢ ｡ ､），比对时统一
_PUNCT_TABLE = str.maketrans({
    "｡": "。", "､": "、", "｣": "」", "｢": "「",
    "\u2002": " ", "\u3000": " ", "\xa0": " ", "\u200b": "",
})

_WS_RE = re.compile(r"\s+")


def norm_ws(s: str) -> str:
    """仅规范化空白（保留标点原样）。"""
    return _WS_RE.sub("", s.translate(_PUNCT_TABLE))


# 法条比对用：进一步统一全/半角与常见标点差异
_FINE_TABLE = str.maketrans({
    "；": ";", "：": ":", "（": "(", "）": ")", "，": ",", "。": ".",
    "“": '"', "”": '"', "‘": "'", "’": "'", "！": "!", "？": "?",
    "、": ",", "《": "<", "》": ">", "—": "-", "－": "-", "～": "~",
})


def norm_law_text(s: str) -> str:
    """法条比对规范化：去空白 + 统一标点。"""
    return norm_ws(s).translate(_FINE_TABLE)


def build_norm_map(text: str):
    """构造 (normalized_string, index_map)。

    index_map[i] = normalized 第 i 个字符在原始 text 中的下标。
    用于把「忽略空白差异」的匹配结果映射回原文精确 span。
    """
    chars, idx = [], []
    for i, ch in enumerate(text):
        if ch.isspace():
            continue
        c = _PUNCT_TABLE.get(ch, ch)
        if c == "":
            continue
        chars.append(c)
        idx.append(i)
    return "".join(chars), idx


def locate_quote(text: str, quote: str, occurrence: int = 1,
                 search_start: int = 0, search_end: int | None = None):
    """在 text 中定位 quote，返回 (start, end, note)；失败返回 (None, None, reason)。

    - 先尝试精确子串匹配（第 occurrence 次出现）。
    - 再尝试忽略空白的规范化匹配，并映射回原文 span（处理换行/空格差异）。
    - search_start/search_end 限定搜索窗口（用于段落锚点约束）。
    """
    if not quote:
        return None, None, "引用原文为空"
    occurrence = max(1, int(occurrence or 1))
    lo = max(0, search_start)
    hi = len(text) if search_end is None else min(len(text), search_end)
    window = text[lo:hi]

    # 1) 精确匹配
    pos, found = -1, 0
    start = 0
    while True:
        p = window.find(quote, start)
        if p < 0:
            break
        found += 1
        if found == occurrence:
            pos = p
            break
        start = p + 1
    if pos >= 0:
        return lo + pos, lo + pos + len(quote), "exact"

    # 2) 规范化匹配（忽略空白）
    nq, _ = build_norm_map(quote)
    if not nq:
        return None, None, "引用原文仅含空白字符"
    ntext, nmap = build_norm_map(window)
    pos, found = -1, 0
    start = 0
    while True:
        p = ntext.find(nq, start)
        if p < 0:
            break
        found += 1
        if found == occurrence:
            pos = p
            break
        start = p + 1
    if pos < 0:
        if found and occurrence > found:
            return None, None, f"occurrence={occurrence} 超出实际出现次数 {found}"
        return None, None, "quote 不是指定位置的原文子串（含忽略空白比对）"
    s = nmap[pos]
    e = nmap[pos + len(nq) - 1] + 1
    return lo + s, lo + e, "normalized"


# ---------------------------------------------------------------- JSON / 日志

def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, obj, indent: int = 1) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=indent), encoding="utf-8")


def now_iso() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")


def merge_log(task_dir: Path, section: str, payload: dict) -> dict:
    """把脚本运行记录合并进 <task_dir>/review_log.json。"""
    log_path = Path(task_dir) / "review_log.json"
    log = read_json(log_path) if log_path.exists() else {
        "task_id": Path(task_dir).name,
        "created_at": now_iso(),
        "stages": [],
    }
    entry = {"stage": section, "time": now_iso(), **payload}
    log["stages"].append(entry)
    log["updated_at"] = now_iso()
    write_json(log_path, log)
    return log


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- 合同数据

def build_full_text(blocks: list[dict]) -> tuple[str, dict]:
    """blocks -> (full_text, {block_id: [start, end)})。block 之间以单个 \n 连接。"""
    parts, offsets, cur = [], {}, 0
    for b in blocks:
        t = b["text"]
        parts.append(t)
        offsets[b["block_id"]] = [cur, cur + len(t)]
        cur += len(t) + 1
    return "\n".join(parts), offsets


def load_contract(task_dir: Path) -> dict:
    c = read_json(Path(task_dir) / "contract.json")
    blocks = c["blocks"]
    full_text, offsets = build_full_text(blocks)
    c["_full_text"] = full_text
    c["_offsets"] = offsets
    c["_block_by_id"] = {b["block_id"]: b for b in blocks}
    return c


# ---------------------------------------------------------------- 枚举

CATEGORIES = ["法律合规风险", "合同效力风险", "条款缺失", "条款约定不明确", "待核实事项"]
SEVERITIES = ["high", "medium", "low", "review_required"]
SEV_ORDER = {"high": 0, "medium": 1, "low": 2, "review_required": 3}
SEV_LABEL = {"high": "高", "medium": "中", "low": "低", "review_required": "待核实"}


def esc(s) -> str:
    """HTML 转义。所有合同原文与模型产出文本进入 HTML 前必须经过此函数。"""
    if s is None:
        return ""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))


def json_for_script(obj) -> str:
    """安全嵌入 <script> 的 JSON：转义 </ 与 U+2028/2029。"""
    s = json.dumps(obj, ensure_ascii=False)
    return (s.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026").replace("\u2028", "\\u2028")
             .replace("\u2029", "\\u2029"))
