"""封面动画：静态展示 / 黑胶唱片 / 呼吸缩放 / 悬浮。"""

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
    scale: float = 1.0
    y_offset: float = 0.0
    tilt_x: float = 0.0
    tilt_y: float = 0.0


@dataclass
class CoverAssets:
    """封面贴图资源（逻辑尺寸 = cover_rect 宽高）。"""

    face: PreparedBitmap | None
    reflection: PreparedBitmap | None
    reflection_gap: float = 24.0
    disc: bool = False
    size: float = 0.0
    ornament: PreparedBitmap | None = None


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


@register(KIND_COVER)
class BreathCover(StaticCover):
    """封面与倒影同步柔和缩放。"""

    anim_type: ClassVar[str] = "breath"
    label: ClassVar[str] = "呼吸缩放"

    @classmethod
    def params_schema(cls) -> list[ParamSpec]:
        return [
            ParamSpec("period", "周期 (秒)", "float", 6.0, 1.0, 30.0),
            ParamSpec("amount", "缩放幅度", "float", 0.05, 0.0, 0.15),
        ]

    def eval(self, t: float, ctx: RenderContext) -> CoverState:
        pulse = (1.0 - math.cos(2.0 * math.pi * t / self.params["period"])) / 2.0
        return CoverState(
            reflection_alpha=0.55, scale=1.0 - self.params["amount"] * pulse
        )


@register(KIND_COVER)
class FloatCover(StaticCover):
    """封面与倒影沿竖直方向平滑悬浮。"""

    anim_type: ClassVar[str] = "float"
    label: ClassVar[str] = "悬浮"

    @classmethod
    def params_schema(cls) -> list[ParamSpec]:
        return [
            ParamSpec("period", "周期 (秒)", "float", 5.0, 1.0, 30.0),
            ParamSpec("distance", "悬浮距离 (px)", "float", 18.0, 0.0, 48.0),
        ]

    def eval(self, t: float, ctx: RenderContext) -> CoverState:
        offset = self.params["distance"] * math.sin(
            2.0 * math.pi * t / self.params["period"]
        )
        return CoverState(reflection_alpha=0.55, y_offset=offset)


@register(KIND_COVER)
class Rock3DCover(StaticCover):
    """封面绕水平、竖直轴周期摇摆，始终保持正面可见。"""

    anim_type: ClassVar[str] = "rock_3d"
    label: ClassVar[str] = "3D 摇摆"

    @classmethod
    def params_schema(cls) -> list[ParamSpec]:
        return [
            ParamSpec("period", "周期 (秒)", "float", 6.0, 1.0, 30.0),
            ParamSpec("angle", "摇摆角度 (度)", "float", 24.0, 0.0, 45.0),
        ]

    def eval(self, t: float, ctx: RenderContext) -> CoverState:
        phase = 2.0 * math.pi * t / self.params["period"]
        return CoverState(
            tilt_x=self.params["angle"] * 0.45 * math.cos(phase),
            tilt_y=self.params["angle"] * math.sin(phase),
        )


@register(KIND_COVER)
class CelestialCover(BaseLayer):
    """圆形专辑配透明齿轮星轨，封面与旋转装饰分别缓存。"""

    kind: ClassVar[str] = KIND_COVER
    anim_type: ClassVar[str] = "celestial"
    label: ClassVar[str] = "星轨齿轮"

    @classmethod
    def params_schema(cls) -> list[ParamSpec]:
        return [ParamSpec("rpm", "光环转速 (RPM)", "float", 0.6, -3.0, 3.0)]

    def prepare(self, ctx: RenderContext) -> CoverAssets:
        import numpy as np
        from PIL import Image, ImageDraw, ImageFilter, ImageOps

        size = int(ctx.layout.cover_rect[2])
        n = size * 2
        face = Image.new("RGBA", (n, n))
        diameter = round(n * 0.78)
        inset = (n - diameter) // 2
        if ctx.cover is not None:
            art = ImageOps.fit(ctx.cover.convert("RGBA"), (diameter, diameter))
            mask = Image.new("L", art.size)
            ImageDraw.Draw(mask).ellipse((1, 1, diameter-2, diameter-2), fill=255)
            art.putalpha(mask)
            face.alpha_composite(art, (inset, inset))
        ink = Image.new("RGBA", (n, n))
        draw = ImageDraw.Draw(ink)
        c = n / 2
        for radius, alpha in ((0.393, 170), (0.408, 85), (0.48, 55), (0.497, 30)):
            r = n * radius
            draw.ellipse((c-r, c-r, c+r, c+r), outline=(168, 222, 219, alpha), width=2)
        points = []
        for i in range(240):
            a = i * math.tau / 240
            r = n * (0.444 if i % 4 in (1, 2) else 0.433)
            points.append((c+r*math.cos(a), c+r*math.sin(a)))
        draw.line(points+[points[0]], fill=(165, 228, 216, 170), width=3)
        for i in range(72):
            a = i * math.tau / 72
            r1, r2 = n * 0.48, n * (0.491 if i % 6 == 0 else 0.485)
            draw.line((c+r1*math.cos(a), c+r1*math.sin(a),
                       c+r2*math.cos(a), c+r2*math.sin(a)), fill=(180, 216, 220, 100), width=2)
        for a, radius in ((-1.35, .095), (.95, .12), (1.30, .065)):
            gx, gy = c+n*.34*math.cos(a), c+n*.34*math.sin(a)
            r = n*radius
            teeth = []
            for i in range(96):
                angle = i*math.tau/96
                rr = r*(1 if i%4 in (1,2) else .91)
                teeth.append((gx+rr*math.cos(angle), gy+rr*math.sin(angle)))
            draw.line(teeth+[teeth[0]], fill=(181, 224, 215, 150), width=2)
            for ratio in (.72, .40):
                rr = r*ratio
                draw.ellipse((gx-rr, gy-rr, gx+rr, gy+rr), outline=(177, 225, 219, 100), width=2)
        glow = ink.filter(ImageFilter.GaussianBlur(9))
        glow.alpha_composite(ink)
        def bitmap(image):
            return PreparedBitmap(np.array(image.resize((size, size), Image.Resampling.LANCZOS)))
        return CoverAssets(bitmap(face), None, size=size, ornament=bitmap(glow))

    def eval(self, t: float, ctx: RenderContext) -> CoverState:
        return CoverState(angle=(t*self.params["rpm"]*6) % 360)
