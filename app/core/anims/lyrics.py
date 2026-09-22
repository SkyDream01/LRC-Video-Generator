"""歌词动画：淡入淡出 / 滚动列表 / 滑入滑出 / 横向揭幕。"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
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
    reveal: float = 1.0
    tilt_x: float = 0.0
    angle: float = 0.0
    scale: float = 1.0
    left_align: bool = False
    right_align: bool = False
    word_progress: float | None = None  # 已唱字符数，含当前字的连续进度


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
        cursor = 0
        for seg in main_segs:
            visible_text = seg.text.removesuffix("…")
            position = line.text.find(visible_text, cursor)
            seg.char_start = position if position >= 0 else cursor
            cursor = seg.char_start + len(visible_text)
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
    step = max(
        style.main_size * 1.5 + (style.sub_size * 1.2 if has_sub else 0.0),
        max((bm.height for bm in lines), default=0.0) + SUB_GAP,
    )
    return LyricsAssets(
        lines=lines, rect=rect, starts=line_starts(ctx.intervals), step=step
    )


def apply_word_timing(state: LyricsState, t: float, ctx: RenderContext) -> LyricsState:
    """给任意行级动画叠加逐字进度；无像素操作，支持任意时间跳转。"""
    items = []
    for item in state.items:
        line = ctx.lyrics[item.index]
        if not line.words:
            items.append(item)
            continue
        progress = float(line.words[0].char_start)
        for word in line.words:
            if t < word.start:
                break
            end = word.end if word.end is not None else ctx.intervals[item.index][1]
            fraction = clamp((t - word.start) / (end - word.start)) if end > word.start else 1.0
            progress = max(progress, word.char_start + (word.char_end - word.char_start) * fraction)
        items.append(replace(item, word_progress=progress))
    return replace(state, items=tuple(items))


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
        if idx < 0 or idx >= len(assets.lines) or t >= ctx.intervals[idx][1]:
            return LyricsState((), -1)
        start, end = ctx.intervals[idx]
        fade_s = min(self.params["fade_ms"] / 1000.0, (end - start) / 2.0)
        if fade_s <= 0.0:
            alpha = 1.0
        else:
            alpha = _smooth(clamp(min((t - start) / fade_s, (end - t) / fade_s)))
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
        if idx < 0 or idx >= len(assets.lines) or t >= ctx.intervals[idx][1]:
            return LyricsState((), -1)

        ease_fn = _EASINGS.get(str(self.params["ease"]), _ease_cubic)
        # 换行动画：当前行 start 起缓动，从上一行位置滑到当前位置（首行保持居中）
        start, end = ctx.intervals[idx]
        seconds = min(SCROLL_MS / 1000.0, (end - start) / 2.0)
        progress = clamp((t - start) / seconds) if seconds > 0 else 1.0
        focus = max(0.0, (idx - 1) + ease_fn(progress))

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
            alpha = (1.0 - 0.65 * _smooth(min(dist, 1.0))) * _smooth(clamp((half - dist) * 2.0))
            y = cy + (i - focus) * assets.step - assets.lines[i].height / 2.0
            items.append(LyricItem(i, cx, y, alpha, i == idx))
        return LyricsState(tuple(items), idx)


def _smooth(p: float) -> float:
    """端点速度为零的平滑插值。"""
    return p * p * (3.0 - 2.0 * p)


def _ease_cubic(p: float) -> float:
    return _smooth(p)


_EASINGS = {"linear": lambda p: p, "cubic": _ease_cubic}


@register(KIND_LYRICS)
class SlideLyrics(FadeLyrics):
    """单行歌词从下方滑入，向上滑出，短行自动压缩过渡。"""

    anim_type: ClassVar[str] = "slide"
    label: ClassVar[str] = "滑入滑出"

    @classmethod
    def params_schema(cls) -> list[ParamSpec]:
        return [
            ParamSpec("fade_ms", "过渡时长 (ms)", "int", 400, 0, 2000),
            ParamSpec("distance", "滑动距离 (px)", "float", 48.0, 0.0, 160.0),
        ]

    def eval(self, t: float, ctx: RenderContext) -> LyricsState:
        state = super().eval(t, ctx)
        if not state.items:
            return state
        start, end = ctx.intervals[state.current_index]
        if t >= end:
            return LyricsState()
        seconds = min(self.params["fade_ms"] / 1000.0, (end - start) / 2.0)
        enter = clamp((t - start) / seconds) if seconds > 0 else 1.0
        leave = clamp((end - t) / seconds) if seconds > 0 else 1.0
        offset = self.params["distance"] * ((1 - enter) ** 3 - (1 - leave) ** 3)
        item = replace(
            state.items[0], y=state.items[0].y + offset, opacity=_smooth(min(enter, leave))
        )
        return LyricsState((item,), state.current_index)


@register(KIND_LYRICS)
class RevealLyrics(FadeLyrics):
    """按行从左向右揭示主歌词与译文，不依赖词级时间。"""

    anim_type: ClassVar[str] = "reveal"
    label: ClassVar[str] = "横向揭幕"

    @classmethod
    def params_schema(cls) -> list[ParamSpec]:
        return [ParamSpec("reveal_ms", "揭幕时长 (ms)", "int", 800, 0, 3000)]

    def eval(self, t: float, ctx: RenderContext) -> LyricsState:
        assets = cast(LyricsAssets, ctx.assets[KIND_LYRICS])
        idx = current_index(assets.starts, t)
        if idx < 0 or idx >= len(assets.lines) or t >= ctx.intervals[idx][1]:
            return LyricsState()
        start, end = ctx.intervals[idx]
        seconds = min(self.params["reveal_ms"] / 1000.0, (end - start) / 2.0)
        progress = clamp((t - start) / seconds) if seconds > 0 else 1.0
        x, y, w, h = assets.rect
        item = LyricItem(
            idx,
            x + w / 2,
            y + (h - assets.lines[idx].height) / 2,
            _smooth(clamp((end - t) / min(0.2, (end - start) / 2))) if seconds > 0 else 1.0,
            True,
            reveal=_smooth(progress),
        )
        return LyricsState((item,), idx)


@register(KIND_LYRICS)
class Flip3DLyrics(FadeLyrics):
    """双语歌词整体透视翻入、翻出，停留期间正面展示。"""

    anim_type: ClassVar[str] = "flip_3d"
    label: ClassVar[str] = "3D 翻转"

    @classmethod
    def params_schema(cls) -> list[ParamSpec]:
        return [
            ParamSpec("fade_ms", "过渡时长 (ms)", "int", 650, 0, 2000),
            ParamSpec("angle", "翻转角度 (度)", "float", 65.0, 0.0, 80.0),
        ]

    def eval(self, t: float, ctx: RenderContext) -> LyricsState:
        state = super().eval(t, ctx)
        if not state.items:
            return state
        start, end = ctx.intervals[state.current_index]
        if t >= end:
            return LyricsState()
        seconds = min(self.params["fade_ms"] / 1000.0, (end - start) / 2.0)
        enter = clamp((t - start) / seconds) if seconds > 0 else 1.0
        leave = clamp((end - t) / seconds) if seconds > 0 else 1.0
        tilt = self.params["angle"] * ((1 - enter) ** 3 - (1 - leave) ** 3)
        return LyricsState(
            (replace(state.items[0], tilt_x=tilt, opacity=_smooth(min(enter, leave))),),
            state.current_index,
        )


@register(KIND_LYRICS)
class ArcLyrics(FadeLyrics):
    """沿朝向歌词区域的圆弧滚动，靠近焦点时连续放大与提亮。"""

    anim_type: ClassVar[str] = "arc"
    label: ClassVar[str] = "圆弧歌词"

    @classmethod
    def params_schema(cls) -> list[ParamSpec]:
        return [
            ParamSpec("lines", "可见行数", "int", 7, 3, 9),
            ParamSpec("spacing", "圆弧间隔 (度)", "float", 18.0, 12.0, 24.0),
            ParamSpec("transition_ms", "换行时长 (ms)", "int", 650, 100, 1500),
        ]

    def eval(self, t: float, ctx: RenderContext) -> LyricsState:
        assets = cast(LyricsAssets, ctx.assets[KIND_LYRICS])
        idx = current_index(assets.starts, t)
        if idx < 0 or idx >= len(assets.lines) or t >= ctx.intervals[idx][1]:
            return LyricsState()
        start, end = ctx.intervals[idx]
        seconds = min(self.params["transition_ms"]/1000, (end-start)/2)
        progress = clamp((t-start)/seconds) if seconds > 0 else 1.0
        focus = max(0, idx-1+_ease_cubic(progress))
        x, y, w, h = ctx.layout.cover_rect
        cx, cy = x+w/2, y+h/2
        direction = 1 if assets.rect[0] + assets.rect[2]/2 >= cx else -1
        anchor = assets.rect[0] + (12 if direction > 0 else assets.rect[2] - 12)
        radius = abs(anchor - cx)
        half = self.params["lines"]/2
        items = []
        for i in range(max(0, math.floor(focus-half)), min(len(assets.lines), math.ceil(focus+half)+1)):
            delta = i-focus
            distance = abs(delta)
            if distance >= half:
                continue
            angle = delta*self.params["spacing"]
            rad = math.radians(angle)
            scale = .48+.52*math.exp(-distance*distance*2)
            alpha = (.20+.80*math.exp(-distance*distance*2))*_smooth(clamp(half-distance))
            items.append(LyricItem(i, anchor+direction*radius*(math.cos(rad)-1),
                cy+radius*math.sin(rad)-assets.lines[i].height*scale/2,
                alpha, i==idx, angle=direction*angle*.45, scale=scale,
                left_align=direction > 0, right_align=direction < 0))
        return LyricsState(tuple(items), idx)
