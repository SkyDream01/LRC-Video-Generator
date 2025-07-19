# lrc_parser.py
import re
import datetime
from collections import defaultdict

def parse_bilingual_lrc_with_metadata(lrc_content):
    """
    解析LRC文件，同时提取歌词和元数据 (ti, ar, al)。
    返回一个元组: (lyrics, metadata)
    - lyrics: [(start_time, primary, secondary), ...]
    - metadata: {'ti': '...', 'ar': '...'}
    """
    time_regex = re.compile(r'\[(\d{2}):(\d{2})\.(\d{2,3})\]')
    meta_regex = re.compile(r'\[(ti|ar|al|by):([^\]]*)\]')
    
    lines = lrc_content.splitlines()

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
            continue # 处理完元数据，跳过该行后续处理

        # 匹配时间戳和歌词
        time_match = time_regex.search(line)
        if time_match:
            minutes = int(time_match.group(1))
            seconds = int(time_match.group(2))
            milliseconds = int(time_match.group(3).ljust(3, '0'))
            start_time = datetime.timedelta(
                minutes=minutes, seconds=seconds, milliseconds=milliseconds
            ).total_seconds()

            lyric_text = line[time_match.end():].strip()
            if lyric_text:
                timed_lyrics[start_time].append(lyric_text)

    lyrics = []
    for start_time, texts in sorted(timed_lyrics.items()):
        if not texts: continue

        primary_text, secondary_text = "", ""
        if len(texts) >= 2:
            primary_text = texts[0].strip()
            secondary_text = texts[1].strip()
        elif len(texts) == 1:
            parts = texts[0].split('/', 1)
            primary_text = parts[0].strip()
            if len(parts) > 1:
                secondary_text = parts[1].strip()

        if primary_text:
            lyrics.append((start_time, primary_text, secondary_text))

    return lyrics, metadata