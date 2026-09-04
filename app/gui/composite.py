"""共用 QPainter 合成：预览与导出调用同一 composite()，保证所见即所得。

调用方负责建立 painter 与变换：
- 导出：QImage(1920, 1080) + QPainter（worker 线程允许 QImage，禁止 QPixmap）；
- 预览：painter.scale(widget_w / 1920, widget_h / 1080) 后调用同一函数。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QImage, QPainter

from ..core.anims.background import BgAssets
from ..core.anims.base import clamp
from ..core.anims.cover import CoverAssets
from ..core.anims.lyrics import LyricsAssets
from ..core.context import RenderContext
from ..core.prepare import PreparedBitmap
from ..core.scene import META_ASSETS_KEY, MetaAssets, SceneState


def numpy_to_qimage(arr: np.ndarray) -> QImage:
    """numpy (H, W, 3|4) uint8 → QImage（copy() 深拷贝，脱离 numpy 缓冲生命周期）。"""
    if arr.ndim != 3 or arr.shape[2] not in (3, 4):
        raise ValueError(f"期望 (H, W, 3|4) 数组，得到 {arr.shape}")
    h, w, ch = arr.shape
    fmt = QImage.Format.Format_RGB888 if ch == 3 else QImage.Format.Format_RGBA8888
    contiguous = np.ascontiguousarray(arr, dtype=np.uint8)
    img = QImage(contiguous.data, w, h, ch * w, fmt)
    return img.copy()


def qimage_to_rgb_array(img: QImage) -> np.ndarray:
    """QImage → (H, W, 3) 连续 uint8（供 yuv420p 转换）。

    必须显式拷贝：RGB888 无 padding 时切片视图直接别名 QImage 内部缓冲，
    若数组寿命超出 QImage 会读到已释放内存。
    """
    h, w = img.height(), img.width()
    bpl = img.bytesPerLine()
    buf = img.constBits()
    rows = np.frombuffer(buf, dtype=np.uint8, count=bpl * h).reshape(h, bpl)
    return np.array(rows[:, : w * 3], copy=True).reshape(h, w, 3)


def qimage_rgb24_buffer(
    img: QImage, scratch: bytearray | None = None
) -> tuple[memoryview, bytearray | None]:
    """返回可直接喂给 FFmpeg ``rgb24`` 输入的帧缓冲。

    ``Format_RGB888`` 的默认 1920×1080 行距恰好没有 padding，因此生产导出
    直接返回 QImage 内存视图。若用户配置了导致行填充的宽度，则复用一个紧凑
    的 bytearray，逐行去掉 padding，保证 rawvideo 的帧大小恒为 ``w*h*3``。
    """
    if img.format() != QImage.Format.Format_RGB888:
        raise ValueError("RGB rawvideo 需要 QImage.Format_RGB888")
    width, height = img.width(), img.height()
    row_bytes = width * 3
    packed_bytes = row_bytes * height
    source = memoryview(img.constBits()).cast("B")
    stride = img.bytesPerLine()
    if stride == row_bytes:
        return source[:packed_bytes], scratch

    if scratch is None or len(scratch) != packed_bytes:
        scratch = bytearray(packed_bytes)
    for row in range(height):
        src_start = row * stride
        dst_start = row * row_bytes
        scratch[dst_start : dst_start + row_bytes] = source[
            src_start : src_start + row_bytes
        ]
    return memoryview(scratch), scratch


@dataclass
class GuiBitmap:
    """可绘制位图：QImage + 相对锚点偏移。"""

    image: QImage
    ox: float
    oy: float
    w: float
    h: float


def _gui_bitmap(pb: PreparedBitmap | None) -> GuiBitmap | None:
    if pb is None or pb.pixels.size == 0:
        return None
    return GuiBitmap(
        numpy_to_qimage(pb.pixels), pb.origin[0], pb.origin[1], pb.width, pb.height
    )


@dataclass
class GuiAssets:
    """core assets 的 Qt 侧镜像（QImage 转换只发生一次）。"""

    canvas: tuple[float, float]
    cover_rect: tuple[float, float, float, float]
    lyric_rect: tuple[float, float, float, float]
    bg_image: QImage | None
    bg_scale: float
    bg_mode: str
    bg_period: float
    cover_face: GuiBitmap | None
    cover_reflection: GuiBitmap | None
    cover_gap: float
    cover_disc: bool
    lyric_lines: list[
        tuple[list[GuiBitmap], list[GuiBitmap], float]
    ]  # (main, sub, sub_offset)
    meta_segments: list[GuiBitmap]

    @classmethod
    def from_context(cls, ctx: RenderContext) -> GuiAssets:
        """Scene.prepare() 之后调用：把 ctx.assets 转成 QImage。"""
        if not ctx.assets:
            raise RuntimeError("assets 为空：请先 Scene.prepare()")

        bg: BgAssets | None = None
        if KIND_BG in ctx.assets and isinstance(ctx.assets[KIND_BG], BgAssets):
            bg = ctx.assets[KIND_BG]  # type: ignore[assignment]
        bg_image = numpy_to_qimage(bg.bitmap) if bg is not None else None

        cover: CoverAssets | None = None
        if KIND_COVER in ctx.assets and isinstance(ctx.assets[KIND_COVER], CoverAssets):
            cover = ctx.assets[KIND_COVER]  # type: ignore[assignment]

        lines: list[tuple[list[GuiBitmap], list[GuiBitmap], float]] = []
        lyric_assets = ctx.assets.get(KIND_LYRICS)
        if isinstance(lyric_assets, LyricsAssets):
            for bm in lyric_assets.lines:
                main = [
                    g for g in (_gui_bitmap(seg) for seg in bm.main) if g is not None
                ]
                sub = [g for g in (_gui_bitmap(seg) for seg in bm.sub) if g is not None]
                lines.append((main, sub, bm.sub_offset))

        meta_segments: list[GuiBitmap] = []
        meta = ctx.assets.get(META_ASSETS_KEY)
        if isinstance(meta, MetaAssets) and meta.segments:
            meta_segments = [
                g for g in (_gui_bitmap(seg) for seg in meta.segments) if g is not None
            ]

        return cls(
            canvas=(ctx.width, ctx.height),
            cover_rect=ctx.layout.cover_rect,
            lyric_rect=ctx.layout.lyrics_rect,
            bg_image=bg_image,
            bg_scale=bg.scale if bg else 1.0,
            bg_mode=bg.mode if bg else "blit",
            bg_period=bg.period_px if bg else 0.0,
            cover_face=_gui_bitmap(cover.face) if cover else None,
            cover_reflection=_gui_bitmap(cover.reflection) if cover else None,
            cover_gap=cover.reflection_gap if cover else 0.0,
            cover_disc=cover.disc if cover else False,
            lyric_lines=lines,
            meta_segments=meta_segments,
        )


KIND_BG = "background"
KIND_LYRICS = "lyrics"
KIND_COVER = "cover"


def composite(painter: QPainter, state: SceneState, assets: GuiAssets) -> None:
    """在逻辑 1920×1080 坐标系内合成一帧。调用方设置好 painter 变换。"""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    _draw_background(painter, state, assets)
    _draw_cover(painter, state, assets)
    _draw_lyrics(painter, state, assets)
    _draw_metadata(painter, state, assets)
    painter.restore()


def _draw_background(painter: QPainter, state: SceneState, assets: GuiAssets) -> None:
    img = assets.bg_image
    if img is None:
        return
    w, h = assets.canvas
    scale = assets.bg_scale
    if assets.bg_mode == "shift_x":
        period = assets.bg_period if assets.bg_period > 0.0 else w
        x0 = state.bg.x_offset % period
        src = QRectF(x0 * scale, 0.0, w * scale, h * scale)
    elif assets.bg_mode == "shift_y":
        y0 = max(0.0, state.bg.y_offset)
        src = QRectF(0.0, y0 * scale, w * scale, h * scale)
    else:
        src = QRectF(0.0, 0.0, img.width(), img.height())
    painter.drawImage(QRectF(0.0, 0.0, w, h), img, src)


def _draw_cover(painter: QPainter, state: SceneState, assets: GuiAssets) -> None:
    face = assets.cover_face
    if face is None:
        return
    x, y, w, h = assets.cover_rect
    cx = x + w / 2.0
    cy = y + h / 2.0

    reflection = assets.cover_reflection
    if reflection is not None and state.cover.reflection_alpha > 0.0:
        painter.save()
        painter.setOpacity(clamp(state.cover.reflection_alpha))
        painter.drawImage(
            QRectF(cx - face.w / 2.0, y + h + assets.cover_gap, face.w, reflection.h),
            reflection.image,
        )
        painter.restore()

    painter.save()
    if assets.cover_disc and state.cover.angle != 0.0:
        painter.translate(cx, cy)
        painter.rotate(state.cover.angle)
        painter.drawImage(
            QRectF(-face.w / 2.0, -face.h / 2.0, face.w, face.h), face.image
        )
    else:
        painter.drawImage(
            QRectF(cx - face.w / 2.0, cy - face.h / 2.0, face.w, face.h), face.image
        )
    painter.restore()


def _draw_lyrics(painter: QPainter, state: SceneState, assets: GuiAssets) -> None:
    if not state.lyrics.items:
        return
    painter.save()
    rx, ry, rw, rh = assets.lyric_rect
    painter.setClipRect(QRectF(rx, ry, rw, rh))
    for item in state.lyrics.items:
        if item.index >= len(assets.lyric_lines):
            continue
        main_segs, sub_segs, sub_offset = assets.lyric_lines[item.index]
        painter.setOpacity(clamp(item.opacity))
        for seg in main_segs:
            painter.drawImage(QPointF(item.x + seg.ox, item.y + seg.oy), seg.image)
        for seg in sub_segs:
            painter.drawImage(
                QPointF(item.x + seg.ox, item.y + sub_offset + seg.oy), seg.image
            )
    painter.restore()


def _draw_metadata(painter: QPainter, state: SceneState, assets: GuiAssets) -> None:
    segs = assets.meta_segments
    if state.meta_alpha <= 0.0 or not segs:
        return
    painter.save()
    painter.setOpacity(clamp(state.meta_alpha) * 0.9)
    w, h = assets.canvas
    margin = 64.0
    total_h = segs[-1].oy + segs[-1].h
    y_top = h - margin - total_h
    cx = w / 2.0
    for seg in segs:
        painter.drawImage(QPointF(cx + seg.ox, y_top + seg.oy), seg.image)
    painter.restore()
