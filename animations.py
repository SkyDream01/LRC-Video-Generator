# animations.py
"""
动画效果模块
定义了用于生成视频背景、歌词和专辑封面动画的FFmpeg滤镜函数。
"""
from functools import lru_cache

# --- 背景动画 ---

def get_static_background_filter(W, H, FPS, duration):
    total_frames = int(duration * FPS) if duration > 0 else 1
    return (
        f"scale={W}:-1,crop={W}:{H},boxblur=20:5,"
        f"zoompan=z=1:d={total_frames}:s={W}x{H}:fps={FPS}"
    )

def get_gradient_wave_background_filter(W, H, FPS, duration):
    # 性能优化：在低分辨率下计算波浪，然后放大
    scale_down_factor = 4
    low_W, low_H = W // scale_down_factor, H // scale_down_factor
    r_expr = f"'128 + 64*sin(X/{150 / scale_down_factor} + T*2) + 64*cos(Y/{150 / scale_down_factor} + T*2.5)'"
    g_expr = f"'128 + 64*sin(X/{180 / scale_down_factor} + T*1.5) + 64*cos(Y/{120 / scale_down_factor} + T*2)'"
    b_expr = f"'128 + 64*sin(X/{120 / scale_down_factor} + T*2.5) + 64*cos(Y/{180 / scale_down_factor} + T*1.5)'"
    return (
        f"nullsrc=s={low_W}x{low_H}:r={FPS}:d={duration},format=yuv420p,"
        f"geq=r={r_expr}:g={g_expr}:b={b_expr},"
        f"scale=w={W}:h={H}:flags=spline"
    )

def get_wave_blur_background_filter(W, H, FPS, duration):
    scale_down_factor = 2
    low_W, low_H = max(1, W // scale_down_factor), max(1, H // scale_down_factor)
    total_frames = int(duration * FPS) if duration > 0 else 1
    
    # 动态参数：根据分辨率调整波浪大小
    wave_strength = W * 0.0015 
    wave_density = W * 0.025
    wave_speed = 2.0

    low_wave_strength = wave_strength / scale_down_factor
    low_wave_density = wave_density / scale_down_factor
    
    geq_expr = f"p(X,Y+{low_wave_strength}*sin(X/{low_wave_density}+T*{wave_speed}))"

    low_luma_radius = 20 / scale_down_factor
    low_chroma_radius = 5 / scale_down_factor

    return (
        f"scale={low_W}:-1,crop={low_W}:{low_H},"
        f"zoompan=z=1:d={total_frames}:s={low_W}x{low_H}:fps={FPS},"
        f"geq='{geq_expr}',"
        f"boxblur={low_luma_radius}:{low_chroma_radius},"
        f"scale={W}:{H}:flags=spline"
    )

# --- 歌词动画 ---

@lru_cache(maxsize=128)
def _clean_text(text: str) -> str:
    """清理歌词中的特殊字符以避免FFmpeg表达式错误。"""
    return text.replace("'", "’").replace(":", "：").replace("%", "％").replace(',', r'\,')

def get_slide_and_fade_text_animation(lyrics_with_ends, font_primary_escaped, font_size_primary, color_primary_ffmpeg,
                                      font_secondary_escaped, font_size_secondary, color_secondary_ffmpeg,
                                      outline_color_ffmpeg, outline_width, W=1920, H=1080):
    """生成歌词滑动和淡入淡出效果 (支持动态分辨率)。"""
    FADE_DURATION = 0.5
    SLIDE_DISTANCE = H * 0.02 # 相对滑动距离

    drawtext_filters = []
    for start, end, primary_text, secondary_text in lyrics_with_ends:
        enable_expr = f"'between(t,{start},{end})'"
        alpha_expr = f"'if(lt(t,{start}+{FADE_DURATION}),(t-{start})/{FADE_DURATION},if(gt(t,{end}-{FADE_DURATION}),({end}-t)/{FADE_DURATION},1))'"
        y_slide_offset = f"if(lt(t,{start}+{FADE_DURATION}),({FADE_DURATION}-(t-{start}))/{FADE_DURATION}*{SLIDE_DISTANCE},0)"
        
        # 使用相对坐标布局
        x_pos = f"'(W/2.618) + (W*1.618/2.618 - text_w)/2'"
        
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

def get_list_text_animation(lyrics_with_ends, font_primary_escaped, font_size_primary, color_primary_ffmpeg,
                            font_secondary_escaped, font_size_secondary, color_secondary_ffmpeg,
                            outline_color_ffmpeg, outline_width, W=1920, H=1080):
    """滚动列表动画 (支持动态分辨率)。"""
    list_line_height = font_size_primary + font_size_secondary + (H * 0.04) 
    list_x_pos = f"'(W/2.618) + (W*1.618/2.618 - text_w)/2'"
    TRANSITION_DURATION = 0.35
    FADE_DISTANCE_LINES = (H * 0.75 / 2) / list_line_height * 1.5
    highlight_font_size_primary = int(font_size_primary * 1.1)

    if not lyrics_with_ends: return ""

    highlight_idx_expr = f"{len(lyrics_with_ends) - 1}"
    for j in range(len(lyrics_with_ends) - 2, -1, -1):
        highlight_idx_expr = f"if(lt(t,{lyrics_with_ends[j + 1][0]}),{j},{highlight_idx_expr})"

    def get_target_y(j):
        return (H / 2.0) - (list_line_height / 2.0) - (max(0, j) * list_line_height)

    scroll_y_expr = f"{get_target_y(0)}"
    for j in range(len(lyrics_with_ends)):
        start_j, target_y_j, prev_target_y = lyrics_with_ends[j][0], get_target_y(j), get_target_y(j - 1)
        progress = f"clip((t - {start_j}) / {TRANSITION_DURATION}, 0, 1)"
        smoothed_progress = f"(1-cos({progress}*3.14159265))/2"
        transition_expr = f"({prev_target_y} + ({target_y_j} - {prev_target_y}) * {smoothed_progress})"
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
                f"drawtext=fontfile='{font_primary_escaped}':text='{clean_primary}':"
                f"fontsize={highlight_font_size_primary}:fontcolor={color_primary_ffmpeg}:"
                f"bordercolor={outline_color_ffmpeg}:borderw={outline_width+1}:x={list_x_pos}:"
                f"y='{y_pos_primary_expr}':alpha='{alpha_fade_expr}':enable='{is_highlighted_expr}'"
            )
            drawtext_filters.append(
                f"drawtext=fontfile='{font_primary_escaped}':text='{clean_primary}':fontsize={font_size_primary}:"
                f"fontcolor={color_secondary_ffmpeg}:bordercolor={outline_color_ffmpeg}:borderw={outline_width}:x={list_x_pos}:"
                f"y='{y_pos_primary_expr}':alpha='(0.7 * {alpha_fade_expr})':enable='not({is_highlighted_expr})'"
            )
        if secondary_text:
            clean_secondary = _clean_text(secondary_text)
            drawtext_filters.append(
                f"drawtext=fontfile='{font_secondary_escaped}':text='{clean_secondary}':fontsize={font_size_secondary}:"
                f"fontcolor={color_secondary_ffmpeg}:bordercolor={outline_color_ffmpeg}:borderw={min(1, outline_width)}:x={list_x_pos}:"
                f"y='{y_pos_secondary_expr}':alpha='(if({is_highlighted_expr},0.9,0.7) * {alpha_fade_expr})'"
            )

    return ",".join(drawtext_filters)

# --- 专辑封面动画 ---

def get_static_cover_animation_filter(duration, fps=60):
    FPS = fps
    total_frames = int(duration * FPS) if duration > 1 else 1
    img_w, img_h = 600, 600
    refl_h = int(img_h * 0.4)
    canvas_h = img_h + refl_h

    filter_chains = [
        f"scale={img_w}:{img_h},setsar=1,split=2[main][refl_src]",
        f"color=c=black@0.0:s={img_w}x{canvas_h}:r={FPS}:d={duration}[canvas]",
        f"[refl_src]vflip,crop=w={img_w}:h={refl_h}:x=0:y=0,format=yuva444p,"
        f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='128*(1-Y/H)',boxblur=3:1[refl]",
        f"[canvas][main]overlay=x=0:y=0[tmp]",
        f"[tmp][refl]overlay=x=0:y={img_h}[with_refl]",
        f"[with_refl]zoompan=z=1:d={total_frames}:s={img_w}x{canvas_h}:fps={FPS}"
    ]
    return ",".join(filter_chains)

def get_vinyl_record_animation_filter(duration, fps=60):
    FPS = fps
    total_frames = max(1, int(duration * FPS))
    rotation_speed_per_sec = (2 * 3.1415926535) / 10 

    record_size = 640
    label_size = 400
    ss = 8
    W, H = record_size * ss, record_size * ss
    R = W / 2

    # 距离中心的距离表达式
    DX, DY = f'(X-{W/2})', f'(Y-{H/2})'
    D2 = f'(pow({DX},2)+pow({DY},2))'
    Dist = f'sqrt({D2})'

    smooth_width = ss * 1.5
    alpha_expr = f"'255 * clip(({R} - {Dist}) / {smooth_width}, 0, 1)'"

    highlight_D2 = f'(pow(X-{W*0.3},2)+pow(Y-{H*0.3},2))'
    highlight_radius = W * 0.7
    highlight_intensity = f'60*pow(max(0,1-sqrt({highlight_D2})/{highlight_radius}),3)'
    
    R_lead_in_outer, R_lead_in_inner = R * 0.99, R * 0.93
    playable_groove_texture = f"15 + 10*sin({Dist}*3.5*{ss})"
    lead_in_groove_additive = f"if(gte({Dist},{R_lead_in_inner})*lte({Dist},{R_lead_in_outer}), 30 + 30*st(0,sin({Dist}*45*{ss}-PI/2)), 0)"

    color_expr = (
        f"if(lt({D2},{(label_size/2*ss)**2}),"
        f"  LUM,"
        f"  min(255, {playable_groove_texture} + {highlight_intensity} + {lead_in_groove_additive})"
        ")"
    )

    prepare_inputs = (
        f"split[label_src][canvas_src];"
        f"[label_src]scale={label_size}:{label_size}:flags=lanczos,setsar=1[label];"
        f"[canvas_src]scale={record_size}:{record_size},format=yuva444p,lutrgb=r=0:g=0:b=0:a=255[black_canvas];"
        f"[black_canvas][label]overlay=(main_w-overlay_w)/2:(main_h-overlay_h)/2[static_record];"
    )

    apply_effects = (
        f"[static_record]scale=w={W}:h={H},setsar=1,format=yuva444p,"
        f"geq="
        f"r='{color_expr.replace('LUM', 'r(X,Y)')}':"
        f"g='{color_expr.replace('LUM', 'g(X,Y)')}':"
        f"b='{color_expr.replace('LUM', 'b(X,Y)')}':"
        f"a={alpha_expr},"
        f"scale=w={record_size}:h={record_size}:flags=lanczos,"
        f"zoompan=z=1:d={total_frames}:s={record_size}x{record_size}:fps={FPS},"
        f"rotate=a=t*{rotation_speed_per_sec}:c=none:ow={record_size}:oh={record_size}"
    )
    
    full_chain = prepare_inputs + apply_effects
    return full_chain.replace(";", ",")

# 定义动画预设字典
GENERATIVE_BACKGROUND_ANIMATIONS = {"渐变波浪"}

BACKGROUND_ANIMATIONS = {
    "静态模糊": get_static_background_filter,
    "渐变波浪": get_gradient_wave_background_filter,
    "波浪模糊": get_wave_blur_background_filter,  
}

TEXT_ANIMATIONS = {
    "淡入淡出": get_slide_and_fade_text_animation,
    "滚动列表": get_list_text_animation,
}

COVER_ANIMATIONS = {
    "静态展示": get_static_cover_animation_filter,
    "唱片旋转": get_vinyl_record_animation_filter,
}