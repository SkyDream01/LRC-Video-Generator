# lrc_parser.py
# 负责解析 LRC 歌词文件的模块。

import re
import datetime
from collections import defaultdict

def parse_bilingual_lrc_with_metadata(lrc_content: str) -> tuple:
    """
    解析LRC文件内容，同时提取歌词和元数据 (ti, ar, al)。
    增强了鲁棒性，支持：
    1. 非标准位数的时间戳 (如 [1:2.3])
    2. 一行多个时间戳 (如 [00:10.00][00:20.00]复用歌词)
    3. 标准/非标准毫秒格式自动兼容

    Args:
        lrc_content (str): LRC文件的完整文本内容。

    Returns:
        tuple: (lyrics, metadata)
               - lyrics: List[(start_time, primary_text, secondary_text)]
               - metadata: Dict
    """
    # 优化1：更宽松的正则表达式
    # \d+ 允许 1位或多位数字，增强兼容性
    # 匹配 [mm:ss.xx] 或 [mm:ss.xxx] 或 [m:s.x]
    time_regex = re.compile(r'\[(\d+):(\d+)\.(\d+)\]')
    
    # 匹配元数据标签 [key:value]
    meta_regex = re.compile(r'\[(ti|ar|al|by):([^\]]*)\]')
    
    lines = lrc_content.splitlines()
    timed_lyrics = defaultdict(list)
    metadata = {}

    for line in lines:
        line = line.strip()
        if not line: continue

        # 1. 优先匹配元数据
        # 考虑到某些LRC可能把元数据放在行尾（罕见但存在），或者一行多个标签
        # 这里简化处理：如果是元数据行，通常整行都是
        meta_match = meta_regex.match(line)
        if meta_match:
            key = meta_match.group(1)
            value = meta_match.group(2).strip()
            if value:
                metadata[key] = value
            continue

        # 2. 查找行内所有时间戳（处理一行多时间戳的情况）
        # finditer 会按顺序找到所有匹配项
        matches = list(time_regex.finditer(line))
        
        if matches:
            # 提取纯歌词文本：将这行里所有的时间戳都替换为空
            # 这样 [00:01.00][00:02.00]歌词 -> 歌词
            lyric_text = time_regex.sub('', line).strip()
            
            # 如果整行只有时间戳没有字（例如空行占位），视为跳过或空字串
            # 取决于具体需求，这里保留空字符串，因为可能代表间奏清空屏幕
            
            for match in matches:
                try:
                    minutes = int(match.group(1))
                    seconds = int(match.group(2))
                    
                    # 优化2：毫秒处理逻辑
                    # LRC标准中 .xx 是百分秒(centiseconds)，.xxx 是毫秒
                    # 逻辑：将数字字符串视为小数部分。
                    # "1" -> 0.1s = 100ms
                    # "12" -> 0.12s = 120ms
                    # "123" -> 0.123s = 123ms
                    # "05" -> 0.05s = 50ms
                    ms_str = match.group(3)
                    # 使用 ljust(3, '0') 模拟小数位对齐，然后取前3位
                    milliseconds = int(ms_str.ljust(3, '0')[:3])
                    
                    start_time = datetime.timedelta(
                        minutes=minutes, seconds=seconds, milliseconds=milliseconds
                    ).total_seconds()
                    
                    if lyric_text:
                        timed_lyrics[start_time].append(lyric_text)
                except ValueError:
                    continue # 忽略格式错误的数字

    # 3. 整理与排序
    lyrics = []
    # 按时间顺序处理
    for start_time in sorted(timed_lyrics.keys()):
        texts = timed_lyrics[start_time]
        if not texts:
            continue

        primary_text, secondary_text = "", ""
        
        # 这里的 texts 列表可能包含：
        # 情况A (双语LRC-双行): ["English Line", "中文翻译"]
        # 情况B (普通LRC-重复): ["Chorus Line", "Chorus Line"] -> 这种通常是误判或者是为了加重？
        # 一般来说，同一时间戳出现不同文本才视为翻译，出现相同文本去重
        
        # 简单去重 (保持顺序)
        unique_texts = []
        seen = set()
        for t in texts:
            if t not in seen:
                unique_texts.append(t)
                seen.add(t)
        
        if len(unique_texts) >= 2:
            # 格式1：多行模式 (通常第一行是原文，第二行是译文)
            primary_text = unique_texts[0].strip()
            secondary_text = unique_texts[1].strip()
        elif len(unique_texts) == 1:
            # 格式2：单行分隔符模式 (English / 中文)
            parts = unique_texts[0].split('/', 1)
            primary_text = parts[0].strip()
            if len(parts) > 1:
                secondary_text = parts[1].strip()
        
        if primary_text or secondary_text:
            lyrics.append((start_time, primary_text, secondary_text))

    return lyrics, metadata