# lrc_parser.py
# 负责解析 LRC 歌词文件的模块。

import re
import datetime
from collections import defaultdict

def parse_bilingual_lrc_with_metadata(lrc_content: str) -> tuple:
    """
    解析LRC文件内容，同时提取歌词和元数据 (ti, ar, al)。
    支持两种双语格式：
    1. 时间戳重复：
       [00:10.00]English line
       [00:10.00]中文行
    2. 单行斜杠分隔：
       [00:12.00]English line / 中文行

    Args:
        lrc_content (str): LRC文件的完整文本内容。

    Returns:
        tuple: 一个包含 (lyrics, metadata) 的元组。
               - lyrics: 列表，每个元素为 (start_time, primary_text, secondary_text)。
               - metadata: 字典，包含歌曲元数据，如 {'ti': '...', 'ar': '...'}.
    """
    # 匹配时间戳的正则表达式，例如 [00:12.34] 或 [00:12.345]
    time_regex = re.compile(r'\[(\d{2}):(\d{2})\.(\d{2,3})\]')
    # 匹配元数据标签的正则表达式，例如 [ti:歌曲标题]
    meta_regex = re.compile(r'\[(ti|ar|al|by):([^\]]*)\]')
    
    lines = lrc_content.splitlines()

    # 使用 defaultdict(list) 来处理同一时间戳有多行歌词的情况
    timed_lyrics = defaultdict(list)
    metadata = {}

    for line in lines:
        # 优先匹配元数据
        meta_match = meta_regex.search(line)
        if meta_match:
            key = meta_match.group(1)
            value = meta_match.group(2).strip()
            if value:
                metadata[key] = value
            continue  # 处理完元数据后跳过该行

        # 匹配时间和歌词
        time_match = time_regex.search(line)
        if time_match:
            minutes = int(time_match.group(1))
            seconds = int(time_match.group(2))
            # 将毫秒填充到3位，例如 '34' -> '340'
            milliseconds = int(time_match.group(3).ljust(3, '0'))
            start_time = datetime.timedelta(
                minutes=minutes, seconds=seconds, milliseconds=milliseconds
            ).total_seconds()

            lyric_text = line[time_match.end():].strip()
            if lyric_text:
                timed_lyrics[start_time].append(lyric_text)

    # 对解析出的带时间戳的歌词进行排序和组织
    lyrics = []
    for start_time, texts in sorted(timed_lyrics.items()):
        if not texts:
            continue

        primary_text, secondary_text = "", ""
        if len(texts) >= 2:
            # 格式1：同一时间戳的多行文本
            primary_text = texts[0].strip()
            secondary_text = texts[1].strip()
        elif len(texts) == 1:
            # 格式2：单行内的斜杠分隔
            parts = texts[0].split('/', 1)
            primary_text = parts[0].strip()
            if len(parts) > 1:
                secondary_text = parts[1].strip()

        if primary_text:
            lyrics.append((start_time, primary_text, secondary_text))

    return lyrics, metadata