"""M2 GUI 测试：纠漂时钟 / 参数面板 schema / 控制器防抖去重 / 预览绘制 /
时间轴 scrub / 主窗口冒烟（离屏，qt 标记）。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import cast

import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.qt
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QPoint, QSize, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QResizeEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core.demo import make_demo_project  # noqa: E402
from app.core.project import KProj  # noqa: E402
from app.gui.audio_player import AudioPlayer, DriftClock  # noqa: E402
from app.gui.controllers import ProjectController  # noqa: E402
from app.gui.preview import PreviewSurface  # noqa: E402
from app.gui.timefmt import format_time  # noqa: E402
from app.gui.timeline_bar import TimelineBar  # noqa: E402
from app.gui.workers import AssetPrepWorker, PreparedSession  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    """复用进程内已有 QApplication（test_export 可能先建）。"""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def _demo(tmp_path: Path):
    work = tmp_path / "demo"
    return make_demo_project(work)


def _wait_until(pred, timeout_ms: int = 15000) -> bool:
    """轮询等待（运行事件循环，让防抖定时器/worker 信号得以派发）。"""
    loop = QEventLoop()
    result = {"ok": False}

    def poll() -> None:
        if pred():
            result["ok"] = True
            loop.quit()

    poller = QTimer()
    poller.setInterval(15)
    poller.timeout.connect(poll)
    poller.start()
    QTimer.singleShot(timeout_ms, loop.quit)
    poll()
    if not result["ok"]:
        loop.exec()
    poller.stop()
    return result["ok"]


# ---------------------------------------------------------------- 纯逻辑


def test_format_time():
    assert format_time(0.0) == "00:00.0"
    assert format_time(61.25) == "01:01.2"
    assert format_time(119.999) == "02:00.0"
    assert format_time(-3.0) == "00:00.0"
    assert format_time(3600.0) == "60:00.0"


def test_drift_clock_anchor_and_reanchor():
    clock = DriftClock()
    clock.anchor(10.0)
    t = clock.now()
    assert 10.0 <= t < 10.2  # 单调钟从锚点起算
    assert not clock.needs_reanchor(t)  # 与自身 PTS 一致 → 无需纠漂
    assert clock.needs_reanchor(11.0)  # 1s 漂移 > 80ms 阈值
    clock.anchor(42.5)
    assert abs(clock.now() - 42.5) < 0.1
    # now() 永不回退（同一锚点内）
    a = clock.now()
    b = clock.now()
    assert b >= a


# ---------------------------------------------------------------- 音频播放器


def test_audio_player_without_source(qapp):
    player = AudioPlayer()
    player.load(None)
    assert player.engine == ""
    assert not player.is_playing()
    player.seek(3.2)
    assert abs(player.position_s() - 3.2) < 1e-6  # 无音频时 scrub 仍可静帧定位
    player.seek(100.0)
    assert player.position_s() == 100.0  # 无 duration 上限时不钳制


def test_audio_player_seek_preview_only(qapp):
    player = AudioPlayer()
    player.load(None)
    player._duration = 60.0  # 模拟已知时长
    player.seek(5.0, sync_media=False)
    assert abs(player.position_s() - 5.0) < 1e-6
    player.seek(70.0)  # 超出时长 → 钳制
    assert player.position_s() == 60.0


# ---------------------------------------------------------------- 参数面板


def test_params_panel_schema_generated(qapp):
    from app.core.anims.base import ANIM_REGISTRY
    from app.gui.panels.params_panel import ParamsPanel

    project = KProj()
    project.animations.background.type = "gradient_wave"
    project.animations.lyrics.type = "scroll_list"
    project.animations.cover.type = "disc_rotate"
    panel = ParamsPanel()
    panel.bind(project)

    # 下拉框选项与注册表一致（GUI 不写死动画）
    for kind in ("background", "lyrics", "cover"):
        assert panel._anim_combos[kind].count() == len(ANIM_REGISTRY[kind])
        assert (
            panel._anim_combos[kind].currentData()
            == getattr(project.animations, kind).type
        )
    # schema 行数与参数个数一致
    bg_cls = ANIM_REGISTRY["background"]["gradient_wave"]
    assert panel._anim_forms["background"].rowCount() == len(bg_cls.params_schema())
    lyrics_cls = ANIM_REGISTRY["lyrics"]["scroll_list"]
    assert panel._anim_forms["lyrics"].rowCount() == len(lyrics_cls.params_schema())


def test_params_panel_type_switch_resets_params(qapp):
    from app.core.anims.base import ANIM_REGISTRY
    from app.gui.panels.params_panel import ParamsPanel

    project = KProj()
    panel = ParamsPanel()
    panel.bind(project)
    changes: list[bool] = []
    panel.paramsChanged.connect(lambda: changes.append(True))

    combo = panel._anim_combos["lyrics"]
    idx = combo.findData("scroll_list")
    assert idx >= 0
    combo.setCurrentIndex(idx)  # 用户切换动画类型
    assert project.animations.lyrics.type == "scroll_list"
    cls = ANIM_REGISTRY["lyrics"]["scroll_list"]
    assert project.animations.lyrics.params == cls.defaults()  # 按 schema 填默认值
    assert changes


def test_params_panel_bind_blocks_signals(qapp):
    from app.gui.panels.params_panel import ParamsPanel

    project = KProj()
    project.lyric_style.main_size = 128
    panel = ParamsPanel()
    changes: list[bool] = []
    panel.paramsChanged.connect(lambda: changes.append(True))
    panel.bind(project)
    assert panel._size_main.value() == 128
    assert not changes  # bind 不触发 paramsChanged


# ---------------------------------------------------------------- 控制器


def test_project_controller_prepare_and_debounce(qapp, tmp_path):
    _project, kproj = _demo(tmp_path)
    ctrl = ProjectController()
    ctrl.load_project(kproj)

    sessions: list[PreparedSession] = []
    ctrl.sessionReady.connect(lambda s: sessions.append(cast(PreparedSession, s)))
    assert _wait_until(lambda: len(sessions) >= 1), "prepare 应在防抖后完成"
    session = sessions[0]
    assert session.ctx.duration == pytest.approx(8.0, abs=0.5)
    assert len(session.ctx.lyrics) == 4  # 双语配对：3 组双语 + 1 行单语
    assert session.assets.lyric_lines  # GUI assets 已转换

    # 防抖合并：连续 3 次 request 只产生一次新 prepare
    ctrl.sessionReady.disconnect()
    count = {"n": 0}
    ctrl.sessionReady.connect(lambda _s: count.__setitem__("n", count["n"] + 1))
    ctrl.request_prepare()
    ctrl.request_prepare()
    ctrl.request_prepare()
    before = count["n"]
    assert _wait_until(lambda: count["n"] > before, 8000)
    assert count["n"] == before + 1


def test_project_controller_empty_project_fails(qapp):
    ctrl = ProjectController()
    errors: list[str] = []
    ctrl.prepareFailed.connect(lambda m: errors.append(m))
    ctrl.request_prepare()
    assert _wait_until(lambda: bool(errors), 8000)
    assert "缺少音频与歌词" in errors[0]


def test_asset_prep_worker_runs_without_qt_widget(qapp, tmp_path):
    """worker 只产出 QImage/numpy，不创建 QPixmap（线程边界约束）。"""
    _project, kproj = _demo(tmp_path)
    from app.core.project import load_kproj

    project = load_kproj(kproj)
    worker = AssetPrepWorker(7, project, kproj.parent)
    from app.gui.composite import GuiAssets

    done: list[GuiAssets] = []
    loop = QEventLoop()
    worker.finished_ok.connect(
        lambda g, c, s, a: (done.append(cast(GuiAssets, a)), loop.quit())
    )
    worker.failed.connect(lambda _g, _m: loop.quit())
    worker.start()
    QTimer.singleShot(15000, loop.quit)
    loop.exec()
    assert done, "prepare 应成功"
    assert done[0].bg_image is not None


# ---------------------------------------------------------------- 预览


def _make_session(tmp_path: Path) -> PreparedSession:
    from app.core.context import build_context
    from app.core.scene import Scene
    from app.gui.composite import GuiAssets

    project, kproj = _demo(tmp_path)
    ctx = build_context(project, kproj.parent)
    scene = Scene(ctx)
    scene.prepare()
    return PreparedSession(
        gen=1, ctx=ctx, scene=scene, assets=GuiAssets.from_context(ctx)
    )


def test_preview_paint_smoke(qapp, tmp_path):
    session = _make_session(tmp_path)
    preview = PreviewSurface()
    preview.resize(640, 360)
    preview.set_session(session)
    preview.set_t_provider(lambda: 2.5)
    img = preview.grab().toImage()
    assert img.width() == 640 and img.height() == 360
    # 中央区域（封面/歌词）非纯背景色
    colors = {img.pixel(320, 180), img.pixel(320, 100), img.pixel(480, 180)}
    bg = img.pixel(2, 2)  # letterbox 外是背景
    assert any(c != bg for c in colors)


def test_preview_placeholder_and_fps(qapp):
    preview = PreviewSurface()
    preview.resize(320, 180)
    fps_values: list[int] = []
    preview.fpsChanged.connect(fps_values.append)
    img = preview.grab().toImage()
    assert img.pixel(2, 2) == img.pixel(160, 90)  # 无会话：整幅占位背景
    assert not fps_values  # 占位不计 fps


def test_timeline_caches_static_layer_and_invalidates_on_layout_changes(qapp):
    timeline = TimelineBar()
    timeline.resize(640, 50)
    timeline.set_duration(10.0)
    timeline.set_marks([1.0, 4.0, 8.0])
    timeline._ruler.grab()  # noqa: SLF001 - exercise the offscreen paint path

    cached = timeline._ruler._static_layer  # noqa: SLF001
    assert cached is not None

    timeline.set_time(2.0)
    assert timeline._ruler._static_layer is cached  # noqa: SLF001

    timeline.set_marks([1.0, 5.0])
    assert timeline._ruler._static_layer is None  # noqa: SLF001
    timeline._ruler.grab()  # noqa: SLF001
    rebuilt = timeline._ruler._static_layer  # noqa: SLF001
    assert rebuilt is not None and rebuilt is not cached

    timeline._ruler.resizeEvent(  # noqa: SLF001
        QResizeEvent(QSize(720, 50), QSize(640, 50))
    )
    assert timeline._ruler._static_layer is None  # noqa: SLF001


def test_timeline_label_updates_only_when_formatted_time_changes(qapp):
    timeline = TimelineBar()
    timeline.set_duration(10.0)
    initial = timeline._label.text()  # noqa: SLF001

    timeline.set_time(0.01)
    assert timeline._label.text() == initial  # noqa: SLF001

    timeline.set_time(0.2)
    assert timeline._label.text() != initial  # noqa: SLF001


def test_preview_preparing_overlay_keeps_last_assets(qapp, tmp_path):
    session = _make_session(tmp_path)
    preview = PreviewSurface()
    preview.resize(320, 180)
    preview.set_session(session)
    preview.set_preparing(True)  # prepare 期间保留旧 assets
    img = preview.grab().toImage()
    assert img.width() == 320


# ---------------------------------------------------------------- 时间轴


def test_timeline_scrub_signals(qapp):
    bar = TimelineBar()
    bar._ruler.resize(400, 40)
    bar.set_duration(100.0)
    bar.set_marks([10.0, 50.0, 90.0])

    received: list[tuple[str, float]] = []
    bar.scrubStarted.connect(lambda t: received.append(("start", round(t, 1))))
    bar.scrubMoved.connect(lambda t: received.append(("move", round(t, 1))))
    bar.scrubFinished.connect(lambda t: received.append(("end", round(t, 1))))

    QTest.mousePress(
        bar._ruler,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(100, 20),
    )
    QTest.mouseMove(bar._ruler, QPoint(200, 20))
    QTest.mouseRelease(
        bar._ruler,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(200, 20),
    )

    # x=100 → t=(100-10)/380*100≈23.7；x=200 → 50.0
    assert received[0][0] == "start" and received[0][1] == pytest.approx(23.7, abs=0.2)
    assert ("move", 50.0) in received
    assert received[-1] == ("end", 50.0)
    assert bar.time == pytest.approx(50.0, abs=0.2)


def test_timeline_time_label_and_playing_state(qapp):
    bar = TimelineBar()
    bar.set_duration(90.0)
    bar.set_time(30.0)
    assert bar.duration == pytest.approx(90.0)
    bar.set_playing(True)
    assert bar._btn.text() == "❚❚"
    bar.set_playing(False)
    assert bar._btn.text() == "▶"


# ---------------------------------------------------------------- 主窗口冒烟


def test_main_window_smoke(qapp, tmp_path):
    from app.gui.main_window import MainWindow

    _project, kproj = _demo(tmp_path)
    win = MainWindow()
    closed: list[bool] = []
    win.closed.connect(lambda: closed.append(True))
    win.show()

    assert not win._export_btn.isEnabled()  # 未加载 → 导出置灰
    win.project_ctrl.load_project(kproj)
    assert _wait_until(lambda: win.preview.session() is not None), "session 应就绪"

    session = win.preview.session()
    assert session is not None
    assert session.ctx.duration > 0
    assert win._export_btn.isEnabled()  # 音频+LRC 就绪
    assert win.input_panel._info_labels["duration"].text() != "—"
    assert len(win.timeline._ruler._starts) == 4  # 歌词刻度

    # scrub 全流程：即时重锚预览时钟（无 PTS 阶跃）
    win._on_scrub_start(2.0)
    win._on_scrub_moved(4.0)
    assert abs(win.audio.position_s() - 4.0) < 1e-6
    win._on_scrub_finished(4.0)
    assert abs(win.audio.position_s() - 4.0) < 1e-6

    # 精确预览：离屏 1920×1080 合成
    win._exact_preview()
    assert win.preview._exact_frame is not None
    assert win.preview._exact_frame.width() == 1920

    # 参数面板改字号 → 防抖 prepare → 新 session（assets 更新）
    win.params_panel._size_main.setValue(120)
    old = session
    assert _wait_until(
        lambda: win.preview.session() is not None and win.preview.session() is not old
    ), "参数变更应触发新一轮 prepare"

    win.close()
    assert closed


def test_main_window_keyboard_home_end(qapp, tmp_path):
    from app.gui.main_window import MainWindow

    _project, kproj = _demo(tmp_path)
    win = MainWindow()
    win.project_ctrl.load_project(kproj)
    assert _wait_until(lambda: win.preview.session() is not None)

    win._jump(5.0)
    assert abs(win.audio.position_s() - 5.0) < 1e-6
    win.close()
