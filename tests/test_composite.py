"""composite 金帧测试：离屏 QImage 渲染（qt 标记，无 Qt 自动 skip）。"""

import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.qt

import numpy as np  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402

from app.core.context import build_context  # noqa: E402
from app.core.project import KProj  # noqa: E402
from app.core.scene import Scene  # noqa: E402
from app.gui.composite import (  # noqa: E402
    GuiAssets,
    composite,
    qimage_rgb24_buffer,
    qimage_to_rgb_array,
)


def _make_scene(lrc: str, anims: dict[str, str] | None = None):
    from PIL import Image

    project = KProj()
    for kind, anim_type in (anims or {}).items():
        getattr(project.animations, kind).type = anim_type
    ctx = build_context(project, ".", lrc_text=lrc, duration_override=10.0)
    ctx.cover = Image.new("RGB", (256, 256), (200, 60, 60))
    scene = Scene(ctx)
    scene.prepare()
    return scene, GuiAssets.from_context(ctx)


def _render(state, gui_assets, fmt=QImage.Format.Format_RGB888) -> QImage:
    img = QImage(1920, 1080, fmt)
    img.fill(Qt.GlobalColor.black)
    painter = QPainter(img)
    try:
        composite(painter, state, gui_assets)
    finally:
        painter.end()
    return img


LYRC = "[00:01.00]Hello world\n[00:01.00]你好世界\n[00:05.00]Second line\n"


@pytest.mark.parametrize("background", [
    "static_blur", "gradient_wave", "wave_blur", "breath_zoom",
])
def test_native_assets_match_original_pixel_formats(background, monkeypatch):
    """原生贴图格式在旋转、半透明歌词和缩放下保持金帧容差。"""
    import importlib

    module = importlib.import_module("app.gui.composite")
    scene, optimized = _make_scene(
        LYRC, {"background": background, "cover": "disc_rotate", "lyrics": "fade"}
    )

    def original_bitmap(pb):
        if pb is None or pb.pixels.size == 0:
            return None
        return module.GuiBitmap(
            module.numpy_to_qimage(pb.pixels), *pb.origin, pb.width, pb.height
        )

    monkeypatch.setattr(module, "_gui_bitmap", original_bitmap)
    original = GuiAssets.from_context(scene.ctx)
    original.bg_image = module.numpy_to_qimage(scene.ctx.assets["background"].bitmap)
    for t in (0.0, 1.05, 2.0, 5.2):
        a = qimage_to_rgb_array(_render(scene.eval(t), original)).astype(np.int16)
        b = qimage_to_rgb_array(_render(scene.eval(t), optimized)).astype(np.int16)
        diff = np.abs(a - b)
        # 8 位预乘 alpha 的舍入只影响边缘，整帧平均误差应远小于 1。
        assert diff.max() <= 8
        assert diff.mean() < 0.1


def test_composite_produces_non_black_frame():
    scene, gui = _make_scene(LYRC)
    img = _render(scene.eval(2.0), gui)
    arr = qimage_to_rgb_array(img)
    assert arr.mean() > 5.0  # 背景 + 封面 + 歌词，绝非全黑


def test_composite_deterministic_same_t():
    scene, gui = _make_scene(LYRC)
    a = _render(scene.eval(2.0), gui)
    b = _render(scene.eval(2.0), gui)
    assert a == b  # QImage 逐像素相等


def test_word_highlight_pixels_progress_and_match_plain_at_end():
    from dataclasses import replace

    scene, gui = _make_scene("[00:01]<00:02>聪<00:04>明<00:06>\n[00:01]译文")
    state = scene.eval(3)
    item = state.lyrics.items[0]

    def render_progress(progress):
        lyrics = replace(state.lyrics, items=(replace(item, word_progress=progress),))
        return qimage_to_rgb_array(_render(replace(state, lyrics=lyrics), gui)).astype(int)

    pending, partial, complete, plain = (render_progress(p) for p in (0, 0.5, 2, None))
    np.testing.assert_array_equal(complete, plain)
    main, sub, sub_offset = gui.lyric_lines[0]
    seg = main[0]
    x, y = round(item.x + seg.ox), round(item.y + seg.oy)
    split = round(seg.char_edges[1])
    assert np.abs(partial[y:y+int(seg.h), x:x+split] - pending[y:y+int(seg.h), x:x+split]).sum() > 0
    np.testing.assert_array_equal(partial[y:y+int(seg.h), x+split:x+int(seg.w)],
                                  pending[y:y+int(seg.h), x+split:x+int(seg.w)])
    for seg in sub:
        x, y = round(item.x + seg.ox), round(item.y + sub_offset + seg.oy)
        np.testing.assert_array_equal(pending[y:y+int(seg.h), x:x+int(seg.w)],
                                      complete[y:y+int(seg.h), x:x+int(seg.w)])


def test_wrapped_word_highlight_finishes_first_row_before_second():
    from dataclasses import replace

    text = "聪明的你告诉我什么是真理" * 4
    lrc = "[00:01]" + "".join(f"<00:{i + 1:02d}>{char}" for i, char in enumerate(text))
    scene, gui = _make_scene(lrc)
    state = scene.eval(3)
    item = state.lyrics.items[0]
    main, _, _ = gui.lyric_lines[0]
    assert len(main) == 2
    first_done = replace(item, word_progress=float(main[1].char_start))
    result = qimage_to_rgb_array(_render(replace(state, lyrics=replace(state.lyrics, items=(first_done,))), gui))
    plain = qimage_to_rgb_array(_render(replace(state, lyrics=replace(state.lyrics, items=(replace(item, word_progress=None),))), gui))
    for index, seg in enumerate(main):
        x, y = round(item.x + seg.ox), round(item.y + seg.oy)
        a, b = result[y:y+int(seg.h), x:x+int(seg.w)], plain[y:y+int(seg.h), x:x+int(seg.w)]
        if index == 0:
            np.testing.assert_array_equal(a, b)
        else:
            assert np.abs(a.astype(int) - b.astype(int)).sum() > 0


def test_lyrics_drawn_inside_lyrics_rect():
    with_lrc, gui = _make_scene(LYRC)
    without_lrc, gui_empty = _make_scene("")
    rect = gui.lyric_rect
    x0, y0, w, h = (int(v) for v in rect)

    arr_with = qimage_to_rgb_array(_render(with_lrc.eval(2.0), gui))
    arr_without = qimage_to_rgb_array(_render(without_lrc.eval(2.0), gui_empty))
    region_diff = np.abs(
        arr_with[y0 : y0 + h, x0 : x0 + w].astype(int)
        - arr_without[y0 : y0 + h, x0 : x0 + w].astype(int)
    ).sum()
    assert region_diff > 0  # 歌词矩形内有差异 → 歌词被绘制

    # 封面区域（无歌词）两帧一致
    cover = gui.cover_rect
    cx0, cy0, cw, ch = (int(v) for v in cover)
    cover_diff = np.abs(
        arr_with[cy0 : cy0 + ch, cx0 : cx0 + cw].astype(int)
        - arr_without[cy0 : cy0 + ch, cx0 : cx0 + cw].astype(int)
    ).sum()
    assert cover_diff == 0


def test_disc_rotation_changes_cover_area():
    scene, gui = _make_scene(LYRC, anims={"cover": "disc_rotate"})
    a = qimage_to_rgb_array(_render(scene.eval(0.0), gui))
    b = qimage_to_rgb_array(_render(scene.eval(1.0), gui))
    cx0, cy0, cw, ch = (int(v) for v in gui.cover_rect)
    assert (
        np.abs(
            a[cy0 : cy0 + ch, cx0 : cx0 + cw].astype(int)
            - b[cy0 : cy0 + ch, cx0 : cx0 + cw].astype(int)
        ).sum()
        > 0
    )


@pytest.mark.parametrize("rpm", [0.6, -0.6, 0.0])
def test_celestial_album_rotates_with_ornament(rpm):
    from PIL import Image

    scene, _ = _make_scene("", {"cover": "celestial"})
    scene.ctx.cover = Image.new("RGB", (256, 256), (220, 30, 30))
    scene.ctx.cover.paste((30, 60, 220), (128, 0, 256, 256))
    scene.ctx.project.animations.cover.params["rpm"] = rpm
    scene = Scene(scene.ctx)
    scene.prepare()
    gui = GuiAssets.from_context(scene.ctx)
    before = qimage_to_rgb_array(_render(scene.eval(0.0), gui))
    after = qimage_to_rgb_array(_render(scene.eval(25.0), gui))
    x, y, w, h = gui.cover_rect
    cx, cy = round(x + w / 2), round(y + h / 2)
    offset = round(w * 0.15)
    # 在专辑内部采样，避免将外圈装饰的转动误判为图片转动。
    assert before[cy, cx - offset, 0] > 180
    if rpm > 0:
        assert after[cy + offset, cx - offset, 2] > 180
        assert after[cy - offset, cx + offset, 0] > 180
    elif rpm < 0:
        assert after[cy + offset, cx + offset, 0] > 180
        assert after[cy - offset, cx - offset, 2] > 180
    else:
        np.testing.assert_array_equal(
            before[cy-offset:cy+offset, cx-offset:cx+offset],
            after[cy-offset:cy+offset, cx-offset:cx+offset],
        )


def test_numpy_to_qimage_roundtrip_alpha():
    from app.gui.composite import numpy_to_qimage

    arr = np.zeros((8, 6, 4), dtype=np.uint8)
    arr[..., 0] = 200
    arr[..., 3] = 128
    img = numpy_to_qimage(arr)
    assert img.width() == 6 and img.height() == 8
    assert img.hasAlphaChannel()
    assert img.pixelColor(0, 0).red() == 200
    assert img.pixelColor(0, 0).alpha() == 128


def test_qimage_rgb24_buffer_is_zero_copy_when_rows_are_tight():
    img = QImage(4, 2, QImage.Format.Format_RGB888)
    img.fill(Qt.GlobalColor.black)

    frame, scratch = qimage_rgb24_buffer(img)

    assert scratch is None
    assert len(frame) == 4 * 2 * 3
    assert frame.tobytes() == b"\0" * (4 * 2 * 3)


def test_qimage_rgb24_buffer_reuses_scratch_for_padded_rows():
    img = QImage(2, 2, QImage.Format.Format_RGB888)
    img.fill(Qt.GlobalColor.black)
    img.setPixelColor(0, 0, QColor(255, 0, 0))
    img.setPixelColor(1, 0, QColor(0, 255, 0))
    img.setPixelColor(0, 1, QColor(0, 0, 255))
    img.setPixelColor(1, 1, QColor(255, 255, 255))

    first, scratch = qimage_rgb24_buffer(img)
    second, reused = qimage_rgb24_buffer(img, scratch)

    assert scratch is not None
    assert reused is scratch
    assert first.tobytes() == second.tobytes()
    assert first.tobytes() == bytes(
        (
            255,
            0,
            0,
            0,
            255,
            0,
            0,
            0,
            255,
            255,
            255,
            255,
        )
    )


@pytest.mark.parametrize(
    "kind,name",
    [
        ("background", "breath_zoom"),
        ("cover", "breath"),
        ("cover", "float"),
        ("lyrics", "flip_3d"),
        ("cover", "rock_3d"),
        ("lyrics", "slide"),
        ("lyrics", "reveal"),
    ],
)
def test_new_effects_change_pixels_and_restore_painter(kind, name):
    from PIL import Image

    scene, _ = _make_scene(LYRC, {kind: name})
    pixels = np.zeros((128, 128, 3), dtype=np.uint8)
    pixels[:, :64] = (240, 80, 60)
    pixels[:, 64:] = (40, 100, 220)
    scene.ctx.cover = Image.fromarray(pixels)
    scene.prepare()
    gui = GuiAssets.from_context(scene.ctx)
    a = scene.eval(1.05)
    b = scene.eval(1.3)
    # 只更换待测图层状态，隔离其他层的动画变化。
    from dataclasses import replace

    field = {"background": "bg", "cover": "cover", "lyrics": "lyrics"}[kind]
    b = replace(a, **{field: getattr(b, field)})
    assert _render(a, gui) != _render(b, gui)
    assert _render(a, gui) == _render(a, gui)
    img = QImage(960, 540, QImage.Format.Format_RGB888)
    painter = QPainter(img)
    painter.scale(0.5, 0.5)
    transform = painter.transform()
    composite(painter, a, gui)
    assert painter.transform() == transform
    assert painter.opacity() == 1
    assert not painter.hasClipping()
    painter.end()


@pytest.mark.parametrize("axis", ["x", "y"])
def test_perspective_projects_plane_and_preserves_scaled_center(axis):
    from app.gui.composite import _perspective
    from PySide6.QtCore import QPointF
    import math

    image = QImage(400, 400, QImage.Format.Format_RGB888)
    painter = QPainter(image)
    try:
        painter.scale(0.5, 0.5)
        _perspective(painter, 200, 200, 30 if axis == "x" else 0,
                     30 if axis == "y" else 0, 1000)
        transform = painter.worldTransform()
        center = transform.map(QPointF(200, 200))
        assert center.x() == pytest.approx(100)
        assert center.y() == pytest.approx(100)
        point = transform.map(QPointF(300, 300))
        denominator = 1 + (0.05 if axis == "y" else -0.05)
        expected_x = 100 * (math.cos(math.pi / 6) if axis == "y" else 1)
        expected_y = 100 * (math.cos(math.pi / 6) if axis == "x" else 1)
        assert point.x() == pytest.approx((200 + expected_x / denominator) / 2)
        assert point.y() == pytest.approx((200 + expected_y / denominator) / 2)
    finally:
        painter.end()


def test_celestial_arc_composite():
    scene, gui = _make_scene(LYRC, {"background": "midnight", "cover": "celestial", "lyrics": "arc"})
    first = _render(scene.eval(2), gui)
    assert first == _render(scene.eval(2), gui)
    assert first != _render(scene.eval(3), gui)
    assert gui.cover_ornament is not None
    assert gui.arc_lyrics


from dataclasses import replace
from app.core.anims.base import ANIM_REGISTRY
from app.core.context import compute_layout


@pytest.mark.parametrize("kind,name", [(k, n) for k in ANIM_REGISTRY for n in ANIM_REGISTRY[k]])
def test_native_export_target_matches_rgb24(kind, name):
    """原生导出目标与原 RGB24 合成在所有动画下保持像素容差。"""
    scene, gui = _make_scene(LYRC, {kind: name})
    for t in (1.05, 2.0, 5.2):
        state = scene.eval(t)
        original = qimage_to_rgb_array(_render(state, gui)).astype(np.int16)
        native = _render(state, gui, QImage.Format.Format_RGB32)
        converted = native.convertToFormat(QImage.Format.Format_RGB888)
        diff = np.abs(original - qimage_to_rgb_array(converted).astype(np.int16))
        assert diff.max() <= 8
        assert diff.mean() < 0.1


@pytest.mark.parametrize("width", [2, 6, 1920])
def test_native_export_buffer_layout(width):
    """RGB32 无行填充，字节序和 FFmpeg bgr0/0rgb 输入一致。"""
    import sys

    img = QImage(width, 2, QImage.Format.Format_RGB32)
    img.fill(QColor(17, 73, 201))
    raw = memoryview(img.constBits()).cast("B")
    pixel = bytes((201, 73, 17, 255)) if sys.byteorder == "little" else bytes((255, 17, 73, 201))
    assert len(raw) == width * 2 * 4
    assert bytes(raw) == pixel * (width * 2)


@pytest.mark.parametrize("kind,name", [(k, n) for k in ("lyrics", "cover") for n in ANIM_REGISTRY[k]])
@pytest.mark.parametrize("preset,offset", [("landscape_mv", 40), ("landscape_mv_reversed", -40)])
def test_all_effects_follow_layout_pixels(kind, name, preset, offset):
    scene, _ = _make_scene(LYRC, {kind: name})
    scene.ctx.layout = compute_layout(1920, 1080, preset)
    scene.prepare()
    gui = GuiAssets.from_context(scene.ctx)
    gui.bg_image = None
    gui.meta_segments = []
    if kind == "lyrics":
        gui.cover_face = None
    else:
        gui.lyric_lines = []
    before = scene.eval(1.2)
    a = qimage_to_rgb_array(_render(before, gui))
    # 圆弧同步平移保留半径；其余动画独立移动，并反向移动另一图层。
    cover_dx = offset if kind == "cover" or name == "arc" else -offset
    lyrics_dx = offset if kind == "lyrics" else -offset
    scene.ctx.layout = compute_layout(1920, 1080, preset, cover_dx, lyrics_dx)
    scene.prepare()
    shifted = GuiAssets.from_context(scene.ctx)
    shifted.bg_image = None
    shifted.meta_segments = []
    if kind == "lyrics":
        shifted.cover_face = None
    else:
        shifted.lyric_lines = []
    state = scene.eval(1.2)
    b = qimage_to_rgb_array(_render(state, shifted))
    assert a.max() > 0
    if offset > 0:
        diff = np.abs(a[:, :-offset].astype(int) - b[:, offset:].astype(int))
    else:
        diff = np.abs(a[:, -offset:].astype(int) - b[:, :offset].astype(int))
    assert diff.mean() < 0.02
    assert diff.max() <= 8
    # 预览的平移/缩放和裁剪不得被动画覆盖；同逻辑尺寸的离屏预览与导出逐像素一致。
    image = QImage(1960, 1120, QImage.Format.Format_RGB888)
    image.fill(Qt.GlobalColor.black)
    painter = QPainter(image)
    painter.translate(20, 20)
    painter.setClipRect(0, 0, 1920, 1080)
    transform = painter.transform()
    clip = painter.clipRegion()
    composite(painter, state, shifted)
    assert painter.transform() == transform
    assert painter.clipRegion() == clip
    painter.end()
    np.testing.assert_array_equal(qimage_to_rgb_array(image)[20:1100, 20:1940], b)


@pytest.mark.parametrize("preset", ["landscape_mv", "landscape_mv_reversed"])
def test_arc_bilingual_edges_and_caller_clip(preset):
    from app.gui.composite import GuiBitmap
    from app.core.anims.lyrics import LyricsState
    scene, _ = _make_scene(LYRC, {"lyrics": "arc"})
    scene.ctx.layout = compute_layout(1920, 1080, preset, 25, -25)
    scene.prepare()
    gui = GuiAssets.from_context(scene.ctx)
    gui.bg_image = None
    gui.cover_face = None
    gui.meta_segments = []
    def segment(width, height):
        img = QImage(width, height, QImage.Format.Format_RGB888)
        img.fill(Qt.GlobalColor.white)
        return GuiBitmap(img, -width/2, 0, width, height)
    gui.lyric_lines[0] = ([segment(200, 20)], [segment(300, 20)], 40)
    state = scene.eval(2)
    item = next(i for i in state.lyrics.items if i.index == 0)
    item = replace(item, y=400)
    state = replace(state, lyrics=LyricsState((item,), 0))
    arr = qimage_to_rgb_array(_render(state, gui))
    main = np.flatnonzero(arr[410, :, 0])
    sub = np.flatnonzero(arr[450, :, 0])
    if item.left_align:
        assert main[0] == sub[0] == round(item.x)
    else:
        assert main[-1] == sub[-1] == round(item.x)-1
    image = QImage(960, 540, QImage.Format.Format_RGB888)
    image.fill(Qt.GlobalColor.black)
    painter = QPainter(image)
    painter.scale(.5, .5)
    painter.setClipRect(round(item.x)-20, 400, 40, 20)
    composite(painter, state, gui)
    painter.end()
    clipped = qimage_to_rgb_array(image)
    assert clipped[200:210].max() > 0
    assert clipped[220:230].max() == 0
