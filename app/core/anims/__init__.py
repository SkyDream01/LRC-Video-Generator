"""动画层包：导入各模块以填充注册表（策略模式 + ANIM_REGISTRY）。"""

from .background import BgAssets, BgState, GradientWaveBG, StaticBlurBG, WaveBlurBG
from .base import (
    ANIM_REGISTRY,
    KIND_BACKGROUND,
    KIND_COVER,
    KIND_LYRICS,
    KINDS,
    BaseLayer,
    ParamSpec,
    clamp,
    layer_class,
)
from .cover import CoverAssets, CoverState, DiscRotate, StaticCover
from .lyrics import FadeLyrics, LyricItem, LyricsAssets, LyricsState, ScrollListLyrics

__all__ = [
    "ANIM_REGISTRY",
    "BaseLayer",
    "BgAssets",
    "BgState",
    "CoverAssets",
    "CoverState",
    "DiscRotate",
    "FadeLyrics",
    "GradientWaveBG",
    "KINDS",
    "KIND_BACKGROUND",
    "KIND_COVER",
    "KIND_LYRICS",
    "LyricItem",
    "LyricsAssets",
    "LyricsState",
    "ParamSpec",
    "ScrollListLyrics",
    "StaticBlurBG",
    "StaticCover",
    "WaveBlurBG",
    "clamp",
    "layer_class",
]
