"""取色测试：固定种子确定性、纯色退化、近白边框过滤、歌词区对比度选色。"""

import numpy as np
from PIL import Image

from app.core.color import (
    contrast_ratio,
    extract_palette,
    hex_to_rgb,
    pick_lyric_colors,
    rgb_to_hex,
)


def _gradient_cover() -> Image.Image:
    w = np.linspace(0, 1, 128)
    arr = (
        np.stack([w * 255, np.zeros(128), (1 - w) * 255], -1) + np.zeros((128, 128, 3))
    ).astype("uint8")
    return Image.fromarray(arr, "RGB")


def test_extract_palette_deterministic():
    img = _gradient_cover()
    p1 = extract_palette(img)
    p2 = extract_palette(img)
    assert p1 == p2


def test_primary_secondary_hue_distance():
    palette = extract_palette(_gradient_cover())
    # 渐变两端为红/蓝系，主辅色应拉开色相差
    assert palette.primary != palette.secondary


def test_solid_color_degenerates():
    img = Image.new("RGB", (100, 100), (10, 200, 100))
    palette = extract_palette(img)
    assert palette.primary == (10, 200, 100)
    assert palette.secondary == (10, 200, 100)


def test_near_white_frame_filtered():
    arr = np.full((64, 64, 3), 250, dtype="uint8")
    arr[16:48, 16:48] = (200, 40, 60)
    palette = extract_palette(Image.fromarray(arr, "RGB"))
    assert palette.primary == (200, 40, 60)


def test_hex_roundtrip():
    assert rgb_to_hex(hex_to_rgb("#7FD1F5")) == "#7FD1F5"
    assert rgb_to_hex(hex_to_rgb("#abc")) == "#AABBCC"
    assert hex_to_rgb("#ZZZZZZ") == (255, 255, 255)  # 非法回退白
    assert hex_to_rgb("#FFFFFF80") == (255, 255, 255)  # RRGGBBAA 取前 6 位
    assert hex_to_rgb("#80FFFF") == (128, 255, 255)


def test_contrast_ratio_bounds():
    assert contrast_ratio((0, 0, 0), (255, 255, 255)) > 20.0
    assert contrast_ratio((128, 128, 128), (128, 128, 128)) == 1.0


def test_pick_lyric_colors_dark_bg():
    text, stroke = pick_lyric_colors(None)
    assert text == (255, 255, 255)  # 深底白字
    assert sum(stroke) < sum(text)


def test_pick_lyric_colors_light_bg():
    img = Image.new("RGB", (64, 64), (240, 240, 240))
    text, _stroke = pick_lyric_colors(img)
    assert text == (16, 16, 20)  # 浅底深字
