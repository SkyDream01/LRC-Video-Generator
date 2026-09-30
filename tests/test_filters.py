"""滤镜确定性、参数边界、工程兼容与循环衔接。"""

import math

import numpy as np
import pytest

from app.core.anims import ANIM_REGISTRY
from app.core.context import build_context
from app.core.project import KProj, kproj_from_dict, load_kproj, save_kproj
from app.core.scene import Scene


@pytest.mark.parametrize("name", ["none", "light_leak", "bokeh"])
def test_filter_seek_cache_and_roundtrip(name, tmp_path):
    project = KProj()
    spec = project.animations.filter
    spec.type = name
    cls = ANIM_REGISTRY["filter"][name]
    spec.params = cls.defaults()
    assert load_kproj(save_kproj(project, tmp_path / "filter.kproj")) == project
    ctx = build_context(project, ".", lrc_text="", duration_override=30)
    scene = Scene(ctx)
    scene.prepare()
    assets = ctx.assets["filter"]
    copies = [texture.copy() for texture in assets.textures]
    first = scene.eval(1.25).filter
    scene.eval(29)
    assert scene.eval(1.25).filter == first
    assert ctx.assets["filter"] is assets
    assert sum(tex.nbytes for tex in assets.textures) <= 2 * 128 * 128 * 4
    if name != "none":
        assert first != scene.eval(3).filter
    for a, b in zip(copies, assets.textures):
        np.testing.assert_array_equal(a, b)
    rebuilt = cls(spec.params).prepare(ctx)
    assert rebuilt.seeds == assets.seeds
    for a, b in zip(rebuilt.textures, assets.textures):
        np.testing.assert_array_equal(a, b)


@pytest.mark.parametrize("raw", [{}, {"version": "1.0", "animations": {"cover": "static"}},
                                  {"animations": {"filter": None}},
                                  {"animations": {"filter": {"type": "future"}}}])
def test_legacy_and_unknown_filter_are_disabled(raw):
    ctx = build_context(kproj_from_dict(raw), ".", lrc_text="", duration_override=2)
    scene = Scene(ctx)
    scene.prepare()
    assert not scene.eval(1).filter.sprites
    assert not ctx.assets["filter"].textures


@pytest.mark.parametrize("name", ["light_leak", "bokeh"])
def test_filter_period_bounds_and_zero_strength(name):
    ctx = build_context(KProj(), ".", lrc_text="", duration_override=60)
    cls = ANIM_REGISTRY["filter"][name]
    layer = cls()
    ctx.assets["filter"] = layer.prepare(ctx)
    period = layer.params["period"]
    for t in (-1, 0, 1.25, 19.9999, 20, 1e6):
        a, b = layer.eval(t, ctx), layer.eval(t + period, ctx)
        for first, last in zip(a.sprites, b.sprites):
            assert (first.x, first.y, first.size, first.opacity) == pytest.approx(
                (last.x, last.y, last.size, last.opacity), abs=1e-7)
            assert 0 <= first.opacity <= 1
            assert all(math.isfinite(v) for v in (first.x, first.y, first.size))
    assert cls({"strength": 0}).eval(1, ctx).sprites == ()
    for spec in cls.params_schema():
        assert cls.resolve_params({spec.key: float("nan")})[spec.key] == spec.default
        assert cls.resolve_params({spec.key: -100})[spec.key] == spec.min
        assert cls.resolve_params({spec.key: 1e6})[spec.key] == spec.max


def test_bokeh_wrap_is_invisible_and_seed_changes_positions():
    ctx = build_context(KProj(), ".", lrc_text="", duration_override=30)
    cls = ANIM_REGISTRY["filter"]["bokeh"]
    layer = cls()
    assets = layer.prepare(ctx)
    ctx.assets["filter"] = assets
    assert cls({"seed": 7}).prepare(ctx).seeds != assets.seeds
    for i, (_, offset, _, _) in enumerate(assets.seeds):
        wrap = (1 - offset) * layer.params["period"]
        for t in (wrap - 1e-6, wrap, wrap + 1e-6):
            assert layer.eval(t, ctx).sprites[i].opacity < 1e-10


@pytest.mark.parametrize("ease", ["linear", "cubic", "smooth"])
def test_single_line_scroll_has_no_blank_handoff(ease):
    ctx = build_context(KProj(), ".", lrc_text="[00:01]A\n[00:02]B", duration_override=4)
    layer = ANIM_REGISTRY["lyrics"]["scroll_list"]({"lines": 1, "ease": ease})
    ctx.assets["lyrics"] = layer.prepare(ctx)
    for frame in range(22):
        state = layer.eval(2 + frame / 60, ctx)
        assert max(item.opacity for item in state.items) > .3


@pytest.mark.parametrize("name", ["scroll_list", "arc"])
def test_smooth_scroll_dense_lines_and_transition_parameter(name):
    ctx = build_context(KProj(), ".", lrc_text="[00:01]A\n[00:01.20]B\n[00:01.40]C", duration_override=3)
    cls = ANIM_REGISTRY["lyrics"][name]
    layer = cls({"ease": "smooth", "transition_ms": 1500})
    ctx.assets["lyrics"] = layer.prepare(ctx)
    before = {item.index: item for item in layer.eval(1.4 - 1e-7, ctx).items}
    after = {item.index: item for item in layer.eval(1.4, ctx).items}
    for i in before.keys() & after.keys():
        assert before[i].y == pytest.approx(after[i].y, abs=.001)
        assert before[i].opacity == pytest.approx(after[i].opacity, abs=.001)
    slow = layer.eval(1.45, ctx)
    fast = cls({"ease": "smooth", "transition_ms": 100}).eval(1.45, ctx)
    assert slow != fast
