"""歌词动画：淡入淡出（单行高亮）/ 滚动列表（多行高亮+缓动滚动）。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import ClassVar, cast

from ..context import RenderContext, lyric_colors_of, sub_colors_of
from ..prepare import PreparedBitmap, layout_text
from ..timeline import current_index, line_starts
from .base import KIND_LYRICS, BaseLayer, ParamSpec, clamp, register

# 主歌词与译文的垂直间距（逻辑像素）
SUB_GAP = 18.0
# 滚动列表换行缓动时长（毫秒）
SCROLL_MS = 350.0


@dataclass(frozen=True)
class LyricItem:
    """单行歌词的绘制状态。x/y 为行锚点（主文本块顶部中心，逻辑坐标）。"""

    index: int
    x: float
    y: float
    opacity: float
    current: bool


@dataclass(frozen=True)
class LyricsState:
    items: tuple[LyricItem, ...] = ()
    current_index: int = -1


@dataclass
class LineBitmaps:
    """单行歌词资源：主/译文各 1-2 段紧 bbox 位图，origin 相对行锚点。"""

    main: list[PreparedBitmap]
    sub: list[PreparedBitmap]
    main_height: float
    height: float  # 主块(+间距)译文块 总高
    sub_offset: float  # 译文块顶部相对行锚点的 y 偏移（无译文为 0）


@dataclass
class LyricsAssets:
    lines: list[LineBitmaps]
    rect: tuple[int, int, int, int]
    starts: list[float]
    step: float  # scroll_list 行距（逻辑像素）


def build_lyrics_assets(ctx: RenderContext) -> LyricsAssets:
    """共享 prepare：逐行光栅化主歌词与译文（超宽缩字/换行在 layout_text 内处理）。"""
    style = ctx.project.lyric_style
    rect = ctx.layout.lyrics_rect
    max_w = rect[2]
    main_color, stroke = lyric_colors_of(ctx)
    sub_color, sub_stroke = sub_colors_of(ctx)

    lines: list[LineBitmaps] = []
    for line in ctx.lyrics:
        main_segs = layout_text(
            line.text,
            ctx.fonts,
            style.main_font,
            style.main_size,
            main_color,
            stroke,
            style.stroke_width,
            max_w,
        )
        sub_segs = (
            layout_text(
                line.translation or "",
                ctx.fonts,
                style.sub_font,
                style.sub_size,
                sub_color,
                sub_stroke,
                style.stroke_width,
                max_w,
            )
            if line.translation
            else []
        )
        main_height = (
            (main_segs[-1].origin[1] + main_segs[-1].height) if main_segs else 0.0
        )
        sub_height = (sub_segs[-1].origin[1] + sub_segs[-1].height) if sub_segs else 0.0
        sub_offset = main_height + SUB_GAP if sub_segs else 0.0
        height = sub_offset + sub_height if sub_segs else main_height
        lines.append(
            LineBitmaps(
                main=main_segs,
                sub=sub_segs,
                main_height=main_height,
                height=height,
                sub_offset=sub_offset,
            )
        )

    has_sub = any(bm.sub for bm in lines)
    step = style.main_size * 1.5 + (style.sub_size * 1.2 if has_sub else 0.0)
    return LyricsAssets(
        lines=lines, rect=rect, starts=line_starts(ctx.intervals), step=step
    )


@register(KIND_LYRICS)
class FadeLyrics(BaseLayer):
    """淡入淡出：单行居中，行首行尾各 fade_ms 渐变。"""

    kind: ClassVar[str] = KIND_LYRICS
    anim_type: ClassVar[str] = "fade"
    label: ClassVar[str] = "淡入淡出"

    @classmethod
    def params_schema(cls) -> list[ParamSpec]:
        return [ParamSpec("fade_ms", "淡入淡出 (ms)", "int", 400, 0, 2000)]

    def prepare(self, ctx: RenderContext) -> LyricsAssets:
        return build_lyrics_assets(ctx)

    def eval(self, t: float, ctx: RenderContext) -> LyricsState:
        assets = cast(LyricsAssets, ctx.assets[KIND_LYRICS])
        idx = current_index(assets.starts, t)
        if idx < 0 or idx >= len(assets.lines):
            return LyricsState((), -1)
        start, end = ctx.intervals[idx]
        fade_s = self.params["fade_ms"] / 1000.0
        if fade_s <= 0.0:
            alpha = 1.0
        else:
            alpha = clamp(min((t - start) / fade_s, (end - t) / fade_s))
        rect = assets.rect
        cx = rect[0] + rect[2] / 2.0
        cy = rect[1] + rect[3] / 2.0
        bm = assets.lines[idx]
        return LyricsState(
            (LyricItem(idx, cx, cy - bm.height / 2.0, alpha, True),), idx
        )


@register(KIND_LYRICS)
class ScrollListLyrics(BaseLayer):
    """滚动列表：多行可见、当前行高亮，换行时缓动滚动。"""

    kind: ClassVar[str] = KIND_LYRICS
    anim_type: ClassVar[str] = "scroll_list"
    label: ClassVar[str] = "滚动列表"

    @classmethod
    def params_schema(cls) -> list[ParamSpec]:
        return [
            ParamSpec("lines", "可见行数", "int", 5, 1, 11),
            ParamSpec("ease", "缓动", "choice", "cubic", choices=("linear", "cubic")),
        ]

    def prepare(self, ctx: RenderContext) -> LyricsAssets:
        return build_lyrics_assets(ctx)

    def eval(self, t: float, ctx: RenderContext) -> LyricsState:
        assets = cast(LyricsAssets, ctx.assets[KIND_LYRICS])
        idx = current_index(assets.starts, t)
        if idx < 0 or idx >= len(assets.lines):
            return LyricsState((), -1)

        ease_fn = _EASINGS.get(str(self.params["ease"]), _ease_cubic)
        # 换行动画：当前行 start 起缓动，从上一行位置滑到当前位置（首行从 -1 滑入）
        progress = clamp((t - ctx.intervals[idx][0]) / (SCROLL_MS / 1000.0))
        focus = (idx - 1) + ease_fn(progress)

        rect = assets.rect
        cx = rect[0] + rect[2] / 2.0
        cy = rect[1] + rect[3] / 2.0
        half = self.params["lines"] / 2.0
        total = len(assets.lines)
        first = max(0, math.floor(focus - half))
        last = min(total - 1, math.ceil(focus + half))

        items = []
        for i in range(first, last + 1):
            dist = abs(i - focus)
            if dist > half + 0.5:
                continue
            alpha = 1.0 if dist < 0.5 else clamp(1.0 - 0.28 * dist, 0.15, 1.0)
            y = cy + (i - focus) * assets.step - assets.lines[i].height / 2.0
            items.append(LyricItem(i, cx, y, alpha, i == idx))
        return LyricsState(tuple(items), idx)


def _ease_cubic(p: float) -> float:
    return 1.0 - (1.0 - p) ** 3


_EASINGS = {"linear": lambda p: p, "cubic": _ease_cubic}
