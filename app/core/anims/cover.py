"""封面动画：静态展示（含倒影）/ 黑胶唱片旋转。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import ClassVar, cast

from ..context import RenderContext
from ..prepare import (
    PreparedBitmap,
    make_cover_texture,
    make_disc_texture,
    make_reflection_bitmap,
)
from .base import KIND_COVER, BaseLayer, ParamSpec, clamp, register


@dataclass(frozen=True)
class CoverState:
    """封面帧状态：唱片角度（度）与倒影透明度。"""

    angle: float = 0.0
    reflection_alpha: float = 0.0


@dataclass
class CoverAssets:
    """封面贴图资源（逻辑尺寸 = cover_rect 宽高）。"""

    face: PreparedBitmap | None
    reflection: PreparedBitmap | None
    reflection_gap: float = 24.0
    disc: bool = False
    size: float = 0.0


@register(KIND_COVER)
class StaticCover(BaseLayer):
    """静态展示：封面方图 + 柔和倒影（呼吸微动）。"""

    kind: ClassVar[str] = KIND_COVER
    anim_type: ClassVar[str] = "static"
    label: ClassVar[str] = "静态展示"

    def prepare(self, ctx: RenderContext) -> CoverAssets:
        size = ctx.layout.cover_rect[2]
        if ctx.cover is None:
            return CoverAssets(face=None, reflection=None, size=size)
        face = make_cover_texture(ctx.cover, size)
        reflection = make_reflection_bitmap(face, height_ratio=0.30, alpha0=0.30)
        return CoverAssets(face=face, reflection=reflection, size=size)

    def eval(self, t: float, ctx: RenderContext) -> CoverState:
        assets = cast(CoverAssets, ctx.assets[KIND_COVER])
        if assets.face is None:
            return CoverState()
        # 倒影呼吸：0.5~0.6 缓慢波动
        return CoverState(
            angle=0.0, reflection_alpha=0.55 + 0.05 * math.sin(2.0 * math.pi * t / 6.0)
        )


@register(KIND_COVER)
class DiscRotate(BaseLayer):
    """黑胶唱片旋转：composite 内 QPainter.rotate 小贴图。"""

    kind: ClassVar[str] = KIND_COVER
    anim_type: ClassVar[str] = "disc_rotate"
    label: ClassVar[str] = "黑胶唱片"

    @classmethod
    def params_schema(cls) -> list[ParamSpec]:
        return [ParamSpec("rpm", "转速 (RPM)", "float", 33.3, 5.0, 78.0)]

    def prepare(self, ctx: RenderContext) -> CoverAssets:
        size = ctx.layout.cover_rect[2]
        if ctx.cover is None:
            return CoverAssets(face=None, reflection=None, size=size, disc=True)
        face = make_disc_texture(ctx.cover, size)
        reflection = make_reflection_bitmap(face, height_ratio=0.26, alpha0=0.22)
        return CoverAssets(face=face, reflection=reflection, disc=True, size=size)

    def eval(self, t: float, ctx: RenderContext) -> CoverState:
        assets = cast(CoverAssets, ctx.assets[KIND_COVER])
        if assets.face is None:
            return CoverState()
        rpm = self.params["rpm"]
        angle = (t * rpm * 6.0) % 360.0
        return CoverState(angle=angle, reflection_alpha=clamp(0.30))
