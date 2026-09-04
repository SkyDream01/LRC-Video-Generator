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


def _render(state, gui_assets) -> QImage:
    img = QImage(1920, 1080, QImage.Format.Format_RGB888)
    img.fill(Qt.GlobalColor.black)
    painter = QPainter(img)
    try:
        composite(painter, state, gui_assets)
    finally:
        painter.end()
    return img


LYRC = "[00:01.00]Hello world\n[00:01.00]你好世界\n[00:05.00]Second line\n"


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
