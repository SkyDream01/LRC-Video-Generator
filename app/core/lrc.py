"""LRC 歌词解析。

支持标准 `[mm:ss.xx]` / `[mm:ss.xxx]` / `[mm:ss]` 标签（含一行多标签）、
元数据标签（ti/ar/al/offset）、双语配对与 Enhanced LRC 词级标签（`<mm:ss.xx>词`）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_TIME_TAG = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
_WORD_TAG = re.compile(r"<(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?>")
_META_TAG = re.compile(r"^\[(ti|ar|al|by|offset|length|re|ve):(.*)\]$", re.IGNORECASE)

# 双语配对阈值：相邻条目时间差小于该值视为同一行的译文
PAIR_TOLERANCE_S = 0.05


@dataclass
class WordTiming:
    """词级时间（Enhanced LRC）。end 为 None 表示未知（取下一词 start）。"""

    start: float
    end: float | None
    text: str


@dataclass
class LyricLine:
    """单行歌词（可能带译文）。time 为行起始秒；行结束时间由 timeline 计算。"""

    time: float
    text: str
    translation: str | None = None
    words: list[WordTiming] | None = None


@dataclass
class LrcDocument:
    """解析结果：排序后的行列表 + 元数据。"""

    lines: list[LyricLine] = field(default_factory=list)
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    offset: float = 0.0  # [offset:] 毫秒，已折算秒


def _tag_to_seconds(m: re.Match) -> float:
    """时间标签 → 秒。正则已保证数字格式，此处仍做防御性转换。"""
    try:
        minutes = int(m.group(1))
        seconds = int(m.group(2))
        frac_raw = m.group(3) or ""
        frac = int(frac_raw) / (10 ** len(frac_raw)) if frac_raw else 0.0
    except ValueError as exc:  # pragma: no cover - 正则保证数字，防御性兜底
        raise ValueError(f"非法时间标签: {m.group(0)!r}") from exc
    return minutes * 60.0 + seconds + frac


def _safe_float(text: str, default: float) -> float:
    """宽松解析浮点数，失败返回 default（LRC 元数据容错）。"""
    try:
        return float(text)
    except ValueError:
        return default


def _split_word_tags(text: str) -> tuple[str, list[WordTiming]]:
    """剥离 Enhanced LRC 词级标签，返回纯文本与词时间列表（无词级标签时返回空列表）。"""
    if "<" not in text:
        return text, []
    matches = list(_WORD_TAG.finditer(text))
    if not matches:
        return text, []
    try:
        words: list[WordTiming] = []
        for i, m in enumerate(matches):
            start = _tag_to_seconds(m)
            end = _tag_to_seconds(matches[i + 1]) if i + 1 < len(matches) else None
            seg_start = m.end()
            seg_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            word_text = text[seg_start:seg_end].strip()
            if word_text:
                words.append(WordTiming(start=start, end=end, text=word_text))
    except ValueError:
        return text, []  # 词级标签非法时按 v1 忽略
    display = _WORD_TAG.sub(" ", text).strip()
    return display, words


def _parse_line(raw: str) -> tuple[list[float], str, list[WordTiming]]:
    """解析单行：返回该行携带的全部时间标签、文本、词级时间。非法行时间列表为空。"""
    times: list[float] = []
    rest = raw
    while True:
        m = _TIME_TAG.match(rest)
        if not m:
            break
        try:
            times.append(_tag_to_seconds(m))
        except ValueError:
            break  # 非法时间标签：忽略该行剩余部分
        rest = rest[m.end() :]
    text, words = _split_word_tags(rest.strip())
    return times, text, words


def parse_lrc(text: str) -> LrcDocument:
    """解析 LRC 文本。容错：无时间戳行、非法时间、空行均忽略；输出按时间稳定排序并完成双语配对。"""
    doc = LrcDocument()
    entries: list[LyricLine] = []
    offset_ms = 0.0

    if not isinstance(text, str):
        return doc

    for raw in text.splitlines():
        # UTF-8 BOM 只会出现在首行，但对每行 lstrip 也能容忍拼接文件。
        line = raw.lstrip("\ufeff").strip()
        if not line:
            continue
        meta = _META_TAG.match(line)
        if meta:
            key, value = meta.group(1).lower(), meta.group(2).strip()
            if key == "ti" and value:
                doc.title = value
            elif key == "ar" and value:
                doc.artist = value
            elif key == "al" and value:
                doc.album = value
            elif key == "offset":
                offset_ms = _safe_float(value, 0.0)
            continue
        times, body, words = _parse_line(line)
        if not times or not body:
            continue
        for t in times:
            entries.append(
                LyricLine(time=t, text=body, words=list(words) if words else None)
            )

    offset_s = offset_ms / 1000.0
    for e in entries:
        e.time = max(0.0, e.time + offset_s)
    entries.sort(key=lambda e: e.time)

    # 双语配对：相邻条目时间戳相同或差值 < 0.05s 时，第二条视为第一条的译文
    paired: list[LyricLine] = []
    i = 0
    while i < len(entries):
        cur = entries[i]
        if i + 1 < len(entries):
            nxt = entries[i + 1]
            if abs(nxt.time - cur.time) < PAIR_TOLERANCE_S and cur.translation is None:
                cur.translation = nxt.text
                i += 2
                paired.append(cur)
                continue
        paired.append(cur)
        i += 1

    doc.lines = paired
    doc.offset = offset_s
    return doc
