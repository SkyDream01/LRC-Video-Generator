"""prepare 测试：紧 bbox 位图、超宽缩字/换行、背景与唱片贴图。"""

from typing import cast

import pytest
import numpy as np
from PIL import Image

from app.core.anims.lyrics import FadeLyrics, LyricsAssets
from app.core.context import build_context, lyric_colors_of
from app.core.prepare import (
    FontCache,
    cover_fill_resize,
    layout_text,
    make_cover_texture,
    make_disc_texture,
    make_gradient_wave_bg,
    make_reflection,
    make_static_blur_bg,
    make_wave_blur_bg,
)
from app.core.project import KProj


def _ctx(lrc: str = "[00:01.00]Hello"):
    return build_context(KProj(), ".", lrc_text=lrc, duration_override=5.0)


def test_rasterized_lyric_is_tight_bbox():
    ctx = _ctx("[00:01.00]Hi\n[00:02.00]There")
    assets = cast(LyricsAssets, FadeLyrics({}).prepare(ctx))
    for bm in assets.lines:
        for seg in bm.main:
            assert seg.width < 1920  # 紧 bbox，禁止全幅画布
            assert seg.width > 0 and seg.height > 0


def test_layout_text_shrinks_for_wide_line():
    ctx = _ctx()
    style = ctx.project.lyric_style
    color, stroke = lyric_colors_of(ctx)
    long_text = (
        "A very long lyric line that absolutely exceeds the lyrics area width for sure"
    )
    segs = layout_text(
        long_text,
        ctx.fonts,
        style.main_font,
        style.main_size,
        color,
        stroke,
        style.stroke_width,
        900.0,
    )
    assert segs  # 至少一段
    for seg in segs:
        assert seg.width <= 900 + 2  # 允许 ±2px 度量误差


def test_layout_text_wraps_cjk_to_two_lines():
    ctx = _ctx()
    style = ctx.project.lyric_style
    color, stroke = lyric_colors_of(ctx)
    text = "这是一句特别长的中文歌词用来验证自动换行策略是否生效继续加长一点"
    segs = layout_text(
        text,
        ctx.fonts,
        style.main_font,
        style.main_size,
        color,
        stroke,
        style.stroke_width,
        700.0,
    )
    assert len(segs) >= 2  # 换行生效
    assert all(seg.width <= 702 for seg in segs)


def test_ellipsis_clip_on_pathological_input():
    ctx = _ctx()
    style = ctx.project.lyric_style
    color, stroke = lyric_colors_of(ctx)
    text = "字" * 200  # 极端超长单字文本
    segs = layout_text(
        text, ctx.fonts, style.main_font, style.main_size, color, stroke, 0, 400.0
    )
    assert segs
    assert all(seg.width <= 402 for seg in segs)


def test_backgrounds_shapes():
    cover = Image.new("RGB", (300, 300), (90, 90, 200))
    static = make_static_blur_bg(cover, 1920, 1080)
    assert static.shape == (1080, 1920, 3)
    wave = make_gradient_wave_bg((127, 209, 245), (245, 200, 127), 1920, 1080)
    assert wave.shape == (270, 960, 3)  # 1/4 分辨率、2 周期宽
    wavy = make_wave_blur_bg(cover, 1920, 1080, 20.0)
    assert wavy.shape == (1120, 1920, 3)  # h + 2·amp
    assert make_static_blur_bg(None, 1920, 1080).shape == (1080, 1920, 3)


def test_gradient_wave_horizontally_tileable():
    bg = make_gradient_wave_bg((200, 60, 60), (60, 200, 120), 1920, 1080)
    # 首尾一个周期应近似相等（2 周期位图：左右边缘同相位）
    diff = np.abs(bg[:, 0].astype(int) - bg[:, bg.shape[1] // 2].astype(int)).mean()
    assert diff < 2.0


def test_disc_texture_circular_alpha():
    cover = Image.new("RGB", (200, 200), (200, 60, 60))
    disc = make_disc_texture(cover, 720)
    assert disc.pixels.shape == (720, 720, 4)
    assert disc.pixels[0, 0, 3] == 0  # 四角透明
    assert disc.pixels[360, 360, 3] == 255  # 中心不透明
    assert disc.pixels[0, 360, 3] < 255  # 边缘羽化


def test_cover_texture_and_reflection():
    cover = Image.new("RGB", (400, 250), (60, 120, 200))
    face = make_cover_texture(cover, 720)
    assert face.pixels.shape == (720, 720, 4)
    refl = make_reflection(face.pixels, height_ratio=0.3, alpha0=0.4)
    assert refl.shape[0] == round(720 * 0.3)
    assert refl[..., 3].max() <= round(0.4 * 255) + 1  # 倒影 alpha 渐隐封顶
    assert refl[0, :, 3].max() > refl[-1, :, 3].max()  # 顶部更实


def test_cover_fill_resize_covers_and_crops():
    img = Image.new("RGB", (100, 50), (10, 10, 10))
    out = cover_fill_resize(img, 200, 200)
    assert out.size == (200, 200)


def test_font_cache_fallback(monkeypatch, tmp_path):
    cache = FontCache(tmp_path)
    font = cache.get(None, 32)  # font/ 为空 → 系统字体或内置字体
    assert font is not None
    # 同 key 命中缓存
    assert cache.get(None, 32) is font


def test_timed_wrapped_lyrics_keep_character_mapping():
    text = "聪明的你告诉我什么是真理" * 4
    lrc = "[00:01]" + "".join(f"<00:{i + 1:02d}>{char}" for i, char in enumerate(text))
    ctx = _ctx(lrc)
    assets = FadeLyrics({}).prepare(ctx)
    segments = assets.lines[0].main
    assert len(segments) == 2
    for seg in segments:
        visible = seg.text.removesuffix("…")
        assert ctx.lyrics[0].text[seg.char_start:seg.char_start + len(visible)] == visible
        assert len(seg.char_edges) == len(seg.text) + 1
        assert seg.char_edges[0] == 0
        assert seg.char_edges[-1] == seg.width
        assert all(a <= b for a, b in zip(seg.char_edges, seg.char_edges[1:]))
        assert " " not in seg.text
    assert segments[1].char_start == len(segments[0].text)


@pytest.mark.parametrize("auto_extract", [True, False])
@pytest.mark.parametrize("background", ["#FFFFFF", "#101014"])
@pytest.mark.parametrize("main,sub,stroke", [
    ("#FFFFFF", "#C8C8C8", "#101014"),
    ("#FF0000", "#00FF00", "#101014"),
    ("#FFFFFF", "#0000FF", "#FF00FF"),
])
def test_selected_lyric_colors_survive_background_and_auto_extract(
    tmp_path, auto_extract, background, main, sub, stroke
):
    from app.core.color import hex_to_rgb
    from app.core.context import sub_colors_of

    Image.new("RGB", (64, 64), background).save(tmp_path / "cover.png")
    project = KProj()
    project.files.cover = "cover.png"
    project.colors.auto_extract = auto_extract
    project.lyric_style.main_color = main
    project.lyric_style.sub_color = sub
    project.lyric_style.stroke_color = stroke
    ctx = build_context(
        project, tmp_path,
        lrc_text="[00:01.00]Hello\n[00:01.00]World",
        duration_override=5.0,
    )
    assert lyric_colors_of(ctx) == (hex_to_rgb(main), hex_to_rgb(stroke))
    assert sub_colors_of(ctx) == (hex_to_rgb(sub), hex_to_rgb(stroke))
    assert ctx.project.lyric_style == project.lyric_style
    assert ctx.project.lyric_style is not project.lyric_style
    assets = cast(LyricsAssets, FadeLyrics({}).prepare(ctx))
    for segments, fill in [(assets.lines[0].main, main), (assets.lines[0].sub, sub)]:
        assert segments
        pixels = segments[0].pixels
        for color in (fill, stroke):
            expected = (*hex_to_rgb(color), 255)
            assert np.any(np.all(pixels == expected, axis=-1))
