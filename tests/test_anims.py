"""动画系统测试：注册表完整性、参数收敛、eval 纯度。"""

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
from app.core.project import KProj

EXPECTED = {
    "background": {"static_blur", "gradient_wave", "wave_blur"},
    "lyrics": {"fade", "scroll_list"},
    "cover": {"static", "disc_rotate"},
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
