"""RenderContext 构建与布局计算：把工程参数、媒体资产、取色结果组装为一次渲染的快照。

动画类不直接读文件——所有 IO 都在 build_context 完成。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from PIL import Image

from .color import (
    RGB,
    Palette,
    extract_palette,
    hex_to_rgb,
    palette_from_manual,
)
from .encoder import audio_duration, read_audio_meta
from .lrc import LrcDocument, LyricLine, parse_lrc
from .prepare import FontCache, cover_fill_resize
from .project import (
    KProj,
    resolve_media,
)
from .timeline import line_intervals

# 应用根目录（font/ 所在）
APP_ROOT = Path(__file__).resolve().parents[2]

# 无音频时按 LRC 最后一行 + 兜底时长估算
_NO_AUDIO_TAIL_S = 5.0


@dataclass(frozen=True)
class MediaMeta:
    """元数据（LRC 标签与 ID3 合并后）。"""

    title: str | None = None
    artist: str | None = None
    album: str | None = None


@dataclass(frozen=True)
class LayoutRects:
    """逻辑分辨率布局矩形（x, y, w, h）。"""

    canvas: tuple[int, int]
    cover_rect: tuple[int, int, int, int]
    lyrics_rect: tuple[int, int, int, int]
    safe_area: tuple[int, int, int, int]


def compute_layout(
    width: int, height: int, preset: str = "landscape_mv",
    cover_offset_x: int = 0, lyrics_offset_x: int = 0,
) -> LayoutRects:
    """计算左右布局和独立水平偏移，静态区域限制在画布内。"""
    margin = 64
    cover = max(360, min(720, height - 2 * margin))
    cover_x = 96
    cover_y = (height - cover) // 2
    lyrics_x = cover_x + cover + 64
    lyrics_width = max(200, width - margin - lyrics_x)
    if preset == "landscape_mv_reversed":
        cover_x = width - cover_x - cover
        lyrics_x = width - lyrics_x - lyrics_width
    cover_x = max(0, min(width - cover, cover_x + cover_offset_x))
    lyrics_x = max(0, min(width - lyrics_width, lyrics_x + lyrics_offset_x))
    lyrics_rect = (lyrics_x, cover_y, lyrics_width, cover)
    return LayoutRects(
        canvas=(width, height),
        cover_rect=(cover_x, cover_y, cover, cover),
        lyrics_rect=lyrics_rect,
        safe_area=(margin, margin, width - 2 * margin, height - 2 * margin),
    )


@dataclass
class RenderContext:
    """一次渲染的完整上下文。assets 由 Scene.prepare 填充（kind → LayerAssets）。"""

    project: KProj
    layout: LayoutRects
    palette: Palette
    lyrics: list[LyricLine]
    intervals: list[tuple[float, float]]
    duration: float
    meta: MediaMeta
    cover: Image.Image | None
    bg_image: Image.Image | None
    fonts: FontCache
    audio_path: Path | None = None
    assets: dict[str, object] = field(default_factory=dict)

    @property
    def meta_text(self) -> str:
        """「标题 − 艺术家」元数据条文本（show_metadata=False 时为空）。"""
        if not self.project.output.show_metadata:
            return ""
        parts = [p for p in (self.meta.title, self.meta.artist) if p]
        return " − ".join(parts)

    @property
    def width(self) -> int:
        return self.layout.canvas[0]

    @property
    def height(self) -> int:
        return self.layout.canvas[1]

    @property
    def fps(self) -> int:
        return max(1, self.project.output.fps)


def _load_image(path: Path | None) -> Image.Image | None:
    if path is None:
        return None
    try:
        with Image.open(path) as img:
            return img.convert("RGB")
    except OSError:
        return None


def _load_lrc_doc(lrc_path: Path | None, lrc_text: str | None) -> LrcDocument:
    text = lrc_text
    if text is None and lrc_path is not None:
        try:
            text = Path(lrc_path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return LrcDocument()
    return parse_lrc(text) if text else LrcDocument()


def build_context(
    project: KProj,
    base_dir: str | Path,
    *,
    lrc_text: str | None = None,
    duration_override: float | None = None,
    font_dir: str | Path | None = None,
) -> RenderContext:
    """从工程文件构建渲染上下文。media 解析顺序：相对工程目录 → 绝对路径。"""
    base = Path(base_dir)
    audio_path = resolve_media(project, base, "audio")
    cover_path = resolve_media(project, base, "cover")
    bg_path = resolve_media(project, base, "background")
    lrc_path = resolve_media(project, base, "lrc")

    cover_img = _load_image(cover_path)
    bg_img = _load_image(bg_path)
    doc = _load_lrc_doc(lrc_path, lrc_text)
    lyrics = doc.lines

    # 时长：override > ffprobe/mutagen > LRC 末行 + 兜底
    duration = 0.0
    if duration_override is not None:
        try:
            duration = float(duration_override)
        except (TypeError, ValueError):
            duration = 0.0
    if duration <= 0.0 and audio_path is not None:
        try:
            duration = audio_duration(audio_path)
        except ValueError:
            duration = 0.0
    if duration <= 0.0 and lyrics:
        last = lyrics[-1]
        timed_end = max((word.end if word.end is not None else word.start + _NO_AUDIO_TAIL_S
                         for word in last.words or []), default=last.time)
        duration = max(last.time + _NO_AUDIO_TAIL_S, timed_end)

    # 元数据：LRC 标签回退 ID3
    tags = read_audio_meta(audio_path) if audio_path is not None else {}
    meta = MediaMeta(
        title=doc.title or tags.get("title"),
        artist=doc.artist or tags.get("artist"),
        album=doc.album or tags.get("album"),
    )

    intervals = line_intervals(lyrics, duration if duration > 0 else None)

    layout = compute_layout(
        project.output.width, project.output.height, project.output.layout_preset,
        project.output.cover_offset_x, project.output.lyrics_offset_x,
    )

    # 取色：自动 → K-Means；手动 → 用户配置
    if project.colors.auto_extract and cover_img is not None:
        palette = extract_palette(cover_img)
    else:
        palette = palette_from_manual(project.colors.primary, project.colors.secondary)

    fonts = FontCache(Path(font_dir) if font_dir else APP_ROOT / "font")

    return RenderContext(
        project=replace(project, lyric_style=replace(project.lyric_style)),
        layout=layout,
        palette=palette,
        lyrics=lyrics,
        intervals=intervals,
        duration=duration,
        meta=meta,
        cover=cover_img,
        bg_image=bg_img,
        fonts=fonts,
        audio_path=audio_path,
    )


def bg_sample_bitmap(
    img: Image.Image,
    w: int,
    h: int,
    *,
    rect: tuple[int, int, int, int] | None = None,
) -> Image.Image:
    """取背景样本；指定 ``rect`` 时只返回画布中该区域的对应内容。

    媒体图先按 cover-fill 映射到逻辑画布，再裁剪歌词区域并缩小，保证
    取色与最终背景的构图一致，同时把采样成本限制在很小的位图上。
    """
    fitted = cover_fill_resize(img, max(2, int(w)), max(2, int(h)))
    if rect is None:
        return fitted.resize(
            (max(2, int(w) // 4), max(2, int(h) // 4)), Image.Resampling.BILINEAR
        )

    x, y, rw, rh = rect
    left = max(0, min(fitted.width, int(x)))
    top = max(0, min(fitted.height, int(y)))
    right = max(left + 1, min(fitted.width, int(x + rw)))
    bottom = max(top + 1, min(fitted.height, int(y + rh)))
    crop = fitted.crop((left, top, right, bottom))
    return crop.resize(
        (max(2, min(64, crop.width)), max(2, min(64, crop.height))),
        Image.Resampling.BILINEAR,
    )


def lyric_colors_of(ctx: RenderContext) -> tuple[RGB, RGB]:
    """(主歌词色, 描边色) RGB。"""
    return hex_to_rgb(ctx.project.lyric_style.main_color), hex_to_rgb(
        ctx.project.lyric_style.stroke_color
    )


def sub_colors_of(ctx: RenderContext) -> tuple[RGB, RGB]:
    """(译文色, 描边色) RGB。"""
    return hex_to_rgb(ctx.project.lyric_style.sub_color), hex_to_rgb(
        ctx.project.lyric_style.stroke_color
    )
