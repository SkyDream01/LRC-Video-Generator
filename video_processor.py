# video_processor.py
# 核心视频处理模块，负责构建和执行 FFmpeg 命令。

import subprocess
import os
import sys
import tempfile
import shlex
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Tuple

from lrc_parser import parse_bilingual_lrc_with_metadata
from animations import (
    BACKGROUND_ANIMATIONS, TEXT_ANIMATIONS, COVER_ANIMATIONS,
    GENERATIVE_BACKGROUND_ANIMATIONS
)

# [新增] 使用 dataclass 封装所有参数，提高代码可读性和类型安全性
@dataclass
class VideoGenParams:
    """存储视频生成所需的所有参数。"""
    audio_path: Path
    cover_path: Path
    lrc_path: Path
    background_path: Path
    font_primary: Path
    font_size_primary: int
    font_secondary: Path
    font_size_secondary: int
    color_primary: str
    color_secondary: str
    outline_color: str
    outline_width: int
    background_anim: str
    text_anim: str
    cover_anim: str
    ffmpeg_path: str
    hw_accel: str
    output_path: Path = field(default=None)
    output_image_path: Path = field(default=None)
    preview_time: float = 0.0
    logger: object = None
    duration: float = 0.0

def to_ffmpeg_color(hex_color: str) -> str:
    """将十六进制颜色字符串转换为FFmpeg可用的 '0xRRGGBB' 格式。"""
    return f"0x{hex_color.lstrip('#')}"

def get_ffmpeg_probe_path(ffmpeg_path_str: str) -> str:
    """
    安全地获取 ffprobe 的路径。
    优先查找与 ffmpeg 同级的目录，其次在系统 PATH 中查找。
    """
    if ffmpeg_path_str == 'ffmpeg':
        return 'ffprobe'

    ffmpeg_path = Path(ffmpeg_path_str)
    ffprobe_exe = 'ffprobe.exe' if sys.platform == 'win32' else 'ffprobe'

    # 1. 检查同级目录
    ffprobe_path_sibling = ffmpeg_path.parent / ffprobe_exe
    if ffprobe_path_sibling.is_file():
        return str(ffprobe_path_sibling)

    # 2. 尝试在系统 PATH 中查找
    try:
        cmd = ['where' if sys.platform == 'win32' else 'which', ffprobe_exe]
        result = subprocess.run(
            cmd, check=True, capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        )
        return result.stdout.strip().split('\n')[0]
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise FileNotFoundError(f"在FFmpeg同目录和系统PATH中都找不到 '{ffprobe_exe}'")

def _get_media_duration(ffprobe_path: str, media_path: Path, logger) -> float:
    """获取媒体文件的总时长（秒）。"""
    logger.status_update(f"正在分析文件: {media_path.name}")
    cmd = [
        ffprobe_path, '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', str(media_path)
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, check=True,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
    )
    duration = float(result.stdout.strip())
    logger.status_update(f"文件时长: {duration:.2f}s")
    return duration

def _build_filter_complex(params: VideoGenParams, lrc_data: List, is_preview: bool) -> str:
    """
    构建完整的FFmpeg filter_complex字符串。
    """
    params.logger.status_update(f"构建滤镜图 (背景: {params.background_anim}, 歌词: {params.text_anim}, 封面: {params.cover_anim})...")

    W, H, FPS = 1920, 1080, 60

    # 确定输入流索引
    is_generative_bg = params.background_anim in GENERATIVE_BACKGROUND_ANIMATIONS
    use_separate_bg = params.background_path != params.cover_path
    cover_stream_idx = 0
    background_stream_idx = 1 if not is_generative_bg and use_separate_bg else 0

    # 准备歌词数据
    lyrics_with_ends = [
        (start, lrc_data[i + 1][0] if i + 1 < len(lrc_data) else params.duration, primary, secondary)
        for i, (start, primary, secondary) in enumerate(lrc_data)
    ]
    visible_lyrics = _get_visible_lyrics(lyrics_with_ends, params, is_preview)

    # 构建滤镜链
    filters = []
    bg_filter_str = BACKGROUND_ANIMATIONS[params.background_anim](W=W, H=H, FPS=FPS, duration=params.duration)
    if is_generative_bg:
        filters.append(f"{bg_filter_str}[base_bg]")
    else:
        filters.append(f"[{background_stream_idx}:v]{bg_filter_str}[base_bg]")

    cover_filter_str = COVER_ANIMATIONS[params.cover_anim](duration=params.duration)
    filters.append(f"[{cover_stream_idx}:v]{cover_filter_str}[fg_cover]")
    filters.append(f"[base_bg][fg_cover]overlay=x='(W/2.618-w)/2':y='(H-h)/2'[final_bg]")

    text_filter_str = ""
    if visible_lyrics:
        font_primary_escaped = str(params.font_primary).replace('\\', '/').replace(':', '\\:')
        font_secondary_escaped = str(params.font_secondary).replace('\\', '/').replace(':', '\\:')
        text_filter_str = TEXT_ANIMATIONS[params.text_anim](
            lyrics_with_ends=visible_lyrics,
            font_primary_escaped=font_primary_escaped,
            font_size_primary=params.font_size_primary,
            color_primary_ffmpeg=to_ffmpeg_color(params.color_primary),
            font_secondary_escaped=font_secondary_escaped,
            font_size_secondary=params.font_size_secondary,
            color_secondary_ffmpeg=to_ffmpeg_color(params.color_secondary),
            outline_color_ffmpeg=to_ffmpeg_color(params.outline_color),
            outline_width=params.outline_width
        )

    final_chain = f"[final_bg]{text_filter_str},format=yuv420p"
    if is_preview:
        filters.append(f"{final_chain},select='eq(n\\,{int(params.preview_time * FPS)})'[v]")
    else:
        filters.append(f"{final_chain}[v]")
    return ";".join(filters)

def _get_visible_lyrics(lyrics_with_ends: List, params: VideoGenParams, is_preview: bool) -> List:
    """根据是否为预览模式，筛选出需要渲染的歌词以优化性能。"""
    if not is_preview:
        return lyrics_with_ends

    params.logger.status_update(f"优化预览: 筛选时间点 {params.preview_time:.2f}s 附近的歌词...")
    current_lyric_index = next((i for i, (start, end, _, _) in enumerate(lyrics_with_ends) if start <= params.preview_time < end), -1)

    if current_lyric_index == -1:
        params.logger.status_update("预览模式: 当前时间点无歌词。")
        return []

    if params.text_anim == "淡入淡出":
        params.logger.status_update("预览模式: 淡入淡出，只加载1行歌词。")
        return [lyrics_with_ends[current_lyric_index]]

    if params.text_anim == "滚动列表":
        window_size = 7
        start_idx = max(0, current_lyric_index - window_size)
        end_idx = min(len(lyrics_with_ends), current_lyric_index + window_size + 1)
        visible_lyrics = lyrics_with_ends[start_idx:end_idx]
        params.logger.status_update(f"预览模式: 滚动列表，加载了 {len(visible_lyrics)} 行歌词。")
        return visible_lyrics

    return lyrics_with_ends

def _run_ffmpeg_process(command: List[str], logger, duration: float = 0):
    """通用FFmpeg进程执行函数，包含进度解析。"""
    logged_command = ' '.join(shlex.quote(str(s)) for s in command)
    logger.status_update(f"--- 开始执行FFmpeg ---\n{logged_command}\n----------------------")

    creationflags = subprocess.CREATE_NO_WINDOW | subprocess.NORMAL_PRIORITY_CLASS if sys.platform == 'win32' else 0
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        universal_newlines=True, encoding='utf-8', errors='ignore',
        creationflags=creationflags
    )

    if hasattr(logger, 'progress_update') and duration > 0:
        for line in iter(process.stdout.readline, ''):
            logger.status_update(line.strip())
            if progress_match := re.search(r'time=(\d{2}):(\d{2}):(\d{2})\.(\d{2})', line):
                h, m, s, ds = map(float, progress_match.groups())
                current_time = h * 3600 + m * 60 + s + ds / 100
                percent = int(100 * current_time / duration)
                logger.progress_update(percent)
    else:
        stdout, _ = process.communicate()
        if stdout: logger.status_update(stdout)

    process.wait()
    if process.returncode != 0:
        raise subprocess.CalledProcessError(process.returncode, command, "FFmpeg 执行失败，请检查日志。")

def _process_media(params: VideoGenParams, is_preview: bool = False):
    """统一处理视频生成和预览的通用函数。"""
    temp_filter_file = None
    try:
        logger = params.logger
        ffprobe_path = get_ffmpeg_probe_path(params.ffmpeg_path)
        params.duration = _get_media_duration(ffprobe_path, params.audio_path, logger)

        logger.status_update("正在解析双语LRC文件...")
        with open(params.lrc_path, 'r', encoding='utf-8') as f:
            lrc_data, _ = parse_bilingual_lrc_with_metadata(f.read())
        if not lrc_data:
            raise ValueError("LRC文件解析失败或内容为空。")

        # [修复] 1. 统一构建所有输入
        command_inputs = ['-i', str(params.cover_path)]
        is_generative_bg = params.background_anim in GENERATIVE_BACKGROUND_ANIMATIONS
        if not is_generative_bg and params.background_path != params.cover_path:
            command_inputs.extend(['-i', str(params.background_path)])

        audio_map_str = ""
        if not is_preview:
            audio_input_idx = len(command_inputs) // 2
            command_inputs.extend(['-i', str(params.audio_path)])
            audio_map_str = f'-map {audio_input_idx}:a'

        # 2. 构建滤镜并写入临时文件
        full_filter_complex_string = _build_filter_complex(params, lrc_data, is_preview)
        with tempfile.NamedTemporaryFile(mode='w', suffix=".txt", delete=False, encoding='utf-8') as f:
            f.write(full_filter_complex_string)
            temp_filter_file = f.name
            logger.status_update(f"已生成临时滤镜脚本: {temp_filter_file}")

        # [修复] 3. 使用包含所有输入的 `command_inputs` 构建命令
        command_base = [params.ffmpeg_path, '-y', *command_inputs]
        command_filters = ['-filter_complex_script', temp_filter_file]

        if is_preview:
            command = [*command_base, *command_filters, '-map', '[v]', '-vframes', '1', str(params.output_image_path)]
        else:
            video_codec_params = ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20']
            if params.hw_accel and "无" not in params.hw_accel:
                if "NVIDIA" in params.hw_accel: video_codec_params = ['-c:v', 'h264_nvenc', '-preset', 'fast', '-cq', '23', '-profile:v', 'high']
                elif "AMD" in params.hw_accel: video_codec_params = ['-c:v', 'h264_amf', '-quality', 'balanced', '-rc', 'cqp', '-qp_p', '23', '-qp_i', '23']
                elif "Intel" in params.hw_accel: video_codec_params = ['-c:v', 'h264_qsv', '-preset', 'fast', '-global_quality', '23']
                logger.status_update(f"启用硬件加速: {params.hw_accel}，使用编码器 {video_codec_params[1]}")

            command = [
                *command_base, *command_filters, '-map', '[v]', *audio_map_str.split(),
                *video_codec_params, '-c:a', 'aac', '-b:a', '320k', '-pix_fmt', 'yuv420p',
                '-r', str(60), '-t', str(params.duration), str(params.output_path)
            ]

        _run_ffmpeg_process(command, logger, params.duration if not is_preview else 0)
        logger.status_update("处理成功完成。")

    finally:
        if temp_filter_file and os.path.exists(temp_filter_file):
            try:
                os.remove(temp_filter_file)
                logger.status_update(f"已清理临时文件: {temp_filter_file}")
            except OSError as e:
                logger.status_update(f"清理临时文件失败: {e}")

def create_karaoke_video(params: VideoGenParams):
    """创建卡拉OK视频的入口函数。"""
    _process_media(params, is_preview=False)

def create_preview_frame(params: VideoGenParams):
    """创建预览帧的入口函数。"""
    _process_media(params, is_preview=True)