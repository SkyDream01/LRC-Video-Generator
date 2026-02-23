# lrc2video/animations.py
"""
动画效果模块
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
    scale_down = 4
    low_W, low_H = W // scale_down, H // scale_down
    freq_x = W * 0.08 / scale_down
    freq_y = H * 0.1 / scale_down
    
    r = f"'128 + 64*sin(X/{freq_x} + T*2) + 64*cos(Y/{freq_x} + T*2.5)'"
    g = f"'128 + 64*sin(X/{freq_y*1.5} + T*1.5) + 64*cos(Y/{freq_y} + T*2)'"
    b = f"'128 + 64*sin(X/{freq_y} + T*2.5) + 64*cos(Y/{freq_y*1.5} + T*1.5)'"
    
    return (
        f"nullsrc=s={low_W}x{low_H}:r={FPS}:d={duration},format=yuv420p,"
        f"geq=r={r}:g={g}:b={b},"
        f"scale=w={W}:h={H}:flags=spline"
    )

def get_wave_blur_background_filter(W, H, FPS, duration):
    scale_down = 2
    low_W, low_H = max(1, W // scale_down), max(1, H // scale_down)
    total_frames = int(duration * FPS) if duration > 0 else 1
    
    low_strength = (W * 0.002) / scale_down
    low_density = (W * 0.025) / scale_down
    
    geq = f"p(X,Y+{low_strength}*sin(X/{low_density}+T*2))"

    return (
        f"scale={low_W}:-1,crop={low_W}:{low_H},"
        f"zoompan=z=1:d={total_frames}:s={low_W}x{low_H}:fps={FPS},"
        f"geq='{geq}',"
        f"boxblur={20/scale_down}:{5/scale_down},"
        f"scale={W}:{H}:flags=spline"
    )

def get_color_flow_background_filter(W, H, FPS, duration):
    """
    色彩流动效果：颜色在画面中流动变化。
    """
    scale_down = 4
    low_W, low_H = W // scale_down, H // scale_down
    
    r = f"'128 + 80*sin(X*0.01 + T*1.2) + 40*cos(Y*0.015 + T*0.8)'"
    g = f"'128 + 70*sin(X*0.012 + T*1.0 + 2.1) + 50*cos(Y*0.01 + T*1.1)'"
    b = f"'128 + 60*sin(X*0.008 + T*0.9 + 4.2) + 60*cos(Y*0.012 + T*1.3)'"
    
    return (
        f"nullsrc=s={low_W}x{low_H}:r={FPS}:d={duration},format=yuv420p,"
        f"geq=r={r}:g={g}:b={b},"
        f"scale={W}:{H}:flags=spline"
    )


# --- 歌词动画 (全比例化 + 动态布局) ---

@lru_cache(maxsize=128)
def _clean_text(text: str) -> str:
    return text.replace("'", "’").replace(":", "：").replace("%", "％").replace(',', r'\,')

def get_slide_and_fade_text_animation(lyrics_with_ends, font_primary_escaped, font_size_primary, color_primary_ffmpeg,
                                      font_secondary_escaped, font_size_secondary, color_secondary_ffmpeg,
                                      outline_color_ffmpeg, outline_width, W=1920, H=1080, layout_split=0.382):
    """
    淡入淡出动画。
    layout_split: 左侧区域占比 (0.0-1.0)，文字将在右侧区域居中。
    """
    FADE_DURATION = 0.5
    SLIDE_DISTANCE = H * 0.025
    
    scale_factor = H / 1080.0
    real_fs_p = int(font_size_primary * scale_factor)
    real_fs_s = int(font_size_secondary * scale_factor)
    real_outline = max(1, int(outline_width * scale_factor))
    
    GAP = (real_fs_p * 0.2) + (H * 0.06)

    # 计算右侧区域的中心 X 坐标
    # 右侧起始X = W * layout_split
    # 右侧宽度 = W * (1 - layout_split)
    # 中心 = 起始X + 宽度/2
    # 简化公式: W * (1 + layout_split) / 2
    # 但 FFmpeg 中 drawtext 的 x 是左上角，若要居中需要减去 text_w/2
    
    # 公式：(W * layout_split) + (W * (1 - layout_split) - text_w) / 2
    x_pos = f"({W}*{layout_split}) + ({W}*(1-{layout_split}) - text_w)/2"

    drawtext_filters = []
    for start, end, primary_text, secondary_text in lyrics_with_ends:
        enable = f"'between(t,{start},{end})'"
        alpha = f"'if(lt(t,{start}+{FADE_DURATION}),(t-{start})/{FADE_DURATION},if(gt(t,{end}-{FADE_DURATION}),({end}-t)/{FADE_DURATION},1))'"
        y_off = f"if(lt(t,{start}+{FADE_DURATION}),({FADE_DURATION}-(t-{start}))/{FADE_DURATION}*{SLIDE_DISTANCE},0)"
        
        if primary_text:
            y_prim = f"'H/2 - {real_fs_p} - ({GAP}/2) - ({y_off})'"
            drawtext_filters.append(
                f"drawtext=fontfile='{font_primary_escaped}':text='{_clean_text(primary_text)}':"
                f"fontsize={real_fs_p}:fontcolor={color_primary_ffmpeg}:"
                f"bordercolor={outline_color_ffmpeg}:borderw={real_outline}:"
                f"x={x_pos}:y={y_prim}:alpha={alpha}:enable={enable}"
            )
        if secondary_text:
            y_sec = f"'H/2 + ({GAP}/2) - ({y_off})'"
            drawtext_filters.append(
                f"drawtext=fontfile='{font_secondary_escaped}':text='{_clean_text(secondary_text)}':"
                f"fontsize={real_fs_s}:fontcolor={color_secondary_ffmpeg}:"
                f"bordercolor={outline_color_ffmpeg}:borderw={real_outline}:"
                f"x={x_pos}:y={y_sec}:alpha={alpha}:enable={enable}"
            )

    return ",".join(drawtext_filters)

def get_list_text_animation(lyrics_with_ends, font_primary_escaped, font_size_primary, color_primary_ffmpeg,
                            font_secondary_escaped, font_size_secondary, color_secondary_ffmpeg,
                            outline_color_ffmpeg, outline_width, W=1920, H=1080, layout_split=0.382):
    """
    滚动列表动画 (Tall Canvas 版 + 动态布局)。
    """
    if not lyrics_with_ends: return ""

    # 1. 比例化参数
    scale_factor = H / 1080.0
    real_fs_p = int(font_size_primary * scale_factor)
    real_fs_s = int(font_size_secondary * scale_factor)
    real_outline = max(1, int(outline_width * scale_factor))
    
    GAP_BETWEEN_LINES = H * 0.05
    line_height = real_fs_p + real_fs_s + GAP_BETWEEN_LINES
    INNER_GAP = real_fs_p * 0.2 + (10 * scale_factor)
    
    # 2. 画布高度
    total_list_height = len(lyrics_with_ends) * line_height
    canvas_height = int(H + total_list_height + H) 
    
    # 3. 滚动表达式 (线性累加)
    TRANSITION_DURATION = 0.35
    scroll_terms = ["0"]
    for j in range(1, len(lyrics_with_ends)):
        start_j = lyrics_with_ends[j][0]
        term = f"({line_height} * (1-cos(clip((t-{start_j})/{TRANSITION_DURATION},0,1)*3.14159265))/2)"
        scroll_terms.append(term)
    
    scroll_sum_expr = "+".join(scroll_terms)
    
    buffer_y = int(H)
    initial_crop_y = buffer_y - (H / 2)
    final_crop_y_expr = f"{initial_crop_y} + ({scroll_sum_expr})"

    # 4. 构建滤镜链
    chain = [f"null[ignore_default_input]"]
    chain.append(f"color=s={W}x{canvas_height}:c=black@0.0:r=60[tall_canvas]")
    
    last_stream = "[tall_canvas]"
    # 动态布局 X 坐标
    x_pos = f"({W}*{layout_split}) + ({W}*(1-{layout_split}) - text_w)/2"
    
    for i, (start, end, p_text, s_text) in enumerate(lyrics_with_ends):
        base_y = int(buffer_y + i * line_height)
        sec_y = int(base_y + real_fs_p + INNER_GAP)
        
        next_start = lyrics_with_ends[i+1][0] if i+1 < len(lyrics_with_ends) else end + 999
        is_active = f"between(t,{start},{next_start})"
        alpha_p = f"if({is_active}, 1, 0.6)"
        alpha_s = f"if({is_active}, 0.9, 0.6)"
        
        if p_text:
            chain.append(
                f"{last_stream}drawtext=fontfile='{font_primary_escaped}':text='{_clean_text(p_text)}':"
                f"fontsize={real_fs_p}:fontcolor={color_primary_ffmpeg}:"
                f"bordercolor={outline_color_ffmpeg}:borderw={real_outline}:"
                f"x={x_pos}:y={base_y}:alpha='{alpha_p}'[txt_{i}_a]"
            )
            last_stream = f"[txt_{i}_a]"
            
        if s_text:
            chain.append(
                f"{last_stream}drawtext=fontfile='{font_secondary_escaped}':text='{_clean_text(s_text)}':"
                f"fontsize={real_fs_s}:fontcolor={color_secondary_ffmpeg}:"
                f"bordercolor={outline_color_ffmpeg}:borderw={max(1, real_outline//2)}:"
                f"x={x_pos}:y={sec_y}:alpha='{alpha_s}'[txt_{i}_b]"
            )
            last_stream = f"[txt_{i}_b]"

    chain.append(f"{last_stream}crop=x=0:y='{final_crop_y_expr}':w={W}:h={H}[scrolling_layer]")
    
    full_filter_str = ";".join(chain).replace("null[ignore_default_input]", "null[bg_ref]")
    full_filter_str += f";[bg_ref][scrolling_layer]overlay=x=0:y=0"
    
    return full_filter_str

def get_bounce_text_animation(lyrics_with_ends, font_primary_escaped, font_size_primary, color_primary_ffmpeg,
                             font_secondary_escaped, font_size_secondary, color_secondary_ffmpeg,
                             outline_color_ffmpeg, outline_width, W=1920, H=1080, layout_split=0.382):
    """
    弹跳入场动画：歌词以弹跳动画方式入场。
    使用弹性缓动函数模拟弹跳效果。
    """
    FADE_DURATION = 0.6
    BOUNCE_DURATION = 0.5
    
    scale_factor = H / 1080.0
    real_fs_p = int(font_size_primary * scale_factor)
    real_fs_s = int(font_size_secondary * scale_factor)
    real_outline = max(1, int(outline_width * scale_factor))
    
    GAP = (real_fs_p * 0.2) + (H * 0.06)
    x_pos = f"({W}*{layout_split}) + ({W}*(1-{layout_split}) - text_w)/2"

    drawtext_filters = []
    for start, end, primary_text, secondary_text in lyrics_with_ends:
        enable = f"'between(t,{start},{end})'"
        
        t_rel = f"clip((t-{start})/{BOUNCE_DURATION},0,1)"
        bounce = f"(1 - cos({t_rel}*3.14159265) * exp(-{t_rel}*3))"
        
        alpha = f"'if(lt(t,{start}+{FADE_DURATION}),(t-{start})/{FADE_DURATION},if(gt(t,{end}-{FADE_DURATION}),({end}-t)/{FADE_DURATION},1))'"
        
        y_off = f"(1-{bounce})*{H*0.1}"
        
        if primary_text:
            y_prim = f"'H/2 - {real_fs_p} - ({GAP}/2) - ({y_off})'"
            drawtext_filters.append(
                f"drawtext=fontfile='{font_primary_escaped}':text='{_clean_text(primary_text)}':"
                f"fontsize={real_fs_p}:fontcolor={color_primary_ffmpeg}:"
                f"bordercolor={outline_color_ffmpeg}:borderw={real_outline}:"
                f"x={x_pos}:y={y_prim}:alpha={alpha}:enable={enable}"
            )
        if secondary_text:
            y_sec = f"'H/2 + ({GAP}/2) - ({y_off})'"
            drawtext_filters.append(
                f"drawtext=fontfile='{font_secondary_escaped}':text='{_clean_text(secondary_text)}':"
                f"fontsize={real_fs_s}:fontcolor={color_secondary_ffmpeg}:"
                f"bordercolor={outline_color_ffmpeg}:borderw={real_outline}:"
                f"x={x_pos}:y={y_sec}:alpha={alpha}:enable={enable}"
            )

    return ",".join(drawtext_filters)

def get_scale_pulse_text_animation(lyrics_with_ends, font_primary_escaped, font_size_primary, color_primary_ffmpeg,
                                   font_secondary_escaped, font_size_secondary, color_secondary_ffmpeg,
                                   outline_color_ffmpeg, outline_width, W=1920, H=1080, layout_split=0.382):
    """
    缩放脉冲动画：歌词入场时带有缩放效果。
    由于 FFmpeg drawtext 不支持动态字号，使用 alpha 和位移模拟效果。
    """
    FADE_DURATION = 0.5
    SCALE_DURATION = 0.4
    
    scale_factor = H / 1080.0
    real_fs_p = int(font_size_primary * scale_factor)
    real_fs_s = int(font_size_secondary * scale_factor)
    real_outline = max(1, int(outline_width * scale_factor))
    
    GAP = (real_fs_p * 0.2) + (H * 0.06)
    x_pos = f"({W}*{layout_split}) + ({W}*(1-{layout_split}) - text_w)/2"

    drawtext_filters = []
    for start, end, primary_text, secondary_text in lyrics_with_ends:
        enable = f"'between(t,{start},{end})'"
        
        t_rel = f"clip((t-{start})/{SCALE_DURATION},0,1)"
        scale_effect = f"(1 - (1-{t_rel})*0.3)"
        
        alpha = f"'if(lt(t,{start}+{FADE_DURATION}),(t-{start})/{FADE_DURATION},if(gt(t,{end}-{FADE_DURATION}),({end}-t)/{FADE_DURATION},1))'"
        
        if primary_text:
            y_prim = f"'H/2 - {real_fs_p} - ({GAP}/2)'"
            drawtext_filters.append(
                f"drawtext=fontfile='{font_primary_escaped}':text='{_clean_text(primary_text)}':"
                f"fontsize={real_fs_p}:fontcolor={color_primary_ffmpeg}:"
                f"bordercolor={outline_color_ffmpeg}:borderw={real_outline}:"
                f"x={x_pos}:y={y_prim}:alpha={alpha}:enable={enable}"
            )
        if secondary_text:
            y_sec = f"'H/2 + ({GAP}/2)'"
            drawtext_filters.append(
                f"drawtext=fontfile='{font_secondary_escaped}':text='{_clean_text(secondary_text)}':"
                f"fontsize={real_fs_s}:fontcolor={color_secondary_ffmpeg}:"
                f"bordercolor={outline_color_ffmpeg}:borderw={real_outline}:"
                f"x={x_pos}:y={y_sec}:alpha={alpha}:enable={enable}"
            )

    return ",".join(drawtext_filters)

# --- 封面动画 ---

def get_static_cover_animation_filter(duration, fps=60, W=1920, H=1080):
    FPS = fps
    frames = int(duration * FPS) if duration > 1 else 1
    # 基于最小边按比例缩放封面
    img_size = int(min(W, H) * 0.45)
    refl_h = int(img_size * 0.4)
    canvas_h = img_size + refl_h
    
    # 使用生成器表达式避免创建中间列表
    return ",".join((
        f"scale={img_size}:{img_size},setsar=1,split=2[m][r_src]",
        f"color=c=black@0.0:s={img_size}x{canvas_h}:r={FPS}:d={duration}[bg]",
        f"[r_src]vflip,crop=w={img_size}:h={refl_h}:x=0:y=0,format=yuva444p,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='128*(1-Y/H)',boxblur=3:1[r]",
        f"[bg][m]overlay=0:0[tmp]",
        f"[tmp][r]overlay=0:{img_size}[out]",
        f"[out]zoompan=z=1:d={frames}:s={img_size}x{canvas_h}:fps={FPS}"
    ))

def get_vinyl_record_animation_filter(duration, fps=60, W=1920, H=1080):
    FPS = fps
    frames = max(1, int(duration * FPS))
    rot_speed = (2 * 3.14159) / 8 
    
    final_size = int(min(W, H) * 0.55)
    label_size = int(final_size * 0.625)
    
    ss = 4
    ss_W, ss_H = final_size*ss, final_size*ss
    dx, dy = f"(X-{ss_W/2})", f"(Y-{ss_H/2})"
    dist = f"sqrt({dx}*{dx}+{dy}*{dy})"
    mask = f"255*clip(({ss_W/2}-{dist})/{ss*2},0,1)"
    texture = f"if(lt({dist},{label_size*ss/2}), LUM, min(255, 15+10*sin({dist}*3)))"
    color_expr = f"r='{texture.replace('LUM','r(X,Y)')}':g='{texture.replace('LUM','g(X,Y)')}':b='{texture.replace('LUM','b(X,Y)')}':a='{mask}'"

    return (
        f"split[lbl][bg];"
        f"[lbl]scale={label_size}:{label_size}:flags=bicubic,setsar=1[l];"
        f"[bg]scale={final_size}:{final_size},format=yuva444p,geq=r=0:g=0:b=0:a=255[k];"
        f"[k][l]overlay=(W-w)/2:(H-h)/2[base];"
        f"[base]scale={ss_W}:{ss_H},format=yuva444p,geq={color_expr},"
        f"scale={final_size}:{final_size}:flags=area," 
        f"zoompan=z=1:d={frames}:s={final_size}x{final_size}:fps={FPS},"
        f"rotate=a=t*{rot_speed}:c=none:ow={final_size}:oh={final_size}"
    ).replace(";", ",")


GENERATIVE_BACKGROUND_ANIMATIONS = {"渐变波浪", "动态光斑", "色彩流动", "粒子漂浮"}
BACKGROUND_ANIMATIONS = {
    "静态模糊": get_static_background_filter,
    "渐变波浪": get_gradient_wave_background_filter,
    "波浪模糊": get_wave_blur_background_filter,
    "色彩流动": get_color_flow_background_filter,
}
TEXT_ANIMATIONS = {
    "淡入淡出": get_slide_and_fade_text_animation,
    "滚动列表": get_list_text_animation,
    "弹跳入场": get_bounce_text_animation,
    "缩放脉冲": get_scale_pulse_text_animation,
}
COVER_ANIMATIONS = {
    "静态展示": get_static_cover_animation_filter,
    "唱片旋转": get_vinyl_record_animation_filter,
}