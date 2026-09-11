"""动画层包：导入各模块以填充注册表（策略模式 + ANIM_REGISTRY）。"""

from .background import (
    BgAssets,
    BgState,
    BreathZoomBG,
    GradientWaveBG,
    StaticBlurBG,
    WaveBlurBG,
)
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
from .cover import (
    BreathCover,
    CoverAssets,
    CoverState,
    DiscRotate,
    FloatCover,
    StaticCover,
)
from .lyrics import (
    FadeLyrics,
    LyricItem,
    LyricsAssets,
    LyricsState,
    RevealLyrics,
    ScrollListLyrics,
    SlideLyrics,
)

__all__ = [
    "ANIM_REGISTRY",
    "KINDS",
    "KIND_BACKGROUND",
    "KIND_COVER",
    "KIND_LYRICS",
    "BaseLayer",
    "BgAssets",
    "BgState",
    "BreathCover",
    "BreathZoomBG",
    "CoverAssets",
    "CoverState",
    "DiscRotate",
    "FadeLyrics",
    "FloatCover",
    "GradientWaveBG",
    "LyricItem",
    "LyricsAssets",
    "LyricsState",
    "ParamSpec",
    "RevealLyrics",
    "ScrollListLyrics",
    "SlideLyrics",
    "StaticBlurBG",
    "StaticCover",
    "WaveBlurBG",
    "clamp",
    "layer_class",
]
