"""自定义左右布局与工程持久化。"""
import pytest
from app.core.context import compute_layout, build_context
from app.core.project import KProj, kproj_from_dict, kproj_to_dict


def test_default_and_reversed_layout():
    normal = compute_layout(1920, 1080)
    reverse = compute_layout(1920, 1080, "landscape_mv_reversed")
    assert normal.cover_rect == (96, 180, 720, 720)
    assert normal.lyrics_rect == (880, 180, 976, 720)
    for before, after in ((normal.cover_rect, reverse.cover_rect), (normal.lyrics_rect, reverse.lyrics_rect)):
        assert after == (1920-before[0]-before[2], *before[1:])


def test_offsets_and_bounds():
    layout = compute_layout(1920, 1080, cover_offset_x=40, lyrics_offset_x=-80)
    assert layout.cover_rect[0] == 136
    assert layout.lyrics_rect[0] == 800
    for offset in (-1920, 1920):
        layout = compute_layout(1920, 1080, cover_offset_x=offset, lyrics_offset_x=offset)
        for x, y, w, h in (layout.cover_rect, layout.lyrics_rect):
            assert 0 <= x <= 1920-w


def test_layout_roundtrip_and_context(tmp_path):
    project = KProj()
    project.output.layout_preset = "landscape_mv_reversed"
    project.output.cover_offset_x = -45
    project.output.lyrics_offset_x = 55
    loaded = kproj_from_dict(kproj_to_dict(project))
    assert loaded == project
    assert build_context(loaded, tmp_path).layout == compute_layout(1920, 1080, "landscape_mv_reversed", -45, 55)


@pytest.mark.parametrize("value,expected", [(None, 0), ("bad", 0), (float("inf"), 0), (9999, 1920), (-9999, -1920)])
def test_offset_loading_tolerance(value, expected):
    project = kproj_from_dict({"output": {"cover_offset_x": value}})
    assert project.output.cover_offset_x == expected
    assert project.output.lyrics_offset_x == 0


@pytest.mark.parametrize("preset", ["landscape_mv", "landscape_mv_reversed"])
def test_arc_lyrics_follow_lyrics_region(tmp_path, preset):
    from app.core.scene import Scene
    project = KProj()
    project.output.layout_preset = preset
    project.animations.lyrics.type = "arc"
    ctx = build_context(project, tmp_path, lrc_text="[00:00.00]A\n[00:02.00]B", duration_override=5.0)
    scene = Scene(ctx)
    scene.prepare()
    state = scene.eval(1.0)
    assert state == scene.eval(1.0)
    assert state.lyrics.items
    focused = next(item for item in state.lyrics.items if item.index == 0)
    assert focused.x == pytest.approx(ctx.layout.lyrics_rect[0] + 12)
