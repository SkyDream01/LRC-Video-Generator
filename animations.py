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

def get_gradient_wave_background_filter(W, H, FPS, duration):
    """
    生成一个动态的、色彩流动的复杂波浪背景 (性能优化版)。
    通过在低分辨率下生成图案然后将其高质量放大来显著提高性能。
    """
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
    """
    生成基于输入图片的动态波浪模糊背景滤镜（支持密度与速度分离，性能优化版）。
    通过在低分辨率下生成波浪效果然后放大来显著提升性能。
    """
    scale_down_factor = 2  # 缩放因子，降低分辨率以减少计算量
    low_W = max(1, W // scale_down_factor)  # 低分辨率宽度，至少为1
    low_H = max(1, H // scale_down_factor)  # 低分辨率高度，至少为1
    total_frames = int(duration * FPS) if duration > 0 else 1

    # 波浪参数
    wave_strength = 3     # 波幅大小（像素单位）
    wave_density = 50     # 波浪密度（空间周期，像素单位，值越小越密）
    wave_speed = 2.0      # 波浪速度（时间因子，越大动画越快）

    # 调整参数到低分辨率
    low_wave_strength = wave_strength / scale_down_factor
    low_wave_density = wave_density / scale_down_factor

    # geq 表达式：密度和速度分离
    geq_expr = f"p(X,Y+{low_wave_strength}*sin(X/{low_wave_density}+T*{wave_speed}))"

    # 模糊参数
    luma_radius = 20      # 原始亮度模糊半径
    chroma_radius = 5     # 原始色度模糊半径
    low_luma_radius = luma_radius / scale_down_factor
    low_chroma_radius = chroma_radius / scale_down_factor

    return (
        f"scale={low_W}:-1,crop={low_W}:{low_H},"
        f"zoompan=z=1:d={total_frames}:s={low_W}x{low_H}:fps={FPS},"
        f"geq='{geq_expr}',"
        f"boxblur={low_luma_radius}:{low_chroma_radius},"
        f"scale={W}:{H}:flags=spline"
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
                                        outline_color_ffmpeg, outline_width):
    """
    在屏幕左侧生成滚动高亮歌词列表。
    【V2增强版】: 新增缓动滚动、高亮行背景光效和动态缩放。
    """
    W, H = 1920, 1080
    list_line_height = font_size_primary + font_size_secondary + 45
    list_x_pos = f"'(W/2.618) + (W*1.618/2.618 - text_w)/2'"
    TRANSITION_DURATION = 0.35
    FADE_DISTANCE_LINES = (H * 6 / 8 / 2) / list_line_height * 1.5
    
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
                f"fontsize={highlight_font_size_primary}:"
                f"fontcolor={color_primary_ffmpeg}:"
                f"bordercolor={outline_color_ffmpeg}:borderw=2:x={list_x_pos}:"
                f"y='{y_pos_primary_expr}':alpha='{alpha_fade_expr}':enable='{is_highlighted_expr}':"
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
    生成具有柔和倒影的静态封面图滤镜（保留倒影，优化性能版）。
    使用 boxblur 替代 gblur 来提升倒影渲染速度。
    """
    FPS = 60
    total_frames = int(duration * FPS) if duration > 1 else 1
    img_w, img_h = 600, 600
    refl_h = int(img_h * 0.4)
    canvas_h = img_h + refl_h

    # 使用分号`;`构建更清晰的滤镜图，最后替换为逗号`,`
    filter_chains = [
        # 1. 缩放原始输入, 并分割成两路给主图和倒影使用
        f"scale={img_w}:{img_h},setsar=1,split=2[main][refl_src]",
        
        # 2. 创建一个透明的画布作为基础
        f"color=c=black@0.0:s={img_w}x{canvas_h}:r={FPS}:d={duration}[canvas]",

        # 3. 创建倒影: 垂直翻转、裁剪、生成Alpha渐变、进行模糊处理
        #    [性能优化] 使用 boxblur 替代 gblur
        f"[refl_src]vflip,crop=w={img_w}:h={refl_h}:x=0:y=0,format=yuva444p,"
        f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='128*(1-Y/H)',boxblur=3:1[refl]",

        # 4. 组合主图和倒影到画布上
        f"[canvas][main]overlay=x=0:y=0[tmp]",
        f"[tmp][refl]overlay=x=0:y={img_h}[with_refl]",

        # 5. 使用 zoompan 确保输出是稳定的视频流
        f"[with_refl]zoompan=z=1:d={total_frames}:s={img_w}x{canvas_h}:fps={FPS}"
    ]
    
    return ",".join(filter_chains)


def get_vinyl_record_animation_filter(duration):
    """
    生成一个圆形、旋转的仿黑胶唱片动画。（V4 - 抗锯齿优化）
    此版本通过在Alpha通道上实现边缘平滑来解决“毛边”问题。
    """
    FPS = 60
    total_frames = max(1, int(duration * FPS))
    rotation_speed_per_sec = (2 * 3.1415926535) / 10

    ss = 8
    orig_W, orig_H = 640, 640
    W, H = orig_W * ss, orig_H * ss
    R = W / 2

    GOLDEN_RATIO = 1.618034
    
    R_label_outer2 = (R / GOLDEN_RATIO)**2
    label_radius = R_label_outer2**0.5
    R_press_inner2 = (label_radius * 0.98)**2
    R_press_outer2 = (label_radius * 1.02)**2
    R_separator_outer2 = (label_radius * 1.07)**2
    R_lead_in_outer = R * 0.99
    R_lead_in_inner = R * 0.93

    DX, DY = f'(X-{W/2})', f'(Y-{H/2})'
    D2 = f'(pow({DX},2)+pow({DY},2))'
    Dist = f'sqrt({D2})'
    
    smooth_width = ss * 1.5 
    alpha_expr = f"'255 * clip(({R} - {Dist}) / {smooth_width}, 0, 1)'"


    highlight_D2 = f'(pow(X-{W*0.3},2)+pow(Y-{H*0.3},2))'
    highlight_radius = W * 0.7
    highlight_intensity = f'60*pow(max(0,1-sqrt({highlight_D2})/{highlight_radius}),3)'
    
    label_pressing_ring_darken = f"if(lte({D2},{R_press_outer2})*gte({D2},{R_press_inner2}), 0.85*LUM, LUM)"

    separator_texture = "5"
    playable_groove_texture = f"15 + 10*sin({Dist}*3.5*{ss})"
    lead_in_groove_additive = f"if(gte({Dist},{R_lead_in_inner})*lte({Dist},{R_lead_in_outer}), 30 + 30*st(0,sin({Dist}*45*{ss}-PI/2)), 0)"

    color_expr = (
        f"if(lt({D2},{R_label_outer2}),"
            f"  {label_pressing_ring_darken},"
        f"  if(lt({D2},{R_separator_outer2}),"
            f"      min(255, {separator_texture} + {highlight_intensity}),"
        f"      min(255, {playable_groove_texture} + {highlight_intensity} + {lead_in_groove_additive})"
        "))"
    )

    return (
        f"scale=w={W}:h={H},setsar=1,format=yuva444p,"
        f"geq="
        f"r='{color_expr.replace('LUM', 'r(X,Y)')}':"
        f"g='{color_expr.replace('LUM', 'g(X,Y)')}':"
        f"b='{color_expr.replace('LUM', 'b(X,Y)')}':"
        f"a={alpha_expr},"
        f"scale=w={orig_W}:h={orig_H}:flags=lanczos,"
        f"zoompan=z=1:d={total_frames}:s={orig_W}x{orig_H}:fps={FPS},"
        f"rotate=a=t*{rotation_speed_per_sec}:c=none:ow={orig_W}:oh={orig_H}"
    )

# --- 定义动画预设字典 ---

GENERATIVE_BACKGROUND_ANIMATIONS = {"渐变波浪"}

BACKGROUND_ANIMATIONS = {
    "静态模糊": get_static_background_filter,
    "渐变波浪": get_gradient_wave_background_filter,
    "波浪模糊": get_wave_blur_background_filter,  # 新增波浪模糊背景
}

TEXT_ANIMATIONS = {
    "淡入淡出": get_slide_and_fade_text_animation,
    "滚动列表": get_list_text_animation,
}

COVER_ANIMATIONS = {
    "静态展示": get_static_cover_animation_filter,
    "唱片旋转": get_vinyl_record_animation_filter,
}