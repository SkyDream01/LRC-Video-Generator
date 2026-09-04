"""Scene 测试：eval(t) 确定性与状态内容（不含像素）。"""

from app.core.context import build_context
from app.core.project import KProj
from app.core.scene import Scene


def _scene(**anim_overrides) -> Scene:
    project = KProj()
    for kind, anim_type in anim_overrides.items():
        getattr(project.animations, kind).type = anim_type
    ctx = build_context(
        project,
        ".",
        lrc_text="[ti:T]\n[ar:A]\n[00:01.00]Hello\n[00:01.00]你好\n[00:05.00]World\n",
        duration_override=10.0,
    )
    scene = Scene(ctx)
    scene.prepare()
    return scene


def test_eval_deterministic():
    scene = _scene()
    s1 = scene.eval(2.0)
    s2 = scene.eval(2.0)
    assert repr(s1) == repr(s2)


def test_current_line_bisect():
    scene = _scene()
    assert scene.eval(0.5).current_line == -1  # 首行前
    assert scene.eval(2.0).current_line == 0
    assert scene.eval(6.0).current_line == 1


def test_fade_opacity_ramp():
    scene = _scene(lyrics="fade")
    inside = scene.eval(2.0)  # 行区间 [1, 5)，fade 400ms
    assert inside.lyrics.items[0].opacity == 1.0
    entering = scene.eval(1.1)  # 100ms / 400ms
    assert abs(entering.lyrics.items[0].opacity - 0.25) < 1e-6


def test_scroll_list_highlight():
    scene = _scene(lyrics="scroll_list")
    state = scene.eval(6.0)
    assert state.lyrics.current_index == 1
    current_items = [it for it in state.lyrics.items if it.current]
    assert len(current_items) == 1
    assert current_items[0].index == 1
    assert current_items[0].opacity == 1.0
    others = [it for it in state.lyrics.items if not it.current]
    assert all(it.opacity < 1.0 for it in others)


def test_disc_angle_progresses():
    scene = _scene(cover="disc_rotate")
    ctx = scene.ctx
    from PIL import Image

    ctx.cover = Image.new("RGB", (64, 64), (120, 40, 40))
    scene.prepare()  # 重新 prepare 以拾取封面
    a1 = scene.eval(2.0).cover.angle
    a2 = scene.eval(4.0).cover.angle
    assert a1 == (2.0 * 33.3 * 6.0) % 360.0
    assert a2 != a1


def test_meta_alpha_fade_in():
    scene = _scene()
    assert scene.eval(0.6).meta_alpha < 1.0
    assert scene.eval(5.0).meta_alpha == 1.0
    assert scene.eval(5.0).meta_alpha > scene.eval(0.3).meta_alpha


def test_eval_before_prepare_raises():
    project = KProj()
    ctx = build_context(project, ".", lrc_text="[00:01.00]A", duration_override=5.0)
    scene = Scene(ctx)
    try:
        scene.eval(0.0)
    except RuntimeError:
        return
    raise AssertionError("未 prepare 时 eval 应抛 RuntimeError")
