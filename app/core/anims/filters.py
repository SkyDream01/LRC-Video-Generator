"""动态氛围滤镜：prepare 缓存小贴图，eval 仅计算确定性的运动状态。"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import ClassVar, cast

import numpy as np

from ..context import RenderContext
from .base import KIND_FILTER, BaseLayer, ParamSpec, register


@dataclass(frozen=True)
class FilterSprite:
    texture: int
    x: float
    y: float
    size: float
    opacity: float


@dataclass(frozen=True)
class FilterState:
    sprites: tuple[FilterSprite, ...] = ()


@dataclass(frozen=True)
class FilterAssets:
    textures: tuple[np.ndarray, ...] = ()
    seeds: tuple[tuple[float, ...], ...] = ()


def _glow(color: tuple[int, int, int], size: int, *, ring: bool) -> np.ndarray:
    axis = np.linspace(-1, 1, size)
    radius = np.hypot(axis[:, None], axis[None, :])
    fade = np.maximum(0, 1 - radius ** 2) ** 3
    if ring:
        fade = fade * .35 + np.exp(-((radius - .65) / .10) ** 2) * .35
        fade *= np.maximum(0, 1 - radius) ** .5
    pixels = np.empty((size, size, 4), dtype=np.uint8)
    pixels[:, :, :3] = color
    pixels[:, :, 3] = np.round(fade * 255).astype(np.uint8)
    pixels.setflags(write=False)
    return pixels


@register(KIND_FILTER)
class NoFilter(BaseLayer):
    """默认关闭滤镜，旧工程保持原有画面。"""

    kind: ClassVar[str] = KIND_FILTER
    anim_type: ClassVar[str] = "none"
    label: ClassVar[str] = "关闭"
    category: ClassVar[str] = "基础"
    description: ClassVar[str] = "不叠加动态滤镜，保持原有画面。"
    display_order: ClassVar[int] = 0

    def prepare(self, ctx: RenderContext) -> FilterAssets:
        return FilterAssets()

    def eval(self, t: float, ctx: RenderContext) -> FilterState:
        return FilterState()


@register(KIND_FILTER)
class LightLeakFilter(NoFilter):
    """两团柔光沿连续闭合轨迹流动，使用封面主色与辅色。"""

    anim_type: ClassVar[str] = "light_leak"
    label: ClassVar[str] = "柔光流动"
    category: ClassVar[str] = "氛围叠加"
    description: ClassVar[str] = "主色与辅色柔光缓慢流动，叠在背景上，保持封面与歌词清晰。"
    display_order: ClassVar[int] = 10

    @classmethod
    def params_schema(cls) -> list[ParamSpec]:
        return [
            ParamSpec("strength", "滤镜强度", "float", .35, 0, 1),
            ParamSpec("period", "运动周期 (秒)", "float", 16, 2, 60),
            ParamSpec("size", "光晕大小 (px)", "int", 1100, 400, 1800),
        ]

    def prepare(self, ctx: RenderContext) -> FilterAssets:
        return FilterAssets(tuple(
            _glow(color, 128, ring=False)
            for color in (ctx.palette.primary, ctx.palette.secondary)
        ))

    def eval(self, t: float, ctx: RenderContext) -> FilterState:
        if self.params["strength"] == 0:
            return FilterState()
        phase = math.tau * (t / self.params["period"] % 1)
        return FilterState(tuple(
            FilterSprite(
                i, ctx.width * (.5 + .42 * math.cos(phase + i * math.pi)),
                ctx.height * (.5 + .35 * math.sin(phase + i * math.pi)),
                self.params["size"] * (1 + .08 * math.sin(phase + i)),
                self.params["strength"] * (.75 + .25 * math.sin(phase + i) ** 2),
            ) for i in range(2)
        ))


@register(KIND_FILTER)
class BokehFilter(LightLeakFilter):
    """固定种子光斑沿背景向上漂浮，循环边界以零透明度衔接。"""

    anim_type: ClassVar[str] = "bokeh"
    label: ClassVar[str] = "漂浮光斑"
    description: ClassVar[str] = "柔和光斑缓慢上浮并淡入淡出；随机种子固定，拖动时间轴可精确复现。"
    display_order: ClassVar[int] = 20

    @classmethod
    def params_schema(cls) -> list[ParamSpec]:
        return [
            ParamSpec("strength", "滤镜强度", "float", .45, 0, 1),
            ParamSpec("period", "运动周期 (秒)", "float", 20, 4, 60),
            ParamSpec("count", "光斑数量", "int", 24, 4, 64),
            ParamSpec("size", "光斑大小 (px)", "int", 90, 20, 240),
            ParamSpec("seed", "随机种子", "int", 42, 0, 99999),
        ]

    def prepare(self, ctx: RenderContext) -> FilterAssets:
        rng = random.Random(self.params["seed"])
        return FilterAssets(
            tuple(_glow(color, 64, ring=True)
                  for color in (ctx.palette.primary, ctx.palette.secondary)),
            tuple(tuple(rng.random() for _ in range(4))
                  for _ in range(self.params["count"])),
        )

    def eval(self, t: float, ctx: RenderContext) -> FilterState:
        if self.params["strength"] == 0:
            return FilterState()
        assets = cast(FilterAssets, ctx.assets[KIND_FILTER])
        items = []
        for i, (x, offset, size, drift) in enumerate(assets.seeds):
            phase = (t / self.params["period"] + offset) % 1
            diameter = self.params["size"] * (.5 + size)
            items.append(FilterSprite(
                i % 2, x * ctx.width + 40 * math.sin(math.tau * phase + drift * math.tau),
                ctx.height + diameter - phase * (ctx.height + 2 * diameter),
                diameter, self.params["strength"] * math.sin(math.pi * phase) ** 2,
            ))
        return FilterState(tuple(items))
