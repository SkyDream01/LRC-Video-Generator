"""动画系统测试：注册表完整性、参数收敛、eval 纯度。"""

import pytest
from PIL import Image

from app.core.anims import (
    ANIM_REGISTRY,
    KIND_LYRICS,
    KINDS,
    BaseLayer,
    GradientWaveBG,
    ScrollListLyrics,
    layer_class,
)
from app.core.context import build_context
from app.core.project import KProj, load_kproj, save_kproj

EXPECTED = {
    "background": {"static_blur", "gradient_wave", "wave_blur", "breath_zoom"},
    "lyrics": {"fade", "scroll_list", "slide", "reveal"},
    "cover": {"static", "disc_rotate", "breath", "float"},
}


def test_registry_complete():
    assert set(KINDS) == {"background", "lyrics", "cover"}
    for kind, expected_types in EXPECTED.items():
        assert set(ANIM_REGISTRY[kind]) == expected_types


def test_layer_class_lookup_and_fallback():
    assert layer_class("background", "gradient_wave") is GradientWaveBG
    fallback = layer_class("background", "unknown_type")
    assert fallback is not None  # 未知 type 回退首个注册项
    assert layer_class("nope", "x") is None


def test_resolve_params_filters_unknown_and_clamps():
    resolved = GradientWaveBG.resolve_params({"speed": 2.0, "amp": 5.0, "bogus": 1})
    assert resolved == {"speed": 2.0, "amp": 1.0}  # 未知忽略 + 越界钳制
    resolved = ScrollListLyrics.resolve_params({"lines": 99, "ease": "linear"})
    assert resolved["lines"] == 11  # max=11
    assert resolved["ease"] == "linear"


def test_resolve_params_invalid_values_fall_back_to_defaults():
    resolved = GradientWaveBG.resolve_params({"speed": "abc", "amp": None})
    assert resolved == {"speed": 1.0, "amp": 0.3}


def test_base_layer_default_schema_empty():
    class Dummy(BaseLayer):
        kind = "background"
        anim_type = "dummy"

        def prepare(self, ctx):
            return None

        def eval(self, t, ctx):
            return None

    assert Dummy.params_schema() == []
    assert Dummy({}).params == {}


def test_layer_eval_pure_between_calls():
    """同一 t 两次 eval 结果必须逐位一致。"""
    project = KProj()
    ctx = build_context(
        project,
        ".",
        lrc_text="[00:01.00]A\n[00:05.00]B",
        duration_override=10.0,
    )
    for kind in KINDS:
        spec = getattr(project.animations, kind)
        cls = ANIM_REGISTRY[kind][spec.type]
        layer = cls({})
        layer.prepare(ctx)
        ctx.assets[kind] = layer.prepare(ctx)
        s1 = repr(layer.eval(2.0, ctx))
        s2 = repr(layer.eval(2.0, ctx))
        assert s1 == s2, f"{kind}/{spec.type} eval 不纯"


def test_unknown_anim_type_in_project_falls_back():
    project = KProj()
    project.animations.lyrics.type = "nonexistent"
    ctx = build_context(project, ".", lrc_text="[00:01.00]A", duration_override=5.0)
    # pi-lens-ignore: reportMissingImports
    from app.core.scene import Scene

    scene = Scene(ctx)  # 不抛错：回退首个注册项
    assert isinstance(scene.layers[KIND_LYRICS], BaseLayer)


def test_params_schema_titles_present():
    for kind, types in EXPECTED.items():
        for anim_type in types:
            schema = ANIM_REGISTRY[kind][anim_type].params_schema()
            for spec in schema:
                assert spec.label
                if spec.kind == "choice":
                    assert spec.choices


NEW_ANIMS = [
    ("background", "breath_zoom"),
    ("lyrics", "slide"),
    ("lyrics", "reveal"),
    ("cover", "breath"),
    ("cover", "float"),
]


@pytest.mark.parametrize("kind,name", NEW_ANIMS)
def test_new_animations_seek_roundtrip_and_resource_reuse(kind, name, tmp_path):
    project = KProj()
    cls = ANIM_REGISTRY[kind][name]
    spec = getattr(project.animations, kind)
    spec.type, spec.params = name, cls.defaults()
    assert load_kproj(save_kproj(project, tmp_path / "new.kproj")) == project
    ctx = build_context(
        project, ".", lrc_text="[00:01.00]Hello\n[00:01.20]World", duration_override=3
    )
    ctx.cover = Image.new("RGB", (64, 64), "red")
    layer = cls(spec.params)
    assets = layer.prepare(ctx)
    ctx.assets[kind] = assets
    first = layer.eval(1.05, ctx)
    layer.eval(2.0, ctx)
    assert first == layer.eval(1.05, ctx)
    assert ctx.assets[kind] is assets
    assert first != layer.eval(1.1, ctx)
    for param in cls.params_schema():
        assert cls.resolve_params({param.key: float("nan")})[param.key] == param.default
        assert cls.resolve_params({param.key: 99999})[param.key] == param.max


@pytest.mark.parametrize("name", ["slide", "reveal"])
def test_new_lyrics_boundaries_short_lines_and_zero_duration(name):
    ctx = build_context(
        KProj(), ".", lrc_text="[00:01.00]A\n[00:01.20]B", duration_override=2
    )
    cls = ANIM_REGISTRY["lyrics"][name]
    layer = cls()
    ctx.assets["lyrics"] = layer.prepare(ctx)
    assert not layer.eval(0, ctx).items
    assert not layer.eval(2, ctx).items
    midpoint = layer.eval(1.1, ctx).items[0]
    assert midpoint.opacity == pytest.approx(1)
    assert midpoint.reveal == pytest.approx(1)
    assert layer.eval(1.2, ctx).current_index == 1
    key = "fade_ms" if name == "slide" else "reveal_ms"
    immediate = cls({key: 0}).eval(1, ctx).items[0]
    assert immediate.opacity == immediate.reveal == 1
    empty = build_context(KProj(), ".", lrc_text="", duration_override=2)
    empty.assets["lyrics"] = layer.prepare(empty)
    assert not layer.eval(1, empty).items


@pytest.mark.parametrize(
    "kind,name,field,low,high",
    [
        ("background", "breath_zoom", "zoom", 1, 1.08),
        ("cover", "breath", "scale", 0.95, 1),
        ("cover", "float", "y_offset", -18, 18),
    ],
)
def test_periodic_motion_bounds(kind, name, field, low, high):
    ctx = build_context(KProj(), ".", lrc_text="", duration_override=30)
    layer = ANIM_REGISTRY[kind][name]()
    period = layer.params["period"]
    values = [getattr(layer.eval(period * i / 100, ctx), field) for i in range(101)]
    assert min(values) == pytest.approx(low)
    assert max(values) == pytest.approx(high)
    assert values[0] == pytest.approx(values[-1])
