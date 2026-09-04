"""背景动画：静态模糊 / 渐变波浪 / 波浪模糊。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import ClassVar, cast

import numpy as np

from ..context import RenderContext
from ..prepare import (
    BG_DOWNSAMPLE,
    make_gradient_wave_bg,
    make_static_blur_bg,
    make_wave_blur_bg,
)
from .base import KIND_BACKGROUND, BaseLayer, ParamSpec, register


@dataclass(frozen=True)
class BgState:
    """背景帧状态：源矩形偏移（逻辑像素）。"""

    x_offset: float = 0.0
    y_offset: float = 0.0
    alpha: float = 1.0


@dataclass
class BgAssets:
    """背景位图资源。scale = 位图像素 / 逻辑像素（1/4 分辨率波浪为 0.25）。"""

    bitmap: np.ndarray  # (H, W, 3) uint8
    logical_size: tuple[int, int]  # 位图代表的逻辑尺寸（可大于画布）
    scale: float
    mode: str  # "blit" | "shift_x" | "shift_y"
    period_px: float = 0.0  # shift_x：位图水平周期（逻辑像素）
    base_offset_px: float = 0.0  # shift_y：位图上方预留振幅余量（逻辑像素）


class _BackgroundBase(BaseLayer):
    kind: ClassVar[str] = KIND_BACKGROUND

    def _source(self, ctx: RenderContext):
        return ctx.bg_image if ctx.bg_image is not None else ctx.cover


@register(KIND_BACKGROUND)
class StaticBlurBG(_BackgroundBase):
    """静态模糊背景。"""

    anim_type: ClassVar[str] = "static_blur"
    label: ClassVar[str] = "静态模糊"

    def prepare(self, ctx: RenderContext) -> BgAssets:
        w, h = ctx.width, ctx.height
        bitmap = make_static_blur_bg(self._source(ctx), w, h)
        return BgAssets(bitmap=bitmap, logical_size=(w, h), scale=1.0, mode="blit")

    def eval(self, t: float, ctx: RenderContext) -> BgState:
        return BgState()


@register(KIND_BACKGROUND)
class GradientWaveBG(_BackgroundBase):
    """渐变波浪背景：纯数学生成，不依赖图片输入。"""

    anim_type: ClassVar[str] = "gradient_wave"
    label: ClassVar[str] = "渐变波浪"

    @classmethod
    def params_schema(cls) -> list[ParamSpec]:
        return [
            ParamSpec("speed", "相位速度", "float", 1.0, 0.05, 5.0),
            ParamSpec("amp", "振幅", "float", 0.3, 0.0, 1.0),
        ]

    def prepare(self, ctx: RenderContext) -> BgAssets:
        w, h = ctx.width, ctx.height
        bitmap = make_gradient_wave_bg(ctx.palette.primary, ctx.palette.secondary, w, h)
        return BgAssets(
            bitmap=bitmap,
            logical_size=(w, h),
            scale=1.0 / BG_DOWNSAMPLE,
            mode="shift_x",
            period_px=w,
        )

    def eval(self, t: float, ctx: RenderContext) -> BgState:
        speed = self.params["speed"]
        amp = self.params["amp"]
        x = ((t * speed) % 1.0) * ctx.width
        y = amp * 0.03 * ctx.height * math.sin(2.0 * math.pi * t * speed / 6.0)
        return BgState(x_offset=x, y_offset=y)


@register(KIND_BACKGROUND)
class WaveBlurBG(_BackgroundBase):
    """波浪模糊背景：基于图片，整幅正弦纵向漂移。"""

    anim_type: ClassVar[str] = "wave_blur"
    label: ClassVar[str] = "波浪模糊"

    @classmethod
    def params_schema(cls) -> list[ParamSpec]:
        return [
            ParamSpec("speed", "相位速度", "float", 1.0, 0.05, 5.0),
            ParamSpec("amp", "振幅", "float", 0.3, 0.0, 1.0),
        ]

    def prepare(self, ctx: RenderContext) -> BgAssets:
        w, h = ctx.width, ctx.height
        amp_px = self.params["amp"] * 0.05 * h
        bitmap = make_wave_blur_bg(self._source(ctx), w, h, amp_px)
        return BgAssets(
            bitmap=bitmap,
            logical_size=(w, round(h + 2.0 * amp_px)),
            scale=1.0,
            mode="shift_y",
            base_offset_px=amp_px,
        )

    def eval(self, t: float, ctx: RenderContext) -> BgState:
        assets = cast(BgAssets, ctx.assets[KIND_BACKGROUND])
        speed = self.params["speed"]
        y = assets.base_offset_px + assets.base_offset_px * math.sin(
            2.0 * math.pi * t * speed / 5.0
        )
        return BgState(y_offset=y)
