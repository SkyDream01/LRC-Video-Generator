# lrc2video/animations.py
"""
动画效果模块
定义了用于生成视频背景、歌词和专辑封面动画的FFmpeg滤镜函数。
每个函数都接受一个 duration 参数，以便于实现与时间相关的动画。
"""
from functools import lru_cache

# --- 背景动画 ---

def get_static_background_filter(W, H, FPS, duration):
    """
    生成静态、模糊的背景滤镜。
    - scale: 缩放输入图像以匹配宽度，高度自动调整。
    - crop: 裁剪图像以匹配目标分辨率 (W, H)。
    - boxblur: 应用一个盒子模糊效果，参数为 'luma_radius:chroma_radius'。
    - zoompan: 一个技巧，用于将单个图像帧转换为稳定的视频流。
    """
    total_frames = int(duration * FPS) if duration > 0 else 1
    return (
        f"scale={W}:-1,crop={W}:{H},boxblur=20:5,"
        f"zoompan=z=1:d={total_frames}:s={W}x{H}:fps={FPS}"
    )

def get_gradient_wave_background_filter(W, H, FPS, duration):
    """
    生成一个动态的、色彩流动的复杂波浪背景 (性能优化版)。
    通过在低分辨率下生成图案然后将其高质量放大来显著提高性能。
    - nullsrc: 创建一个指定大小、帧率和时长的空白视频源。
    - format: 确保像素格式为 yuv420p，这是视频编码的常用格式。
    - geq: (Generic Expression) 滤镜，用于根据数学表达式为每个像素生成颜色值。
        - r, g, b: 分别代表红色、绿色、蓝色通道的表达式。
        - X, Y: 当前像素的坐标。
        - T: 当前时间（秒）。
        - sin, cos: 用于创建平滑的周期性变化，形成波浪效果。
    - scale: 将低分辨率图像放大到目标尺寸，flags=spline 使用高质量的样条插值算法。
    """
    scale_down_factor = 4  # 缩小因子，值越大，性能越高，但细节可能越少
    low_W, low_H = W // scale_down_factor, H // scale_down_factor
    # 复杂的三角函数组合，创造出流动的色彩
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
    生成基于输入图片的动态波浪模糊背景滤镜（性能优化版）。
    同样使用了低分辨率处理再放大的技巧。
    - geq: 表达式 'p(X, Y + ...)' 表示对像素进行垂直位移，位移量由sin函数决定，
           从而创建垂直的波浪扭曲效果。
        - X/{low_wave_density}: 控制波浪的空间频率（密度）。
        - T*{wave_speed}: 控制波浪的时间频率（速度）。
    """
    scale_down_factor = 2
    low_W, low_H = max(1, W // scale_down_factor), max(1, H // scale_down_factor)
    total_frames = int(duration * FPS) if duration > 0 else 1

    # 波浪参数
    wave_strength = 3     # 波幅大小（像素）
    wave_density = 50     # 波浪密度（值越小越密）
    wave_speed = 2.0      # 波浪速度（值越大越快）

    # 调整参数以适应低分辨率
    low_wave_strength = wave_strength / scale_down_factor
    low_wave_density = wave_density / scale_down_factor
    
    # geq 表达式：p(X, Y) 返回 (X,Y) 处的像素值。这里对 Y 坐标进行正弦扰动。
    geq_expr = f"p(X,Y+{low_wave_strength}*sin(X/{low_wave_density}+T*{wave_speed}))"

    # 模糊参数
    luma_radius, chroma_radius = 20, 5 # 亮度/色度模糊半径
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
def _clean_text(text: str) -> str:
    """清理歌词中的特殊字符以避免FFmpeg表达式错误。"""
    # FFmpeg 的 drawtext 滤镜对某些字符（如 ' : % ,）有特殊含义，需要转义。
    return text.replace("'", "’").replace(":", "：").replace("%", "％").replace(',', r'\,')

def get_slide_and_fade_text_animation(lyrics_with_ends, font_primary_escaped, font_size_primary, color_primary_ffmpeg,
                                      font_secondary_escaped, font_size_secondary, color_secondary_ffmpeg,
                                      outline_color_ffmpeg, outline_width):
    """
    生成歌词滑动和淡入淡出效果的 drawtext 滤镜字符串。
    - drawtext: FFmpeg 的核心文本绘制滤镜。
        - enable='between(t, start, end)': 设置文本仅在指定时间段内可见。
        - alpha='if(...)': 控制透明度。表达式实现了在 FADE_DURATION 内的淡入和淡出。
        - y='... - (y_slide_offset)': 控制Y坐标。y_slide_offset 表达式实现了向上的滑动入场效果。
        - x='(W-text_w)/2': 使文本水平居中。
    """
    FADE_DURATION = 0.5  # 淡入淡出时长（秒）
    SLIDE_DISTANCE = 20  # 滑动距离（像素）
    W, H = 1920, 1080    # 视频分辨率

    drawtext_filters = []
    for start, end, primary_text, secondary_text in lyrics_with_ends:
        enable_expr = f"'between(t,{start},{end})'"
        # 透明度表达式：在开始和结束时淡化
        alpha_expr = f"'if(lt(t,{start}+{FADE_DURATION}),(t-{start})/{FADE_DURATION},if(gt(t,{end}-{FADE_DURATION}),({end}-t)/{FADE_DURATION},1))'"
        # Y坐标偏移表达式：实现从下方滑入的效果
        y_slide_offset = f"if(lt(t,{start}+{FADE_DURATION}),({FADE_DURATION}-(t-{start}))/{FADE_DURATION}*{SLIDE_DISTANCE},0)"
        
        # 黄金比例布局的X坐标
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
    这是一个非常复杂的滤镜，核心思想是：
    1. `highlight_idx_expr`: 计算出当前时间点应该高亮的歌词行索引。
    2. `scroll_y_expr`: 计算出整个歌词列表的垂直滚动偏移量。它使用 `if` 和缓动函数 `(1-cos(...))/2` 来实现平滑的滚动动画。
    3. 循环每一行歌词，为它们生成一个 `drawtext` 滤镜。
        - `y_pos_..._expr`: 计算每一行歌词的Y坐标，它等于基础滚动偏移量 + 行号 * 行高。
        - `is_highlighted_expr`: 判断当前行是否是高亮行。
        - `alpha_fade_expr`: 根据离高亮行的距离，计算透明度，实现上下淡出效果。
        - 根据是否高亮，为同一行主歌词生成两个 `drawtext`，一个高亮样式，一个普通样式，通过 enable 切换。
    """
    W, H = 1920, 1080
    list_line_height = font_size_primary + font_size_secondary + 45
    list_x_pos = f"'(W/2.618) + (W*1.618/2.618 - text_w)/2'"
    TRANSITION_DURATION = 0.35  # 滚动动画时长
    FADE_DISTANCE_LINES = (H * 6 / 8 / 2) / list_line_height * 1.5
    highlight_font_size_primary = int(font_size_primary * 1.1)

    if not lyrics_with_ends: return ""

    # 倒序生成一个嵌套的 if 表达式，用于在 O(logN) 的时间内（FFmpeg内部优化）确定当前高亮行
    highlight_idx_expr = f"{len(lyrics_with_ends) - 1}"
    for j in range(len(lyrics_with_ends) - 2, -1, -1):
        highlight_idx_expr = f"if(lt(t,{lyrics_with_ends[j + 1][0]}),{j},{highlight_idx_expr})"

    # 目标Y坐标函数
    def get_target_y(j):
        return (H / 2.0) - (list_line_height / 2.0) - (max(0, j) * list_line_height)

    # 滚动动画表达式：在每个滚动转换期间，使用缓动函数进行插值
    scroll_y_expr = f"{get_target_y(0)}"
    for j in range(len(lyrics_with_ends)):
        start_j, target_y_j, prev_target_y = lyrics_with_ends[j][0], get_target_y(j), get_target_y(j - 1)
        progress = f"clip((t - {start_j}) / {TRANSITION_DURATION}, 0, 1)"
        smoothed_progress = f"(1-cos({progress}*3.14159265))/2" # Ease-in-out 缓动
        transition_expr = f"({prev_target_y} + ({target_y_j} - {prev_target_y}) * {smoothed_progress})"
        scroll_y_expr = f"if(gte(t,{start_j}),if(lt(t,{start_j}+{TRANSITION_DURATION}),{transition_expr},{target_y_j}),{scroll_y_expr})"

    drawtext_filters = []
    for i, (_, _, primary_text, secondary_text) in enumerate(lyrics_with_ends):
        y_pos_primary_expr = f"({scroll_y_expr}) + ({i} * {list_line_height})"
        y_pos_secondary_expr = f"({scroll_y_expr}) + {font_size_primary} + ({i} * {list_line_height})"
        is_highlighted_expr = f"eq({i},({highlight_idx_expr}))"
        # 距离高亮行越远，越透明
        alpha_fade_expr = f"clip(1-(abs({i}-({highlight_idx_expr})))/{FADE_DISTANCE_LINES},0,1)"

        # 主歌词：为高亮和非高亮状态分别创建 drawtext
        if primary_text:
            clean_primary = _clean_text(primary_text)
            # 高亮状态
            drawtext_filters.append(
                f"drawtext=fontfile='{font_primary_escaped}':text='{clean_primary}':"
                f"fontsize={highlight_font_size_primary}:fontcolor={color_primary_ffmpeg}:"
                f"bordercolor={outline_color_ffmpeg}:borderw=2:x={list_x_pos}:"
                f"y='{y_pos_primary_expr}':alpha='{alpha_fade_expr}':enable='{is_highlighted_expr}'"
            )
            # 非高亮状态
            drawtext_filters.append(
                f"drawtext=fontfile='{font_primary_escaped}':text='{clean_primary}':fontsize={font_size_primary}:"
                f"fontcolor={color_secondary_ffmpeg}:bordercolor={outline_color_ffmpeg}:borderw=2:x={list_x_pos}:"
                f"y='{y_pos_primary_expr}':alpha='(0.7 * {alpha_fade_expr})':enable='not({is_highlighted_expr})'"
            )
        # 次要歌词
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
    生成具有柔和倒影的静态封面图滤镜（性能优化版）。
    - split=2: 将输入流（封面图）复制成两份，分别命名为 [main] 和 [refl_src]。
    - color: 创建一个透明的黑色画布 [canvas]。
    - [refl_src]vflip...: 对倒影源进行处理：垂直翻转、裁剪、添加Alpha渐变、模糊。
        - geq a='...': 创建从上到下（Y从0到H）的线性渐变透明度。
        - boxblur: 使用性能更好的盒子模糊。
    - overlay: 将主图 [main] 和倒影 [refl] 叠加到画布 [canvas] 上。
    """
    FPS = 60
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


def get_vinyl_record_animation_filter(duration):
    """
    生成一个圆形、旋转的仿黑胶唱片动画。
    - geq a='...': 使用 `sqrt(pow(X-W/2,2)+pow(Y-H/2,2))` 计算像素到中心的距离，
      通过与半径比较，创造出圆形遮罩，并带有平滑的边缘。
    - geq r/g/b='...': 模拟唱片上的纹理和高光。
        - 播放区纹理: `15 + 10*sin(...)` 创建细密的环形纹理。
        - 引入轨纹理: `if(gte(...) ...)` 在特定半径范围内创建更粗的纹理。
        - 高光: `60*pow(...)` 模拟一个光源照射在唱片上形成的高光区域。
    - rotate: 旋转动画，`a=t*...` 表示旋转角度随时间线性变化。
    """
    FPS = 60
    total_frames = max(1, int(duration * FPS))
    rotation_speed_per_sec = (2 * 3.1415926535) / 10  # 每10秒转一圈

    record_size = 640
    label_size = 400

    # 为抗锯齿进行超采样
    ss = 8
    W, H = record_size * ss, record_size * ss
    R = W / 2

    # 1. 准备输入：将封面图缩放成标签，并叠加到一个黑色背景上
    prepare_inputs = (
        f"split[label_src][canvas_src];"
        f"[label_src]scale={label_size}:{label_size}:flags=lanczos,setsar=1[label];"
        f"[canvas_src]scale={record_size}:{record_size},format=yuva444p,lutrgb=r=0:g=0:b=0:a=255[black_canvas];"
        f"[black_canvas][label]overlay=(main_w-overlay_w)/2:(main_h-overlay_h)/2[static_record];"
    )

    # 2. 对合成好的图像应用效果
    label_radius_ss = (label_size / 2) * ss
    R_label_outer2 = label_radius_ss**2
    
    # 距离中心的距离表达式
    DX, DY = f'(X-{W/2})', f'(Y-{H/2})'
    D2 = f'(pow({DX},2)+pow({DY},2))'
    Dist = f'sqrt({D2})'

    # Alpha 表达式，用于创建平滑边缘的圆形遮罩
    smooth_width = ss * 1.5
    alpha_expr = f"'255 * clip(({R} - {Dist}) / {smooth_width}, 0, 1)'"

    # 高光表达式
    highlight_D2 = f'(pow(X-{W*0.3},2)+pow(Y-{H*0.3},2))'
    highlight_radius = W * 0.7
    highlight_intensity = f'60*pow(max(0,1-sqrt({highlight_D2})/{highlight_radius}),3)'
    
    # 唱片纹理表达式
    R_lead_in_outer, R_lead_in_inner = R * 0.99, R * 0.93
    playable_groove_texture = f"15 + 10*sin({Dist}*3.5*{ss})"
    lead_in_groove_additive = f"if(gte({Dist},{R_lead_in_inner})*lte({Dist},{R_lead_in_outer}), 30 + 30*st(0,sin({Dist}*45*{ss}-PI/2)), 0)"

    # 颜色表达式：如果是标签区域，使用原始颜色(LUM)，否则应用纹理和高光
    color_expr = (
        f"if(lt({D2},{R_label_outer2}),"
        f"  LUM,"
        f"  min(255, {playable_groove_texture} + {highlight_intensity} + {lead_in_groove_additive})"
        ")"
    )

    # 3. 组合效果并添加旋转动画
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

# --- 定义动画预设字典 ---

# 生成式背景动画（不需要输入图像）
GENERATIVE_BACKGROUND_ANIMATIONS = {"渐变波浪"}

# 所有背景动画
BACKGROUND_ANIMATIONS = {
    "静态模糊": get_static_background_filter,
    "渐变波浪": get_gradient_wave_background_filter,
    "波浪模糊": get_wave_blur_background_filter,  
}

# 歌词动画
TEXT_ANIMATIONS = {
    "淡入淡出": get_slide_and_fade_text_animation,
    "滚动列表": get_list_text_animation,
}

# 封面动画
COVER_ANIMATIONS = {
    "静态展示": get_static_cover_animation_filter,
    "唱片旋转": get_vinyl_record_animation_filter,
}