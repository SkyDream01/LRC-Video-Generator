"""背景效果：图片背景（模糊、缩放、漂移）与生成背景（渐变、雾光）。"""

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
    zoom: float = 1.0


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
    category: ClassVar[str] = "图片背景"

    def _source(self, ctx: RenderContext):
        return ctx.bg_image if ctx.bg_image is not None else ctx.cover


@register(KIND_BACKGROUND)
class StaticBlurBG(_BackgroundBase):
    """静态模糊背景。"""

    anim_type: ClassVar[str] = "static_blur"
    label: ClassVar[str] = "静态模糊"
    description: ClassVar[str] = "将背景图柔化为静止背景；未设置背景图时使用封面。"
    display_order: ClassVar[int] = 0

    def prepare(self, ctx: RenderContext) -> BgAssets:
        w, h = ctx.width, ctx.height
        bitmap = make_static_blur_bg(self._source(ctx), w, h)
        return BgAssets(bitmap=bitmap, logical_size=(w, h), scale=1.0, mode="blit")

    def eval(self, t: float, ctx: RenderContext) -> BgState:
        return BgState()


@register(KIND_BACKGROUND)
class GradientWaveBG(_BackgroundBase):
    """渐变流动：纯数学生成渐变波纹，不依赖图片输入。"""

    anim_type: ClassVar[str] = "gradient_wave"
    label: ClassVar[str] = "渐变流动"
    category: ClassVar[str] = "生成背景"
    description: ClassVar[str] = "主色与辅色组成渐变波纹，沿水平方向循环流动，无需背景图。"
    display_order: ClassVar[int] = 30

    @classmethod
    def params_schema(cls) -> list[ParamSpec]:
        return [
            ParamSpec("speed", "流动速度", "float", 1.0, 0.05, 5.0),
            ParamSpec("amp", "波纹强度", "float", 0.3, 0.0, 1.0),
        ]

    def prepare(self, ctx: RenderContext) -> BgAssets:
        w, h = ctx.width, ctx.height
        bitmap = make_gradient_wave_bg(ctx.palette.primary, ctx.palette.secondary, w, h, self.params["amp"])
        return BgAssets(
            bitmap=bitmap,
            logical_size=(w, h),
            scale=1.0 / BG_DOWNSAMPLE,
            mode="shift_x",
            period_px=w,
        )

    def eval(self, t: float, ctx: RenderContext) -> BgState:
        speed = self.params["speed"]
        x = ((t * speed) % 1.0) * ctx.width
        return BgState(x_offset=x)


@register(KIND_BACKGROUND)
class WaveBlurBG(_BackgroundBase):
    """纵向漂移：模糊图片背景整体沿竖直方向往复移动。"""

    anim_type: ClassVar[str] = "wave_blur"
    label: ClassVar[str] = "纵向漂移"
    description: ClassVar[str] = "模糊背景图平滑上下漂移；未设置背景图时使用封面。"
    display_order: ClassVar[int] = 20

    @classmethod
    def params_schema(cls) -> list[ParamSpec]:
        return [
            ParamSpec("speed", "漂移速度", "float", 1.0, 0.05, 5.0),
            ParamSpec("amp", "漂移幅度", "float", 0.3, 0.0, 1.0),
        ]

    def prepare(self, ctx: RenderContext) -> BgAssets:
        w, h = ctx.width, ctx.height
        amp_px = self.params["amp"] * 0.05 * h
        bitmap = make_wave_blur_bg(self._source(ctx), w, h, amp_px)
        return BgAssets(
            bitmap=bitmap,
            logical_size=(w, bitmap.shape[0]),
            scale=1.0,
            mode="shift_y",
            base_offset_px=(bitmap.shape[0] - h) / 2.0,
        )

    def eval(self, t: float, ctx: RenderContext) -> BgState:
        assets = cast(BgAssets, ctx.assets[KIND_BACKGROUND])
        speed = self.params["speed"]
        y = assets.base_offset_px + assets.base_offset_px * math.sin(
            2.0 * math.pi * t * speed / 5.0
        )
        return BgState(y_offset=y)


@register(KIND_BACKGROUND)
class BreathZoomBG(StaticBlurBG):
    """居中裁切缓存背景，周期性缓慢推近与拉远。"""

    anim_type: ClassVar[str] = "breath_zoom"
    label: ClassVar[str] = "呼吸缩放"
    description: ClassVar[str] = "模糊背景图缓慢推近、拉远；未设置背景图时使用封面。"
    display_order: ClassVar[int] = 10

    @classmethod
    def params_schema(cls) -> list[ParamSpec]:
        return [
            ParamSpec("period", "周期 (秒)", "float", 12.0, 2.0, 60.0),
            ParamSpec("amount", "缩放幅度", "float", 0.08, 0.0, 0.3),
        ]

    def eval(self, t: float, ctx: RenderContext) -> BgState:
        pulse = (1.0 - math.cos(2.0 * math.pi * t / self.params["period"])) / 2.0
        return BgState(zoom=1.0 + self.params["amount"] * pulse)


@register(KIND_BACKGROUND)
class MidnightBG(StaticBlurBG):
    """深蓝径向雾光背景，与封面颜色无关。"""

    anim_type: ClassVar[str] = "midnight"
    label: ClassVar[str] = "午夜雾光"
    category: ClassVar[str] = "生成背景"
    description: ClassVar[str] = "深蓝色静态雾光背景，无需背景图，使用固定配色。"
    display_order: ClassVar[int] = 40

    def prepare(self, ctx: RenderContext) -> BgAssets:
        w, h = ctx.width, ctx.height
        yy, xx = np.mgrid[0:h:4, 0:w:4]
        light = np.exp(-(((xx-w*.36)/(w*.40))**2 + ((yy-h*.46)/(h*.75))**2)*1.8)
        bitmap = np.stack([12+light*36, 21+light*47, 35+light*55], axis=-1).astype(np.uint8)
        return BgAssets(bitmap, (w, h), .25, "blit")
