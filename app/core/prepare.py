"""prepare 阶段图层资源光栅化（Pillow/NumPy，仅资源/参数变化时运行）。

产出紧 bbox RGBA 位图与布局矩形；禁止按 1920 宽全幅画布缓存歌词。
本模块零 Qt 依赖，可被 pytest 直接测。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .color import RGB
from .project import FONT_EXTS, scan_fonts

# 背景降采样倍率（模糊先缩小再放大，约 16× 提速）
BG_DOWNSAMPLE = 4
# 唱片/封面贴图超采样倍率（抗锯齿）
TEXTURE_SS = 2
# 超宽歌词允许的最小字号比例
WRAP_MIN_SCALE = 0.5
WRAP_MAX_LINES = 2
WRAP_LINE_GAP_RATIO = 0.18

_WINDOWS_FONT_CANDIDATES = ("msyh.ttc", "simhei.ttf", "arial.ttf")
_WINDOWS_FONTS_DIR = Path("C:/Windows/Fonts")


@dataclass
class PreparedBitmap:
    """紧 bbox RGBA 位图。origin 为相对锚点的 (ox, oy) 偏移（锚点默认 = 行布局点）。"""

    pixels: np.ndarray  # (H, W, 4) uint8
    origin: tuple[int, int] = (0, 0)

    @property
    def width(self) -> int:
        return self.pixels.shape[1]

    @property
    def height(self) -> int:
        return self.pixels.shape[0]


class FontCache:
    """字体缓存：font/ 目录优先，缺省回退系统 CJK 字体 → Pillow 内置字体。"""

    def __init__(self, font_dir: str | Path | None = None) -> None:
        self.font_dir = Path(font_dir) if font_dir else None
        self._cache: dict[
            tuple[str, int], ImageFont.FreeTypeFont | ImageFont.ImageFont
        ] = {}

    def available_fonts(self) -> list[str]:
        return scan_fonts(self.font_dir) if self.font_dir else []

    def resolve_path(self, name: str | None) -> str | None:
        """按名解析字体文件路径；未命中返回 None（由 get() 继续回退）。"""
        if not name:
            return None
        if self.font_dir:
            candidate = self.font_dir / name
            if candidate.suffix.lower() in FONT_EXTS and candidate.is_file():
                return str(candidate)
        return None

    def get(
        self, name: str | None, size: int
    ) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        """取字体。解析顺序：指定名 → font/ 首个字体 → 系统 CJK → Pillow 内置。"""
        key = (name or "", size)
        if key in self._cache:
            return self._cache[key]
        font = self._load(name, size)
        self._cache[key] = font
        return font

    def _load(self, name: str | None, size: int):
        path = self.resolve_path(name)
        if path is None:
            fonts = self.available_fonts()
            if fonts and self.font_dir is not None:
                path = str(self.font_dir / fonts[0])
        if path is None:
            for candidate in _WINDOWS_FONT_CANDIDATES:
                if (_WINDOWS_FONTS_DIR / candidate).is_file():
                    path = str(_WINDOWS_FONTS_DIR / candidate)
                    break
        if path is not None:
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                pass
        return ImageFont.load_default(size)


def rasterize_text(
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    color: RGB,
    stroke_color: RGB,
    stroke_width: int = 0,
) -> PreparedBitmap:
    """渲染单段文本为紧 bbox RGBA 位图，origin 水平居中（ox=-w/2, oy=0）。"""
    if not text:
        return PreparedBitmap(pixels=np.zeros((0, 0, 4), dtype=np.uint8), origin=(0, 0))
    left, top, right, bottom = font.getbbox(text, stroke_width=stroke_width)
    w = max(1, round(right - left))
    h = max(1, round(bottom - top))
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.text(
        (-left, -top),
        text,
        font=font,
        fill=color,
        stroke_width=stroke_width,
        stroke_fill=stroke_color,
    )
    alpha_bbox = img.getchannel("A").getbbox()
    if alpha_bbox:
        img = img.crop(alpha_bbox)
    pixels = np.asarray(img, dtype=np.uint8)
    return PreparedBitmap(pixels=pixels, origin=(-pixels.shape[1] // 2, 0))


def _text_width(font, text: str, stroke_width: int) -> float:
    bbox = font.getbbox(text, stroke_width=stroke_width)
    return bbox[2] - bbox[0]


def layout_text(
    text: str,
    font_cache: FontCache,
    font_name: str | None,
    size: int,
    color: RGB,
    stroke_color: RGB,
    stroke_width: int,
    max_width: float,
) -> list[PreparedBitmap]:
    """超宽策略：先缩字号适配宽度；仍溢出换行（最多 2 行）；再溢出截断加省略号。

    返回各段位图，origin 相对行锚点（水平居中，oy 逐段累计）。
    """
    text = text.strip()
    if not text:
        return []
    font = font_cache.get(font_name, size)
    if _text_width(font, text, stroke_width) <= max_width:
        seg = rasterize_text(text, font, color, stroke_color, stroke_width)
        return [seg]

    # 1) 缩小字号
    min_size = max(16, round(size * WRAP_MIN_SCALE))
    fit_size = size
    while fit_size > min_size:
        fit_size -= 2
        font = font_cache.get(font_name, fit_size)
        if _text_width(font, text, stroke_width) <= max_width:
            return [rasterize_text(text, font, color, stroke_color, stroke_width)]

    # 2) 换行（最多 2 行），逐行压缩字号直到两行都放得下或到达最小字号
    while fit_size >= min_size:
        font = font_cache.get(font_name, fit_size)
        lines = _wrap_two_lines(text, font, stroke_width, max_width)
        if lines is not None and all(
            _text_width(font, seg, stroke_width) <= max_width for seg in lines
        ):
            return _stack_segments(
                [
                    rasterize_text(seg, font, color, stroke_color, stroke_width)
                    for seg in lines
                ],
                fit_size,
            )
        if lines is not None and all(
            _text_width(font, seg, stroke_width) <= max_width
            for seg in lines[:WRAP_MAX_LINES]
        ):
            break
        fit_size -= 2

    # 3) 最小字号下仍溢出：两行 + 省略号截断
    font = font_cache.get(font_name, max(min_size, 16))
    lines = _wrap_two_lines(text, font, stroke_width, max_width) or [text]
    if len(lines) > WRAP_MAX_LINES:
        lines = lines[:WRAP_MAX_LINES]
    lines[-1] = _ellipsis_clip(lines[-1], font, stroke_width, max_width)
    return _stack_segments(
        [rasterize_text(seg, font, color, stroke_color, stroke_width) for seg in lines],
        fit_size,
    )


def _wrap_two_lines(
    text: str, font, stroke_width: int, max_width: float
) -> list[str] | None:
    """贪心换行为最多 2 行；一个字符都放不下时返回 None。"""
    if _text_width(font, text[0], stroke_width) > max_width:
        return None
    words = (
        text.split(" ") if " " in text else list(text)
    )  # 空格分词（西文），否则逐字（CJK）
    lines: list[str] = []
    cur = ""
    for word in words:
        trial = f"{cur} {word}".strip() if cur else word
        if _text_width(font, trial, stroke_width) <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
            if len(lines) >= WRAP_MAX_LINES:
                break
    if len(lines) < WRAP_MAX_LINES and cur:
        lines.append(cur)
    if not lines:
        return None
    if len(lines) > WRAP_MAX_LINES:
        # 贪心提前 break 时剩余内容并入最后一行（由调用方截断兜底）
        lines = lines[:WRAP_MAX_LINES]
    return lines


def _ellipsis_clip(text: str, font, stroke_width: int, max_width: float) -> str:
    if _text_width(font, text, stroke_width) <= max_width:
        return text
    out = text
    while out and _text_width(font, out + "…", stroke_width) > max_width:
        out = out[:-1]
    return out + "…"


def _stack_segments(segs: list[PreparedBitmap], size: int) -> list[PreparedBitmap]:
    """把多段位图的 origin 调整为相对行锚点（水平居中、垂直累计行距）。"""
    gap = round(size * WRAP_LINE_GAP_RATIO)
    out: list[PreparedBitmap] = []
    y_offset = 0
    for seg in segs:
        out.append(
            PreparedBitmap(pixels=seg.pixels, origin=(-seg.width // 2, y_offset))
        )
        y_offset += seg.height + gap
    return out


# ---------------------------------------------------------------- 背景位图


def cover_fill_resize(img: Image.Image, w: int, h: int) -> Image.Image:
    """等比放大到覆盖 (w, h) 后居中裁剪。"""
    src = img.convert("RGB")
    iw, ih = src.size
    scale = max(w / iw, h / ih)
    nw, nh = max(w, round(iw * scale)), max(h, round(ih * scale))
    resized = src.resize((nw, nh), Image.Resampling.LANCZOS)
    x = (nw - w) // 2
    y = (nh - h) // 2
    return resized.crop((x, y, x + w, y + h))


def blur_to_size(img: Image.Image, w: int, h: int, radius: float = 8.0) -> np.ndarray:
    """高斯模糊背景：先缩小 BG_DOWNSAMPLE 倍模糊再放大（约 16× 提速）。返回 (h, w, 3) uint8。"""
    qw, qh = max(1, w // BG_DOWNSAMPLE), max(1, h // BG_DOWNSAMPLE)
    small = cover_fill_resize(img, qw, qh).filter(ImageFilter.GaussianBlur(radius))
    big = small.resize((w, h), Image.Resampling.BILINEAR)
    return np.asarray(big, dtype=np.uint8)


def make_static_blur_bg(
    source: Image.Image | None, w: int, h: int, base_color: RGB = (24, 26, 34)
) -> np.ndarray:
    """静态模糊背景：源图 cover-fill + 模糊；无源图时用基础色纯色。"""
    if source is None:
        arr = np.empty((h, w, 3), dtype=np.uint8)
        arr[:, :] = base_color
        return arr
    return blur_to_size(source, w, h)


def make_gradient_wave_bg(primary: RGB, secondary: RGB, w: int, h: int) -> np.ndarray:
    """可平铺渐变波浪底图：2 个水平周期、1/4 分辨率。返回 (h/Q, 2w/Q, 3) uint8。"""
    qw, qh = max(2, 2 * w // BG_DOWNSAMPLE), max(2, h // BG_DOWNSAMPLE)
    period = qw / 2.0  # 位图恰好两个周期 → 水平可平铺
    y = (np.arange(qh, dtype=np.float64) + 0.5) / qh
    x = np.arange(qw, dtype=np.float64)
    # 垂直渐变：主色(上下) → 辅色(中部)，三角形权重保证上下闭合
    tri = 1.0 - np.abs(2.0 * y - 1.0)
    top = np.asarray(primary, dtype=np.float64)
    bot = np.asarray(secondary, dtype=np.float64)
    grad = top[None, :] * (1.0 - tri)[:, None] + bot[None, :] * tri[:, None]  # (qh, 3)
    # 波浪亮度带：依赖 x mod period（水平周期）与 y，产生流动感
    phase = 2.0 * np.pi * (x[None, :] / period) + 4.0 * np.pi * y[:, None]
    band = 0.10 * np.sin(phase)  # (qh, qw)
    arr = np.clip(
        grad[:, None, :] * (1.0 + band[..., None]) + band[..., None] * 18.0, 0, 255
    )
    return arr.astype(np.uint8)


def make_wave_blur_bg(
    source: Image.Image | None,
    w: int,
    h: int,
    amp_px: float,
    base_color: RGB = (24, 26, 34),
) -> np.ndarray:
    """波浪模糊底图：高度 = h + 2·amp_px（上下留振幅余量），1/4 处理后放大。"""
    amp = max(1, round(amp_px))
    total_h = h + 2 * amp
    if source is None:
        arr = np.empty((total_h, w, 3), dtype=np.uint8)
        arr[:, :] = base_color
        return arr
    return blur_to_size(source, w, total_h, radius=10.0)


# ---------------------------------------------------------------- 封面 / 唱片贴图


def _circular_feather_mask(size: int, feather_px: float = 1.5) -> Image.Image:
    ss = size * TEXTURE_SS
    mask = Image.new("L", (ss, ss), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((feather_px, feather_px, ss - feather_px, ss - feather_px), fill=255)
    return mask.resize((size, size), Image.Resampling.LANCZOS)


def make_cover_texture(
    cover: Image.Image, size: int, corner_radius: int = 12
) -> PreparedBitmap:
    """封面方形贴图（2× 超采样 + 圆角），紧贴 size×size。"""
    ss = size * TEXTURE_SS
    face = cover_fill_resize(cover, ss, ss).convert("RGBA")
    mask = Image.new("L", (ss, ss), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, ss - 1, ss - 1), radius=corner_radius * TEXTURE_SS, fill=255
    )
    face.putalpha(mask)
    face = face.resize((size, size), Image.Resampling.LANCZOS)
    return PreparedBitmap(pixels=np.asarray(face, dtype=np.uint8))


def make_disc_texture(
    cover: Image.Image, size: int, grooves: int = 90
) -> PreparedBitmap:
    """黑胶唱片贴图：封面圆标 + 唱纹 + 高光，2× 超采样。"""
    ss = size * TEXTURE_SS
    n = np.arange(ss, dtype=np.float64)
    xx, yy = np.meshgrid(n, n)
    cx = cy = (ss - 1) / 2.0
    r = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    r_max = ss / 2.0

    # 唱纹底色：深灰 + 径向细纹理
    groove = 0.5 + 0.5 * np.sin(r / ss * 2.0 * np.pi * grooves)
    base = 34.0 + groove * 14.0
    disc = np.dstack([base, base, base + 4.0])

    # 封面圆标（半径 0.36·ss），圆形掩码内粘贴
    label_r = 0.36 * ss
    label_size = round(label_r * 2)
    label_img = cover_fill_resize(cover, label_size, label_size).convert("RGB")
    label_arr = np.asarray(label_img, dtype=np.float64)
    y0 = round(cy - label_r)
    x0 = round(cx - label_r)
    region = disc[y0 : y0 + label_size, x0 : x0 + label_size]
    label_mask = r[y0 : y0 + label_size, x0 : x0 + label_size] <= label_r
    region[label_mask] = label_arr[label_mask]

    # 高光：左上椭圆径向渐变
    hx, hy = 0.34 * ss, 0.30 * ss
    hd = np.sqrt((xx - hx) ** 2 + (yy - hy) ** 2) / (1.05 * ss)
    sheen = np.clip(1.0 - hd, 0.0, 1.0) ** 2 * 0.38
    disc = disc + sheen[..., None] * (255.0 - disc)

    # 圆形 alpha（边缘羽化）
    alpha = np.clip((r_max - r) / (2.0 * TEXTURE_SS), 0.0, 1.0) * 255.0
    rgba = np.dstack([np.clip(disc, 0, 255), alpha]).astype(np.uint8)
    img = Image.fromarray(rgba, "RGBA").resize((size, size), Image.Resampling.LANCZOS)
    return PreparedBitmap(pixels=np.asarray(img, dtype=np.uint8))


def make_reflection(
    texture: np.ndarray, height_ratio: float = 0.32, alpha0: float = 0.32
) -> np.ndarray:
    """垂直翻转贴图并做线性 alpha 渐隐，生成倒影位图。"""
    src = texture[::-1]
    h, w = src.shape[:2]
    refl_h = max(1, round(h * height_ratio))
    img = Image.fromarray(src, "RGBA").resize((w, refl_h), Image.Resampling.BILINEAR)
    arr = np.asarray(img).copy()
    # 渐隐系数用 0-1 分数刻度：新 alpha = 原 alpha × 系数（系数 ≤ alpha0）
    ramp = (1.0 - (np.arange(refl_h, dtype=np.float64) + 0.5) / refl_h) * alpha0
    arr[..., 3] = (arr[..., 3].astype(np.float64) * ramp[:, None]).astype(np.uint8)
    return arr.astype(np.uint8)


def make_reflection_bitmap(
    texture: PreparedBitmap, height_ratio: float = 0.32, alpha0: float = 0.32
) -> PreparedBitmap:
    return PreparedBitmap(
        pixels=make_reflection(texture.pixels, height_ratio, alpha0), origin=(0, 0)
    )
