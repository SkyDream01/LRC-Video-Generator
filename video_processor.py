# video_processor.py
import subprocess
import os
import sys
import tempfile
import shlex
import re
from pathlib import Path
from lrc_parser import parse_bilingual_lrc_with_metadata
from animations import BACKGROUND_ANIMATIONS, TEXT_ANIMATIONS, COVER_ANIMATIONS, GENERATIVE_BACKGROUND_ANIMATIONS

def to_ffmpeg_color(hex_color):
    """将十六进制颜色字符串转换为FFmpeg格式。"""
    return f"0x{hex_color[1:]}" if hex_color.startswith('#') else hex_color

def get_ffmpeg_probe_path(ffmpeg_path_str: str) -> str:
    """安全地获取ffprobe路径，优先查找同级目录，其次在PATH中查找。"""
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
        result = subprocess.run(cmd, check=True, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
        return result.stdout.strip().split('\n')[0] # 取第一个结果
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise FileNotFoundError(f"在FFmpeg同目录和系统PATH中都找不到 '{ffprobe_exe}'")

def _get_media_duration(ffprobe_path, media_path, logger):
    """获取媒体文件时长。"""
    logger.status_update(f"正在分析文件: {Path(media_path).name}")
    cmd = [ffprobe_path, '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', str(media_path)]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
    duration = float(result.stdout.strip())
    logger.status_update(f"文件时长: {duration:.2f}s")
    return duration

def _build_filter_complex(
    lrc_data, duration,
    background_anim, text_anim, cover_anim,
    font_primary, font_size_primary, color_primary,
    font_secondary, font_size_secondary, color_secondary,
    outline_color, outline_width, logger,
    background_stream_idx, cover_stream_idx,
    preview_time=None,
    is_preview=False
):
    """构建完整的FFmpeg filter_complex字符串。"""
    logger.status_update(f"构建滤镜图 (背景: {background_anim}, 歌词: {text_anim}, 封面: {cover_anim})...")

    if background_anim not in BACKGROUND_ANIMATIONS: raise ValueError(f"未知背景动画: {background_anim}")
    if text_anim not in TEXT_ANIMATIONS: raise ValueError(f"未知文本动画: {text_anim}")
    if cover_anim not in COVER_ANIMATIONS: raise ValueError(f"未知封面动画: {cover_anim}")

    background_anim_func = BACKGROUND_ANIMATIONS[background_anim]
    text_anim_func = TEXT_ANIMATIONS[text_anim]
    cover_anim_func = COVER_ANIMATIONS[cover_anim]

    W, H, FPS = 1920, 1080, 60
    font_primary_escaped = str(font_primary).replace('\\', '/').replace(':', '\\:')
    font_secondary_escaped = str(font_secondary).replace('\\', '/').replace(':', '\\:')

    lyrics_with_ends = [(start, lrc_data[i + 1][0] if i + 1 < len(lrc_data) else duration, primary, secondary)
                        for i, (start, primary, secondary) in enumerate(lrc_data)]

    visible_lyrics = lyrics_with_ends
    if is_preview and preview_time is not None:
        logger.status_update(f"优化预览: 筛选时间点 {preview_time:.2f}s 附近的歌词...")
        current_lyric_index = -1
        for i, (start, end, _, _) in enumerate(lyrics_with_ends):
            if start <= preview_time < end:
                current_lyric_index = i
                break
        
        if current_lyric_index != -1:
            if text_anim == "淡入淡出":
                visible_lyrics = [lyrics_with_ends[current_lyric_index]]
                logger.status_update("预览模式: 淡入淡出，只加载1行歌词。")
            elif text_anim == "滚动列表":
                window_size = 7
                start_idx = max(0, current_lyric_index - window_size)
                end_idx = min(len(lyrics_with_ends), current_lyric_index + window_size + 1)
                visible_lyrics = lyrics_with_ends[start_idx:end_idx]
                logger.status_update(f"预览模式: 滚动列表，加载了 {len(visible_lyrics)} 行歌词。")
        else:
            visible_lyrics = []
            logger.status_update("预览模式: 当前时间点无歌词。")

    filters = []
    base_bg_stream = "[base_bg]"

    # --- 1. 背景处理逻辑重构 ---
    bg_filter_str = background_anim_func(W=W, H=H, FPS=FPS, duration=duration)
    if background_anim in GENERATIVE_BACKGROUND_ANIMATIONS:
        # 如果是生成式动画，它自己就是流的起点
        filters.append(f"{bg_filter_str}{base_bg_stream}")
    else:
        # 如果是滤镜式动画，需要一个输入流
        filters.append(f"[{background_stream_idx}:v]{bg_filter_str}{base_bg_stream}")

    # 2. 封面 (来自指定视频输入)
    cover_filter_str = cover_anim_func(duration=duration)
    filters.append(f"[{cover_stream_idx}:v]{cover_filter_str}[fg_cover]")

    # 3. 叠加背景和封面 (黄金比例布局)
    filters.append(f"{base_bg_stream}[fg_cover]overlay=x='(W/2.618-w)/2':y='(H-h)/2'[final_bg]")

    # 4. 歌词动画
    base_filter = "[final_bg]"
    if visible_lyrics:
        full_drawtext_string = text_anim_func(
            lyrics_with_ends=visible_lyrics,
            font_primary_escaped=font_primary_escaped, font_size_primary=font_size_primary,
            color_primary_ffmpeg=to_ffmpeg_color(color_primary),
            font_secondary_escaped=font_secondary_escaped, font_size_secondary=font_size_secondary,
            color_secondary_ffmpeg=to_ffmpeg_color(color_secondary),
            outline_color_ffmpeg=to_ffmpeg_color(outline_color), outline_width=outline_width
        )
        base_filter += full_drawtext_string
    
    base_filter += ",format=yuv420p"

    # 5. 时间选择（用于预览）
    if is_preview:
        filters.append(f"{base_filter},select='eq(n\\,{int(preview_time * FPS)})'[v]")
    else:
        filters.append(f"{base_filter}[v]")

    return ";".join(filters)

def _run_ffmpeg_process(command, logger, duration=0):
    """通用FFmpeg进程执行函数。"""
    logged_command = ' '.join(shlex.quote(str(s)) for s in command)
    logger.status_update(f"--- 开始执行FFmpeg ---\n{logged_command}\n----------------------")
    
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        universal_newlines=True, encoding='utf-8', errors='ignore',
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
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
        raise RuntimeError(f"FFmpeg 执行失败，返回码: {process.returncode}。请检查日志。")

def _process_media(params, is_preview=False):
    """统一处理视频生成和预览的通用函数。"""
    temp_filter_file = None
    try:
        logger = params['logger']
        ffprobe_path = get_ffmpeg_probe_path(params['ffmpeg_path'])
        duration = _get_media_duration(ffprobe_path, params['audio_path'], logger)
        params['duration'] = duration

        logger.status_update("正在解析双语LRC文件...")
        with open(params['lrc_path'], 'r', encoding='utf-8') as f:
            lrc_data, _ = parse_bilingual_lrc_with_metadata(f.read())
        if not lrc_data:
            raise ValueError("LRC文件解析失败或内容为空。")

        # --- 核心修改：动态确定输入文件和流索引 ---
        is_generative_bg = params["background_anim"] in GENERATIVE_BACKGROUND_ANIMATIONS
        use_separate_bg = params.get('background_path') and params['background_path'] != params['cover_path']

        command_inputs = []
        
        # 输入0：封面（始终需要）
        cover_stream_idx = 0
        command_inputs.extend(['-i', str(params['cover_path'])])

        # 背景流索引：仅在非生成式动画时有效
        background_stream_idx = -1 
        if not is_generative_bg:
            if use_separate_bg:
                # 如果有独立背景图，则添加为输入1
                background_stream_idx = 1
                command_inputs.extend(['-i', str(params['background_path'])])
            else:
                # 否则，背景复用封面流
                background_stream_idx = 0
        
        # 音频输入（仅在生成最终视频时需要）
        audio_map_str = ""
        if not is_preview:
            # 正确计算音频文件的输入索引（每个-i参数算一个输入）
            audio_input_idx = int(len(command_inputs) / 2)
            command_inputs.extend(['-i', str(params['audio_path'])])
            audio_map_str = f'-map {audio_input_idx}:a'

        filter_params = {
            "lrc_data": lrc_data, "duration": duration,
            "background_anim": params["background_anim"], "text_anim": params["text_anim"], "cover_anim": params["cover_anim"],
            "font_primary": params["font_primary"], "font_size_primary": params["font_size_primary"], "color_primary": params["color_primary"],
            "font_secondary": params["font_secondary"], "font_size_secondary": params["font_size_secondary"], "color_secondary": params["color_secondary"],
            "outline_color": params["outline_color"], "outline_width": params["outline_width"], "logger": logger,
            "preview_time": params.get("preview_time"), "is_preview": is_preview,
            "cover_stream_idx": cover_stream_idx,
            "background_stream_idx": background_stream_idx
        }
        full_filter_complex_string = _build_filter_complex(**filter_params)
        
        with tempfile.NamedTemporaryFile(mode='w', suffix=".txt", delete=False, encoding='utf-8') as f:
            f.write(full_filter_complex_string)
            temp_filter_file = f.name
            logger.status_update(f"已生成临时滤镜脚本: {temp_filter_file}")

        # --- 动态构建最终的FFmpeg命令 ---
        command_base = [params['ffmpeg_path'], '-y', *command_inputs]
        command_filters = ['-filter_complex_script', temp_filter_file]
        
        if is_preview:
            command = [*command_base, *command_filters, '-map', '[v]', '-vframes', '1', str(params['output_image_path'])]
        else:
            video_codec_params = ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20']
            if (hw_accel := params.get('hw_accel')) and hw_accel != "无 (软件编码 x264)":
                if "NVIDIA" in hw_accel: video_codec_params = ['-c:v', 'h264_nvenc', '-preset', 'fast', '-cq', '23', '-profile:v', 'high']
                elif "AMD" in hw_accel: video_codec_params = ['-c:v', 'h264_amf', '-quality', 'balanced', '-rc', 'cqp', '-qp_p', '23', '-qp_i', '23']
                elif "Intel" in hw_accel: video_codec_params = ['-c:v', 'h264_qsv', '-preset', 'fast', '-global_quality', '23']
                params['logger'].status_update(f"启用硬件加速: {hw_accel}，使用编码器 {video_codec_params[1]}")
            
            command = [
                *command_base, *command_filters,
                '-map', '[v]', *audio_map_str.split(),
                *video_codec_params,
                '-c:a', 'aac', '-b:a', '320k', '-pix_fmt', 'yuv420p', '-r', str(60),
                '-t', str(duration), str(params['output_path'])
            ]
        
        _run_ffmpeg_process(command, logger, duration if not is_preview else 0)
        logger.status_update("处理成功完成。")

    finally:
        if temp_filter_file and os.path.exists(temp_filter_file):
            try:
                os.remove(temp_filter_file)
                logger.status_update(f"已清理临时文件: {temp_filter_file}")
            except OSError as e:
                logger.status_update(f"清理临时文件失败: {e}")

def create_karaoke_video(**kwargs):
    """创建卡拉OK视频。"""
    _process_media(kwargs, is_preview=False)

def create_preview_frame(**kwargs):
    """创建预览帧。"""
    _process_media(kwargs, is_preview=True)