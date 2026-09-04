"""Scene：组装三层动画，持有 prepare 缓存；eval(t) → SceneState（纯状态，无像素）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from .anims.background import BgState
from .anims.base import (
    KIND_BACKGROUND,
    KIND_COVER,
    KIND_LYRICS,
    BaseLayer,
    clamp,
    layer_class,
)
from .anims.cover import CoverState
from .anims.lyrics import LyricsState
from .context import RenderContext
from .prepare import PreparedBitmap, layout_text

# 元数据条字号与淡入时长
META_SIZE = 34
META_FADE_S = 1.2
# assets 字典中元数据条的键名
META_ASSETS_KEY = "meta"


@dataclass
class MetaAssets:
    """元数据条位图（可选叠加）。"""

    segments: list[PreparedBitmap]


@dataclass(frozen=True)
class SceneState:
    """一帧的完整动画状态（eval 纯函数输出，无像素）。"""

    t: float
    bg: BgState
    lyrics: LyricsState
    cover: CoverState
    meta_alpha: float
    current_line: int


class Scene:
    """按工程配置实例化三层动画并串联 prepare / eval。

    Scene 拥有 prepare 缓存（写入 ctx.assets）；层上不提供内部 render()，
    避免绕过缓存。预览与导出共享同一 Scene 实例与同一份 assets。
    """

    def __init__(self, ctx: RenderContext) -> None:
        self.ctx = ctx
        self.layers: dict[str, BaseLayer] = {}
        for kind in (KIND_BACKGROUND, KIND_LYRICS, KIND_COVER):
            spec = getattr(ctx.project.animations, kind)
            cls = layer_class(kind, spec.type)
            if cls is None:
                raise ValueError(f"动画类型未注册: {kind}/{spec.type}")
            self.layers[kind] = cls(spec.params)
        self._prepared = False

    @property
    def prepared(self) -> bool:
        return self._prepared

    def prepare(self) -> None:
        """光栅化所有图层资源（仅资源/参数变化时需要重跑）。"""
        for kind, layer in self.layers.items():
            self.ctx.assets[kind] = layer.prepare(self.ctx)
        self.ctx.assets[META_ASSETS_KEY] = self._prepare_meta()
        self._prepared = True

    def _prepare_meta(self) -> MetaAssets | None:
        text = self.ctx.meta_text
        if not text:
            return None
        style = self.ctx.project.lyric_style
        safe = self.ctx.layout.safe_area
        segments = layout_text(
            text,
            self.ctx.fonts,
            style.sub_font,
            META_SIZE,
            (235, 235, 240),
            (16, 16, 20),
            2,
            safe[2],
        )
        return MetaAssets(segments=segments) if segments else None

    def eval(self, t: float) -> SceneState:
        """纯函数：t 秒 → SceneState。必须先 prepare()。"""
        if not self._prepared:
            raise RuntimeError("Scene.eval 前必须先 prepare()")
        bg = cast(BgState, self.layers[KIND_BACKGROUND].eval(t, self.ctx))
        lyrics = cast(LyricsState, self.layers[KIND_LYRICS].eval(t, self.ctx))
        cover = cast(CoverState, self.layers[KIND_COVER].eval(t, self.ctx))
        meta_alpha = clamp(t / META_FADE_S) if self.ctx.meta_text else 0.0
        return SceneState(
            t=t,
            bg=bg,
            lyrics=lyrics,
            cover=cover,
            meta_alpha=meta_alpha,
            current_line=lyrics.current_index,
        )
