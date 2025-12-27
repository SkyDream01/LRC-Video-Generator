# video_processor.py
import subprocess
import os
import sys
import tempfile
import re
import shutil
from pathlib import Path
from dataclasses import dataclass, field
from typing import List

from lrc_parser import parse_bilingual_lrc_with_metadata
from animations import (
    BACKGROUND_ANIMATIONS, TEXT_ANIMATIONS, COVER_ANIMATIONS,
    GENERATIVE_BACKGROUND_ANIMATIONS
)

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
    width: int = 1920
    height: int = 1080
    fps: int = 60
    # 布局分割比例 (0.0 - 1.0)，左侧占多少
    layout_split: float = 0.382 

def to_ffmpeg_color(hex_color: str) -> str:
    return f"0x{hex_color.lstrip('#')}"

def get_ffmpeg_probe_path(ffmpeg_path_str: str) -> str:
    if ffmpeg_path_str == 'ffmpeg':
        if shutil.which('ffprobe'): return 'ffprobe'
        if sys.platform == 'win32' and shutil.which('ffprobe.exe'): return 'ffprobe.exe'
    ffmpeg_path = Path(ffmpeg_path_str)
    ffprobe_exe = 'ffprobe.exe' if sys.platform == 'win32' else 'ffprobe'
    ffprobe_path_sibling = ffmpeg_path.parent / ffprobe_exe
    if ffprobe_path_sibling.is_file(): return str(ffprobe_path_sibling)
    found = shutil.which(ffprobe_exe)
    if found: return found
    raise FileNotFoundError(f"在FFmpeg同目录和系统PATH中都找不到 '{ffprobe_exe}'")

def _get_media_duration(ffprobe_path: str, media_path: Path, logger) -> float:
    logger.status_update(f"正在分析文件: {media_path.name}")
    cmd = [ffprobe_path, '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', str(media_path)]
    startupinfo = subprocess.STARTUPINFO() if sys.platform == 'win32' else None
    if sys.platform == 'win32': startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    result = subprocess.run(cmd, capture_output=True, text=True, check=True, startupinfo=startupinfo)
    duration = float(result.stdout.strip())
    logger.status_update(f"文件时长: {duration:.2f}s")
    return duration

def _build_filter_complex(params: VideoGenParams, lrc_data: List, is_preview: bool) -> str:
    # 优化点1：如果是预览，强制降低分辨率 (例如 960x540)，大幅提升处理速度
    # 你的 animations.py 已经写得很好了，是基于 H 进行比例缩放的，所以这里改 W/H 会自动适配字体大小
    target_width = params.width
    target_height = params.height
    
    if is_preview:
        scale_factor = 0.5 # 预览缩放比例，0.5 意味着 1080p -> 540p，速度提升约 4 倍
        target_width = int(target_width * scale_factor)
        target_height = int(target_height * scale_factor)
        # 确保宽高是偶数（FFmpeg yuv420p 要求）
        if target_width % 2 != 0: target_width -= 1
        if target_height % 2 != 0: target_height -= 1

    params.logger.status_update(f"构建滤镜 ({target_width}x{target_height}, split={params.layout_split:.2f})...")
    
    W, H, FPS = target_width, target_height, params.fps
    split_ratio = params.layout_split

    is_generative_bg = params.background_anim in GENERATIVE_BACKGROUND_ANIMATIONS
    use_separate_bg = params.background_path != params.cover_path
    
    # 确定输入流索引
    # 注意：在 _process_media 中，如果是预览模式，且开启了 Input Seeking，
    # 所有的输入流时间轴都被重置了。
    cover_stream_idx = 0
    background_stream_idx = 1 if not is_generative_bg and use_separate_bg else 0

    # 优化点2：时间轴偏移
    # 如果使用了 -ss (Input Seeking)，视频流是从 0 开始的，
    # 但 lrc_data 的时间戳是绝对时间（例如 120秒）。
    # 我们需要把歌词时间戳全部减去 preview_time。
    time_offset = params.preview_time if is_preview else 0.0

    # 处理歌词数据：计算结束时间并应用偏移
    lyrics_with_ends = []
    for i, (start, primary, secondary) in enumerate(lrc_data):
        raw_end = lrc_data[i + 1][0] if i + 1 < len(lrc_data) else params.duration
        
        # 应用偏移
        adj_start = start - time_offset
        adj_end = raw_end - time_offset
        
        lyrics_with_ends.append((adj_start, adj_end, primary, secondary))

    # 筛选当前可见的歌词
    # 对于预览，现在的当前时间点是 0 (因为我们 seek 到了这里)
    # 所以我们要找 adj_start <= 0 < adj_end 或者附近的歌词
    visible_lyrics = _get_visible_lyrics(lyrics_with_ends, params, is_preview, current_t=0.0)

    filters = []
    
    # 1. 背景层
    bg_func = BACKGROUND_ANIMATIONS[params.background_anim]
    # 注意：对于预览，duration 只需要很短，生成 1 帧即可，设置为 1.0 秒防止某些滤镜除以0
    bg_duration = 1.0 if is_preview else params.duration 
    
    try: bg_filter_str = bg_func(W=W, H=H, FPS=FPS, duration=bg_duration)
    except TypeError: bg_filter_str = bg_func(duration=bg_duration)

    if is_generative_bg: filters.append(f"{bg_filter_str}[base_bg]")
    else: filters.append(f"[{background_stream_idx}:v]{bg_filter_str}[base_bg]")

    # 2. 封面层
    cover_func = COVER_ANIMATIONS[params.cover_anim]
    cover_filter_str = cover_func(duration=bg_duration, fps=FPS, W=W, H=H)
    filters.append(f"[{cover_stream_idx}:v]{cover_filter_str}[fg_cover]")
    
    # 3. 混合背景与封面
    filters.append(f"[base_bg][fg_cover]overlay=x='(W*{split_ratio}-w)/2':y='(H-h)/2'[final_bg]")

    # 4. 歌词层
    text_filter_str = ""
    if visible_lyrics:
        font_p = str(params.font_primary).replace('\\', '/').replace(':', '\\:')
        font_s = str(params.font_secondary).replace('\\', '/').replace(':', '\\:')
        
        text_filter_str = TEXT_ANIMATIONS[params.text_anim](
            lyrics_with_ends=visible_lyrics,
            font_primary_escaped=font_p,
            font_size_primary=params.font_size_primary,
            color_primary_ffmpeg=to_ffmpeg_color(params.color_primary),
            font_secondary_escaped=font_s,
            font_size_secondary=params.font_size_secondary,
            color_secondary_ffmpeg=to_ffmpeg_color(params.color_secondary),
            outline_color_ffmpeg=to_ffmpeg_color(params.outline_color),
            outline_width=params.outline_width,
            W=W, H=H,
            layout_split=split_ratio
        )

    # 组装最终链
    # 如果 text_filter_str 为空 (无歌词)，直接使用 [final_bg]
    if text_filter_str:
        final_chain = f"[final_bg]{text_filter_str},format=yuv420p"
    else:
        final_chain = f"[final_bg]format=yuv420p"
    
    # 优化点3：预览模式不再使用 select='eq(n, ...)'
    # 因为我们已经用 -ss 裁剪了输入，现在只需要输出第1帧 [v]
    filters.append(f"{final_chain}[v]")
        
    return ";".join(filters)

def _get_visible_lyrics(lyrics_with_ends: List, params: VideoGenParams, is_preview: bool, current_t: float = 0.0) -> List:
    if not is_preview: return lyrics_with_ends
    
    # params.preview_time 在这里不再使用，因为 lyrics_with_ends 已经根据 offset 调整过了
    # 我们只需要查找包含 time=0 的歌词，或者 time=0 附近的歌词 (滚动列表)
    
    params.logger.status_update(f"优化预览: 筛选可见歌词...")
    
    current_idx = -1
    for i, (start, end, _, _) in enumerate(lyrics_with_ends):
        # 这里的 start 和 end 已经是相对于 preview_time 的相对时间了
        # 所以我们判断 0 是否在区间内
        if start <= 0.1 < end: # 用 0.1稍微偏后一点点，防止刚好卡在边界
            current_idx = i
            break
            
    # 如果没找到（可能是间奏），找最近的一个？或者返回空
    if current_idx == -1:
        # 尝试找最近的一个即将开始的，以便预览能看到点东西
        # 这是一个可选的优化体验
        for i, (start, _, _, _) in enumerate(lyrics_with_ends):
            if start > 0:
                current_idx = i
                break
        if current_idx == -1 and lyrics_with_ends: # 都在后面或者都在前面
             if lyrics_with_ends[-1][1] < 0: current_idx = len(lyrics_with_ends) - 1 # 歌放完了
    
    if current_idx == -1: return []

    if params.text_anim == "淡入淡出": 
        return [lyrics_with_ends[current_idx]]
        
    if params.text_anim == "滚动列表":
        window_size = 5
        start_idx = max(0, current_idx - window_size)
        end_idx = min(len(lyrics_with_ends), current_idx + window_size + 1)
        return lyrics_with_ends[start_idx:end_idx]
        
    return lyrics_with_ends

def _run_ffmpeg_process(command: List[str], logger, duration: float = 0):
    display_command = []
    for arg in command:
        if arg.startswith('filter_complex_script'): display_command.append(arg)
        elif len(str(arg)) > 200: display_command.append(str(arg)[:50] + "...")
        else: display_command.append(str(arg))
    logger.status_update(f"FFmpeg CMD: {' '.join(display_command)}")

    startupinfo = subprocess.STARTUPINFO() if sys.platform == 'win32' else None
    if sys.platform == 'win32': startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        universal_newlines=True, encoding='utf-8', errors='ignore',
        startupinfo=startupinfo
    )

    if hasattr(logger, 'progress_update') and duration > 0:
        for line in iter(process.stdout.readline, ''):
            line = line.strip()
            if not line: continue
            # 过滤掉一些无用的FFmpeg输出以保持日志清洁
            if 'frame=' in line or 'size=' in line or 'time=' in line:
                if progress_match := re.search(r'time=(\d{2}):(\d{2}):(\d{2})\.(\d{2})', line):
                    try:
                        h, m, s, ds = map(float, progress_match.groups())
                        current_time = h * 3600 + m * 60 + s + ds / 100
                        percent = min(99, int(100 * current_time / duration))
                        logger.progress_update(percent)
                    except ValueError: pass
            else:
                 logger.status_update(line)
    else:
        # 预览模式不需要进度条，直接读取全部输出
        stdout, _ = process.communicate()
        if stdout and "Error" in stdout: # 只有错误才打印，避免预览刷屏
            logger.status_update(stdout)

    process.wait()
    if process.returncode != 0:
        raise subprocess.CalledProcessError(process.returncode, command, "FFmpeg 进程异常退出")

def _process_media(params: VideoGenParams, is_preview: bool = False):
    temp_filter_file = None
    try:
        logger = params.logger
        ffprobe_path = get_ffmpeg_probe_path(params.ffmpeg_path)
        if params.duration <= 0:
             params.duration = _get_media_duration(ffprobe_path, params.audio_path, logger)

        logger.status_update("解析LRC...")
        with open(params.lrc_path, 'r', encoding='utf-8') as f:
            lrc_data, _ = parse_bilingual_lrc_with_metadata(f.read())
        
        # 优化点4：构建 Input Seeking 参数
        # 如果是预览，使用 -ss 放在 -i 之前。
        # 注意：这会瞬间定位到该时间点，不需要解码之前的数据。
        ss_args = ['-ss', f"{params.preview_time:.3f}"] if is_preview else []
        
        # 构建输入列表
        command_inputs = []
        
        # Cover Input
        command_inputs.extend([*ss_args, '-i', str(params.cover_path)])
        
        is_generative_bg = params.background_anim in GENERATIVE_BACKGROUND_ANIMATIONS
        if not is_generative_bg and params.background_path != params.cover_path:
            # Background Input
            command_inputs.extend([*ss_args, '-i', str(params.background_path)])

        audio_idx = -1
        if not is_preview:
            # 正常生成模式，不使用 ss_args (因为需要从头生成)，且需要音频
            command_inputs.extend(['-i', str(params.audio_path)])
            audio_idx = len(command_inputs) // 2 - 1 

        full_filter_complex = _build_filter_complex(params, lrc_data, is_preview)
        
        with tempfile.NamedTemporaryFile(mode='w', suffix=".txt", delete=False, encoding='utf-8') as f:
            f.write(full_filter_complex)
            temp_filter_file = f.name
        
        command_base = [params.ffmpeg_path, '-y', *command_inputs]
        command_filters = ['-filter_complex_script', temp_filter_file]

        if is_preview:
            # 优化点5：预览模式参数调整
            # -frames:v 1: 只输出1帧
            command = [
                *command_base, 
                *command_filters, 
                '-map', '[v]', 
                '-frames:v', '1',  # 关键：只处理一帧
                str(params.output_image_path)
            ]
        else:
            video_codec_params = ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20']
            hw_configs = {
                "NVIDIA": ['-c:v', 'h264_nvenc', '-preset', 'p4', '-cq', '23'],
                "AMD": ['-c:v', 'h264_amf', '-usage', 'transcoding', '-rc', 'cqp', '-qp_p', '23', '-qp_i', '23'],
                "Intel": ['-c:v', 'h264_qsv', '-preset', 'medium', '-global_quality', '23']
            }
            for key, val in hw_configs.items():
                if key in params.hw_accel:
                    video_codec_params = val
                    logger.status_update(f"硬件加速: {key}")
                    break

            command = [
                *command_base, *command_filters, 
                '-map', '[v]', '-map', f'{audio_idx}:a',
                *video_codec_params, '-c:a', 'aac', '-b:a', '320k', 
                '-pix_fmt', 'yuv420p', '-r', str(params.fps), 
                '-t', str(params.duration), str(params.output_path)
            ]

        _run_ffmpeg_process(command, logger, params.duration if not is_preview else 0)
        
    finally:
        if temp_filter_file and os.path.exists(temp_filter_file):
            try: os.remove(temp_filter_file)
            except OSError: pass

def create_karaoke_video(params: VideoGenParams):
    _process_media(params, is_preview=False)

def create_preview_frame(params: VideoGenParams):
    _process_media(params, is_preview=True)