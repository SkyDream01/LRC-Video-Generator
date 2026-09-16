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
    x, _, w, _ = ctx.layout.lyrics_rect
    assert focused.x == pytest.approx(x + (12 if preset == "landscape_mv" else w - 12))


from dataclasses import replace
from app.core.anims.base import ANIM_REGISTRY


@pytest.mark.parametrize("kind", ["lyrics", "cover"])
@pytest.mark.parametrize("preset", ["landscape_mv", "landscape_mv_reversed"])
@pytest.mark.parametrize("offsets", [(40, -40), (-1920, 1920), (1920, -1920)])
def test_all_animation_layout_states(tmp_path, kind, preset, offsets):
    project = KProj()
    ctx = build_context(project, tmp_path,
                        lrc_text="[00:00]Main\n[00:00]Translation\n[00:02]Next", duration_override=5)
    from PIL import Image
    ctx.cover = Image.new("RGB", (32, 32), (200, 60, 30))
    original = ctx.layout
    for name, cls in ANIM_REGISTRY[kind].items():
        layer = cls({})
        ctx.layout = original
        ctx.assets[kind] = layer.prepare(ctx)
        baseline = [layer.eval(t, ctx) for t in (0.1, 1.0, 2.1, 4.9, 5.0)]
        ctx.layout = compute_layout(1920, 1080, preset, *offsets)
        ctx.assets[kind] = layer.prepare(ctx)
        dx = ctx.layout.lyrics_rect[0] - original.lyrics_rect[0]
        for t, before in zip((0.1, 1.0, 2.1, 4.9, 5.0), baseline):
            after = layer.eval(t, ctx)
            assert after == layer.eval(t, ctx)
            if kind == "cover":
                assert after == before
            elif name != "arc":
                assert after == replace(before, items=tuple(replace(i, x=i.x+dx) for i in before.items))
            else:
                import math
                assert all(math.isfinite(i.x) and math.isfinite(i.y) for i in after.items)
                assert all(i.left_align != i.right_align for i in after.items)


@pytest.mark.parametrize("offsets", [(0, 0), (40, -60), (1920, -1920)])
def test_arc_mirrors_geometry_without_mirroring_text(tmp_path, offsets):
    from app.core.anims.lyrics import ArcLyrics
    ctx = build_context(KProj(), tmp_path,
                        lrc_text="\n".join(f"[00:{i*2:02}]Line {i}" for i in range(8)), duration_override=18)
    layer = ArcLyrics({})
    ctx.layout = compute_layout(1920, 1080, "landscape_mv", *offsets)
    ctx.assets["lyrics"] = layer.prepare(ctx)
    before = layer.eval(6.2, ctx)
    ctx.layout = compute_layout(1920, 1080, "landscape_mv_reversed", *(-v for v in offsets))
    ctx.assets["lyrics"] = layer.prepare(ctx)
    after = layer.eval(6.2, ctx)
    assert before.items
    for a, b in zip(before.items, after.items):
        assert a.x + b.x == pytest.approx(1920)
        assert a.y == pytest.approx(b.y)
        assert a.angle == -b.angle
        assert a.scale == b.scale
        assert a.opacity == b.opacity
        assert a.left_align == b.right_align
