# lrc2video/animations.py
"""
动画效果模块
定义了用于生成视频背景、歌词和专辑封面动画的FFmpeg滤镜函数。
每个函数都接受一个 duration 参数，以便于实现与时间相关的动画。
"""
from functools import lru_cache

# --- 背景动画 ---

def get_static_background_filter(W, H, FPS, duration):
    """生成静态、模糊的背景滤镜。"""
    total_frames = int(duration * FPS) if duration > 0 else 1
    return (
        f"scale={W}:-1,crop={W}:{H},boxblur=20:5,"
        f"zoompan=z=1:d={total_frames}:s={W}x{H}:fps={FPS}"
    )


# --- 歌词动画 ---

@lru_cache(maxsize=128)
def _clean_text(text):
    """清理歌词中的特殊字符以避免FFmpeg表达式错误。"""
    return text.replace("'", "’").replace(":", "：").replace("%", "％").replace(',', r'\,')

def get_slide_and_fade_text_animation(lyrics_with_ends, font_primary_escaped, font_size_primary, color_primary_ffmpeg,
                                      font_secondary_escaped, font_size_secondary, color_secondary_ffmpeg,
                                      outline_color_ffmpeg, outline_width):
    """生成歌词滑动和淡入淡出效果的 drawtext 滤镜字符串。"""
    FADE_DURATION = 0.5
    SLIDE_DISTANCE = 20
    W, H = 1920, 1080

    drawtext_filters = []
    for start, end, primary_text, secondary_text in lyrics_with_ends:
        enable_expr = f"'between(t,{start},{end})'"
        alpha_expr = f"'if(lt(t,{start}+{FADE_DURATION}),(t-{start})/{FADE_DURATION},if(gt(t,{end}-{FADE_DURATION}),({end}-t)/{FADE_DURATION},1))'"
        y_slide_offset = f"if(lt(t,{start}+{FADE_DURATION}),({FADE_DURATION}-(t-{start}))/{FADE_DURATION}*{SLIDE_DISTANCE},0)"
        
        x_pos = f"'((W*2/3)-text_w)/2'"
        
        if primary_text:
            y_pos_primary = f"'H/2 - ({font_size_primary}*1.5) - ({y_slide_offset})'"
            drawtext_filters.append(
                f"drawtext="
                f"fontfile='{font_primary_escaped}':text='{_clean_text(primary_text)}':fontsize={font_size_primary}:"
                f"fontcolor={color_primary_ffmpeg}:bordercolor={outline_color_ffmpeg}:borderw={outline_width}:"
                f"x={x_pos}:y={y_pos_primary}:alpha={alpha_expr}:enable={enable_expr}"
            )
        if secondary_text:
            y_pos_secondary = f"'H/2 + ({font_size_secondary}*0.5) - ({y_slide_offset})'"
            drawtext_filters.append(
                f"drawtext="
                f"fontfile='{font_secondary_escaped}':text='{_clean_text(secondary_text)}':fontsize={font_size_secondary}:"
                f"fontcolor={color_secondary_ffmpeg}:bordercolor={outline_color_ffmpeg}:borderw={outline_width}:"
                f"x={x_pos}:y={y_pos_secondary}:alpha={alpha_expr}:enable={enable_expr}"
            )

    return ",".join(drawtext_filters)

def get_left_list_right_cover_animation(lyrics_with_ends, font_primary_escaped, font_size_primary, color_primary_ffmpeg,
                                        font_secondary_escaped, font_size_secondary, color_secondary_ffmpeg,
                                        outline_color_ffmpeg, outline_width):
    """在屏幕左侧生成滚动高亮歌词列表。"""
    W, H = 1920, 1080
    list_line_height = font_size_primary + font_size_secondary + 25
    list_x_pos = f"'(W*2/3 - text_w)/2'"
    TRANSITION_DURATION = 0.2
    FADE_DISTANCE_LINES = (H * 6 / 8 / 2) / list_line_height * 1.5

    if not lyrics_with_ends: return ""

    highlight_idx_expr = f"{len(lyrics_with_ends) - 1}"
    for j in range(len(lyrics_with_ends) - 2, -1, -1):
        highlight_idx_expr = f"if(lt(t,{lyrics_with_ends[j + 1][0]}),{j},{highlight_idx_expr})"

    def get_target_y(j):
        return (H / 2.0) - (list_line_height / 2.0) - (max(0, j) * list_line_height)

    scroll_y_expr = f"{get_target_y(0)}"
    for j in range(len(lyrics_with_ends)):
        start_j, target_y_j, prev_target_y = lyrics_with_ends[j][0], get_target_y(j), get_target_y(j - 1)
        transition_expr = f"({prev_target_y} + ({target_y_j} - {prev_target_y}) * (t - {start_j}) / {TRANSITION_DURATION})"
        scroll_y_expr = f"if(gte(t,{start_j}),if(lt(t,{start_j}+{TRANSITION_DURATION}),{transition_expr},{target_y_j}),{scroll_y_expr})"

    drawtext_filters = []
    for i, (_, _, primary_text, secondary_text) in enumerate(lyrics_with_ends):
        y_pos_primary_expr = f"({scroll_y_expr}) + ({i} * {list_line_height})"
        y_pos_secondary_expr = f"({scroll_y_expr}) + {font_size_primary} + ({i} * {list_line_height})"
        is_highlighted_expr = f"eq({i},({highlight_idx_expr}))"
        alpha_fade_expr = f"clip(1-(abs({i}-({highlight_idx_expr})))/{FADE_DISTANCE_LINES},0,1)"

        if primary_text:
            clean_primary = _clean_text(primary_text)
            drawtext_filters.append(
                f"drawtext=fontfile='{font_primary_escaped}':text='{clean_primary}':fontsize={font_size_primary}:"
                f"fontcolor={color_primary_ffmpeg}:bordercolor={outline_color_ffmpeg}:borderw=2:x={list_x_pos}:"
                f"y='{y_pos_primary_expr}':alpha='{alpha_fade_expr}':enable='{is_highlighted_expr}'"
            )
            drawtext_filters.append(
                f"drawtext=fontfile='{font_primary_escaped}':text='{clean_primary}':fontsize={font_size_primary}:"
                f"fontcolor={color_secondary_ffmpeg}:bordercolor={outline_color_ffmpeg}:borderw=2:x={list_x_pos}:"
                f"y='{y_pos_primary_expr}':alpha='(0.7 * {alpha_fade_expr})':enable='not({is_highlighted_expr})'"
            )
        if secondary_text:
            clean_secondary = _clean_text(secondary_text)
            drawtext_filters.append(
                f"drawtext=fontfile='{font_secondary_escaped}':text='{clean_secondary}':fontsize={font_size_secondary}:"
                f"fontcolor={color_secondary_ffmpeg}:bordercolor={outline_color_ffmpeg}:borderw=1:x={list_x_pos}:"
                f"y='{y_pos_secondary_expr}':alpha='(if({is_highlighted_expr},0.9,0.7) * {alpha_fade_expr})'"
            )

    return ",".join(drawtext_filters)

# --- 专辑封面动画 ---

def get_static_cover_animation_filter(duration):
    """
    生成静态封面图的滤镜。
    修复：使用 zoompan 将静态图转为视频流，以确保在滤镜链中正常工作。
    """
    FPS = 60 # 视频帧率
    total_frames = int(duration * FPS) if duration > 1 else 1
    return (
        f"scale=w=500:h=500,setsar=1,"
        f"zoompan=z=1:d={total_frames}:s=500x500:fps={FPS}"
    )

def get_vinyl_record_animation_filter(duration):
    """
    生成一个圆形、旋转的仿黑胶唱片动画（最终兼容版）。
    修复：使用 f-string 修复了旋转速度变量未被正确格式化到字符串中的问题。
    """
    FPS = 60  # 视频帧率
    total_frames = int(duration * FPS) if duration > 1 else 1
    # 速度：每10秒一圈
    rotation_speed_per_sec = (2 * 3.1415926535) / 10

    # 最终修复：使用 f-string 将 rotation_speed_per_sec 变量的值嵌入
    # 并将滤镜链中每一行都变为f-string确保格式正确
    return (
        f"scale=w=500:h=500,setsar=1,"
        f"zoompan=z=1:d={total_frames}:s=500x500:fps={FPS},"
        f"format=yuva444p,"
        f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
        f"a='if(lte((X-W/2)*(X-W/2)+(Y-H/2)*(Y-H/2),(W/2)*(W/2)),255,0)',"
        f"rotate=a=t*{rotation_speed_per_sec}:c=none"
    )

# --- 定义动画预设字典 ---

BACKGROUND_ANIMATIONS = {
    "静态模糊": get_static_background_filter,
}

TEXT_ANIMATIONS = {
    "淡入淡出": get_slide_and_fade_text_animation,
    "滚动列表": get_left_list_right_cover_animation
}

COVER_ANIMATIONS = {
    "静态": get_static_cover_animation_filter,
    "唱片旋转": get_vinyl_record_animation_filter,
}