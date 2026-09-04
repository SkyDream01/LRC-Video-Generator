"""色彩提取：NumPy 手写 K-Means 取主色/辅色 + 歌词区域对比度选色。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image

KMEANS_K = 5
KMEANS_MAX_ITER = 20
SEED = 0

# 采样过滤阈值：去掉近黑/近白/低饱和像素（边框、letterbox）
SAT_MIN = 0.10
L_MIN = 0.08
L_MAX = 0.92

# 辅色与主色的最小色相差（度）
SECONDARY_HUE_DIFF_DEG = 30.0

RGB = tuple[int, int, int]


@dataclass(frozen=True)
class Palette:
    """取色结果。颜色均为 RGB 0-255 元组；clusters 为 (rgb, 权重) 列表，按评分降序。"""

    primary: RGB
    secondary: RGB
    clusters: tuple[tuple[RGB, float], ...]


def hex_to_rgb(hex_color: str) -> RGB:
    """'#RRGGBB' → (r, g, b)；非法输入回退白色。"""
    if not isinstance(hex_color, str):
        return (255, 255, 255)
    s = hex_color.strip().lstrip("#")
    if len(s) == 8:  # 含 alpha 的 #RRGGBBAA，取前 6 位
        s = s[:6]
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    try:
        r, g, b = (int(s[i : i + 2], 16) for i in (0, 2, 4))
    except (IndexError, TypeError, ValueError):
        return (255, 255, 255)
    return (r, g, b)


def rgb_to_hex(rgb: RGB) -> str:
    """(r, g, b) → '#RRGGBB'。"""
    try:
        r, g, b = (
            max(0, min(255, round(float(c))))
            for c in rgb
        )
    except (TypeError, ValueError):
        return "#FFFFFF"
    return f"#{r:02X}{g:02X}{b:02X}"


def _to_hsl_arrays(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """RGB 0-255 浮点数组 → (H, S, L) 0-1 数组（饱和度取 HSV 近似）。"""
    rr, gg, bb = rgb[..., 0] / 255.0, rgb[..., 1] / 255.0, rgb[..., 2] / 255.0
    mx = np.maximum(np.maximum(rr, gg), bb)
    mn = np.minimum(np.minimum(rr, gg), bb)
    lum = (mx + mn) / 2.0
    d = mx - mn
    s = np.divide(d, mx, out=np.zeros_like(d), where=mx > 1e-9)
    d_safe = np.where(d > 1e-9, d, 1.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        h = (
            np.select(
                [
                    (mx == rr) & (gg >= bb),
                    (mx == rr) & (gg < bb),
                    mx == gg,
                    mx == bb,
                ],
                [
                    ((gg - bb) / d_safe) % 6.0,
                    (gg - bb) / d_safe + 6.0,
                    (bb - rr) / d_safe + 2.0,
                    (rr - gg) / d_safe + 4.0,
                ],
                default=0.0,
            )
            / 6.0
        )
    return np.where(d > 1e-9, h, 0.0), s, lum


def _kmeans(samples: np.ndarray, k: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """手写 K-Means：返回 (簇心 k×3 uint8, 簇权重 k)。固定种子保证确定性。"""
    n = len(samples)
    if n == 0:
        raise ValueError("K-Means 没有可用样本")
    k = max(1, min(int(k), n))
    rng = np.random.default_rng(seed)
    centers = samples[rng.choice(n, size=k, replace=False)].astype(np.float64)
    for _ in range(KMEANS_MAX_ITER):
        dists = ((samples[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
        assign = dists.argmin(axis=1)
        new_centers = centers.copy()
        for j in range(k):
            mask = assign == j
            if mask.any():
                new_centers[j] = samples[mask].mean(axis=0)
        converged = np.allclose(new_centers, centers, atol=0.5)
        centers = new_centers
        if converged:
            break
    dists = ((samples[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
    assign = dists.argmin(axis=1)
    weights = np.bincount(assign, minlength=k).astype(np.float64)
    weights /= max(1.0, weights.sum())
    return np.clip(np.rint(centers), 0, 255).astype(np.uint8), weights


def _hue_diff(h1: float, h2: float) -> float:
    d = abs(h1 - h2) % 1.0
    return min(d, 1.0 - d) * 360.0


def extract_palette(img: Image.Image, k: int = KMEANS_K, seed: int = SEED) -> Palette:
    """从封面提取主色/辅色。纯色等退化输入回退该色本身。"""
    if not isinstance(img, Image.Image) or img.width <= 0 or img.height <= 0:
        fallback = (24, 26, 34)
        return Palette(
            primary=fallback, secondary=fallback, clusters=((fallback, 1.0),)
        )

    # 透明封面先合成到深色底，避免透明区域被误当成纯黑主色。
    if "A" in img.getbands():
        rgba = np.asarray(img.convert("RGBA"), dtype=np.float64)
        alpha = rgba[..., 3:4] / 255.0
        rgb = np.rint(
            rgba[..., :3] * alpha
            + np.asarray((24, 26, 34), dtype=np.float64) * (1.0 - alpha)
        )
        small = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")
    else:
        small = img.convert("RGB")
    small.thumbnail((64, 64))
    pixels = np.asarray(small, dtype=np.float64).reshape(-1, 3)

    _, light, sat = _to_hsl_arrays(pixels)
    mask = (sat >= SAT_MIN) & (light >= L_MIN) & (light <= L_MAX)
    samples = (
        pixels[mask] if mask.sum() >= max(k, 16) else pixels
    )  # 过滤后过少则回退全量

    centers, weights = _kmeans(samples, k, seed)
    ch, _, cs = _to_hsl_arrays(centers.astype(np.float64))

    # 评分：0.5·饱和度 + 0.3·亮度适中 + 0.2·簇面积；转 Python 标量便于纯逻辑分支
    mid_light = 1.0 - np.abs(_to_hsl_arrays(centers.astype(np.float64))[2] - 0.5) * 2.0
    score = 0.5 * cs + 0.3 * mid_light + 0.2 * weights
    # 空簇的初始中心可能来自画面中的偶然颜色，不能让它成为主色/辅色。
    if np.any(weights > 0):
        score = np.where(weights > 0, score, -np.inf)
    order: list[int] = np.argsort(-score).tolist()
    valid_order = [i for i in order if weights[i] > 0] or order
    ch_list: list[float] = ch.tolist()
    weights_list: list[float] = weights.tolist()

    def rgb_of(i: int) -> RGB:
        vals = centers[i].tolist()
        return (int(vals[0]), int(vals[1]), int(vals[2]))

    primary_i = order[0]
    secondary_i = primary_i
    for j in valid_order[1:]:
        if _hue_diff(ch_list[primary_i], ch_list[j]) >= SECONDARY_HUE_DIFF_DEG:
            secondary_i = j
            break
    else:
        secondary_i = valid_order[-1] if len(valid_order) > 1 else primary_i

    clusters = tuple((rgb_of(i), weights_list[i]) for i in order)
    return Palette(
        primary=rgb_of(primary_i), secondary=rgb_of(secondary_i), clusters=clusters
    )


def _relative_luminance(rgb: RGB) -> float:
    """WCAG 相对亮度（0-1）。"""

    def chan(c: float) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (chan(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: RGB, b: RGB) -> float:
    """WCAG 对比度（1-21）。"""
    la, lb = _relative_luminance(a), _relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def pick_lyric_colors(bg_sample: Image.Image | None) -> tuple[RGB, RGB]:
    """歌词区域背景采样 → (文字色, 描边色)。浅底用深字浅描边，深底用白字深描边（对比度优先）。"""
    mean_rgb: RGB = (16, 16, 24)
    if isinstance(bg_sample, Image.Image) and bg_sample.width > 0 and bg_sample.height > 0:
        arr = np.asarray(
            bg_sample.convert("RGB").resize((32, 32), Image.Resampling.BILINEAR),
            dtype=np.float64,
        )
        mean = arr.reshape(-1, 3).mean(axis=0).round().astype(np.int64).tolist()
        mean_rgb = (int(mean[0]), int(mean[1]), int(mean[2]))

    white: RGB = (255, 255, 255)
    black: RGB = (16, 16, 20)
    if contrast_ratio(white, mean_rgb) >= contrast_ratio(black, mean_rgb):
        return white, black
    return black, (235, 235, 240)


def palette_from_manual(primary_hex: str, secondary_hex: str) -> Palette:
    """手动取色：用户覆盖主色/辅色。"""
    return Palette(
        primary=hex_to_rgb(primary_hex),
        secondary=hex_to_rgb(secondary_hex),
        clusters=(),
    )


__all__ = [
    "KMEANS_K",
    "Palette",
    "SEED",
    "contrast_ratio",
    "extract_palette",
    "hex_to_rgb",
    "palette_from_manual",
    "pick_lyric_colors",
    "rgb_to_hex",
]
