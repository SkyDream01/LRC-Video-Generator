"""主窗口：布局 / 菜单 / 快捷键 / 播放时钟驱动 / 导出入口。

- 预览时钟：16ms PreciseTimer 只调 preview.update()（不当计时器用），
  500ms 定时器做 PTS 纠漂；paintEvent 内只 eval + composite；
- prepare 永不在播放路径上：全部经 ProjectController 防抖进后台线程；
- scrub：拖动即预览（仅重锚预览时钟），音频 seek 合并 120ms，松手落定并恢复播放。
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QImage, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..core.encoder import find_binary
from ..core.project import default_output_name
from ..core.timeline import line_starts
from .composite import composite
from .controllers import ExportController, ProjectController
from .panels.input_panel import InputPanel
from .panels.params_panel import ParamsPanel
from .preview import CANVAS_H, CANVAS_W, PreviewSurface
from .timefmt import format_time
from .timeline_bar import TimelineBar
from .theme import apply_theme
from .workers import EncoderProbeWorker

# 播放 tick 周期（只驱动 update，不当计时器）
TICK_MS = 16
REANCHOR_MS = 500
SEEK_COALESCE_MS = 120

_ENGINE_LABELS = {"qt": "Qt 多媒体", "pcm": "ffmpeg PCM", "": "无"}


class MainWindow(QMainWindow):
    """LVM 主窗口（M2：GUI + 实时预览 + 纠漂时钟）。"""

    closed = Signal()

    def __init__(self) -> None:
        super().__init__()
        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_theme(app)
        self.setWindowTitle("LVM — LRC Video Maker")
        self.resize(1280, 800)
        self.setMinimumSize(1000, 640)

        # ---- 控制器与播放器 ----
        self.project_ctrl = ProjectController(self)
        self.export_ctrl = ExportController(self)
        from .audio_player import AudioPlayer

        self.audio = AudioPlayer(self)
        self._loaded_audio: str | None = None
        self._scrub_was_playing = False
        self._pending_seek: float | None = None
        self._probe_worker: EncoderProbeWorker | None = None

        # ---- 面板 ----
        self.input_panel = InputPanel()
        self.preview = PreviewSurface()
        self.params_panel = ParamsPanel()
        self.timeline = TimelineBar()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.input_panel)
        splitter.addWidget(self.preview)
        splitter.addWidget(self.params_panel)
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        splitter.setCollapsible(2, False)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([260, 640, 300])

        center = QWidget()
        center.setObjectName("workspace")
        vbox = QVBoxLayout()
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)
        vbox.addWidget(splitter, 1)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        vbox.addWidget(line)
        vbox.addWidget(self.timeline)
        layout = QHBoxLayout(center)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(vbox)
        self.setCentralWidget(center)

        self._build_status_bar()
        self._build_menus()
        self._build_shortcuts()
        self._build_timers()
        self._wire()

        self.params_panel.bind(self.project_ctrl.project)
        self._update_readiness()
        self._start_encoder_probe()

    # ---------------------------------------------------------------- UI 构建

    def _build_status_bar(self) -> None:
        self._export_btn = QPushButton("导出视频")
        self._export_btn.setObjectName("exportButton")
        self._export_btn.setToolTip("导出 1920×1080 MP4（Ctrl+E）")
        self._export_btn.clicked.connect(self._on_export_button)

        self._progress = QProgressBar()
        self._progress.setObjectName("exportProgress")
        self._progress.setFixedWidth(200)
        self._progress.setTextVisible(True)
        self._progress.setVisible(False)

        self._encoder_label = QLabel("编码器: 探测中…")
        self._encoder_label.setObjectName("statusMetric")
        self._fps_label = QLabel("预览 -- fps")
        self._fps_label.setObjectName("statusMetric")
        self._engine_label = QLabel("音频: 无")
        self._engine_label.setObjectName("statusMetric")

        bar = self.statusBar()
        bar.setSizeGripEnabled(False)
        brand = QLabel("LVM")
        brand.setObjectName("statusBrand")
        bar.addWidget(brand)
        bar.addPermanentWidget(QLabel(" "))
        bar.addPermanentWidget(self._engine_label)
        bar.addPermanentWidget(self._fps_label)
        bar.addPermanentWidget(self._encoder_label)
        bar.addPermanentWidget(self._progress)
        bar.addPermanentWidget(self._export_btn)

    def _build_menus(self) -> None:
        menu_file = self.menuBar().addMenu("文件(&F)")
        act_open = menu_file.addAction("打开工程…")
        act_open.setShortcut(QKeySequence("Ctrl+O"))
        act_open.triggered.connect(self._open_project)
        act_save = menu_file.addAction("保存工程")
        act_save.setShortcut(QKeySequence("Ctrl+S"))
        act_save.triggered.connect(self._save_project)
        act_save_as = menu_file.addAction("工程另存为…")
        act_save_as.triggered.connect(lambda: self._save_project(force_dialog=True))
        menu_file.addSeparator()
        act_demo = menu_file.addAction("载入演示工程")
        act_demo.triggered.connect(self._load_demo)
        menu_file.addSeparator()
        act_export = menu_file.addAction("导出视频…")
        act_export.setShortcut(QKeySequence("Ctrl+E"))
        act_export.triggered.connect(self._on_export_button)
        menu_file.addSeparator()
        act_quit = menu_file.addAction("退出")
        act_quit.setShortcut(QKeySequence("Ctrl+Q"))
        act_quit.triggered.connect(self.close)

        menu_view = self.menuBar().addMenu("设置(&O)")
        act_exact = menu_view.addAction("精确预览当前帧")
        act_exact.setShortcut(QKeySequence("F5"))
        act_exact.setToolTip("离屏 1920×1080 合成当前帧（与导出像素一致）")
        act_exact.triggered.connect(self._exact_preview)
        act_restore = menu_view.addAction("恢复默认参数")
        act_restore.triggered.connect(self._restore_defaults)

        menu_help = self.menuBar().addMenu("帮助(&H)")
        act_about = menu_help.addAction("关于 LVM")
        act_about.triggered.connect(self._show_about)

    def _build_shortcuts(self) -> None:
        # 空格：焦点在输入类控件上时让控件自行处理
        space = QShortcut(QKeySequence(Qt.Key.Key_Space), self)
        space.setContext(Qt.ShortcutContext.WindowShortcut)
        space.activated.connect(self._toggle_play_guarded)
        home = QShortcut(QKeySequence(Qt.Key.Key_Home), self)
        home.activated.connect(lambda: self._jump(0.0))
        end = QShortcut(QKeySequence(Qt.Key.Key_End), self)
        end.activated.connect(self._jump_end)

    def _build_timers(self) -> None:
        self._tick = QTimer(self)
        self._tick.setTimerType(Qt.TimerType.PreciseTimer)
        self._tick.setInterval(TICK_MS)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start()

        self._reanchor = QTimer(self)
        self._reanchor.setInterval(REANCHOR_MS)
        self._reanchor.timeout.connect(self.audio.tick)
        self._reanchor.start()

        self._seek_timer = QTimer(self)
        self._seek_timer.setSingleShot(True)
        self._seek_timer.setInterval(SEEK_COALESCE_MS)
        self._seek_timer.timeout.connect(self._flush_pending_seek)

    # ---------------------------------------------------------------- 信号接线

    def _wire(self) -> None:
        pc = self.project_ctrl
        pc.sessionReady.connect(self._on_session)
        pc.preparingChanged.connect(self.preview.set_preparing)
        pc.prepareFailed.connect(
            lambda msg: self.statusBar().showMessage(f"资源准备失败: {msg}", 8000)
        )
        pc.projectLoaded.connect(self._on_project_loaded)

        self.input_panel.mediaSelected.connect(self._on_media_selected)
        self.input_panel.mediaCleared.connect(self._on_media_cleared)
        self.input_panel.loadDemoRequested.connect(self._load_demo)

        self.params_panel.paramsChanged.connect(pc.request_prepare)
        self.params_panel.restoreDefaultsRequested.connect(self._restore_defaults)

        self.timeline.playToggled.connect(self._toggle_play_guarded)
        self.timeline.scrubStarted.connect(self._on_scrub_start)
        self.timeline.scrubMoved.connect(self._on_scrub_moved)
        self.timeline.scrubFinished.connect(self._on_scrub_finished)

        self.preview.set_t_provider(self.audio.position_s)
        self.preview.fpsChanged.connect(
            lambda fps: self._fps_label.setText(f"预览 {fps} fps")
        )

        self.audio.playbackChanged.connect(self._on_playback_changed)
        self.audio.durationChanged.connect(self._on_player_duration)
        self.audio.errorOccurred.connect(
            lambda msg: self.statusBar().showMessage(msg, 8000)
        )
        self.audio.engineChanged.connect(
            lambda eng: self._engine_label.setText(
                f"音频: {_ENGINE_LABELS.get(eng, eng)}"
            )
        )
        self.audio.finished.connect(
            lambda: self.statusBar().showMessage("播放结束", 4000)
        )

        ec = self.export_ctrl
        ec.exportStarted.connect(self._on_export_started)
        ec.exportProgress.connect(self._on_export_progress)
        ec.exportFinished.connect(self._on_export_finished)
        ec.exportCancelled.connect(self._on_export_cancelled)
        ec.exportFailed.connect(self._on_export_failed)

    # ---------------------------------------------------------------- 工程/媒体

    def _on_project_loaded(self) -> None:
        p = self.project_ctrl.project
        for key in ("audio", "cover", "lrc", "background"):
            self.input_panel.set_media_path(key, getattr(p.files, key))
        self.params_panel.bind(p)
        name = (
            f" · {self.project_ctrl.kproj_path.name}"
            if self.project_ctrl.kproj_path
            else ""
        )
        self.setWindowTitle(f"LVM — LRC Video Maker{name}")

    def _on_media_selected(self, key: str, path: str) -> None:
        self.input_panel.set_media_path(key, path)
        self.project_ctrl.set_media(key, path)

    def _on_media_cleared(self, key: str) -> None:
        self.input_panel.set_media_path(key, None)
        self.project_ctrl.clear_media(key)

    def _open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "打开工程", "", "LVM 工程 (*.kproj)"
        )
        if not path:
            return
        try:
            self.project_ctrl.load_project(path)
        except (ValueError, OSError) as exc:
            QMessageBox.critical(self, "打开工程失败", str(exc))

    def _save_project(self, force_dialog: bool = False) -> None:
        path: str | None = None
        if force_dialog or self.project_ctrl.kproj_path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "保存工程", "untitled.kproj", "LVM 工程 (*.kproj)"
            )
            if not path:
                return
        try:
            saved = self.project_ctrl.save_project(path)
        except (ValueError, OSError) as exc:
            QMessageBox.critical(self, "保存工程失败", str(exc))
            return
        self.setWindowTitle(f"LVM — LRC Video Maker · {saved.name}")
        self.statusBar().showMessage(f"已保存: {saved}", 5000)

    def _load_demo(self) -> None:
        from app.core.demo import make_demo_project

        work = Path("output/gui_demo")
        try:
            _project, kproj_path = make_demo_project(work)
        except OSError as exc:
            QMessageBox.critical(self, "生成演示工程失败", str(exc))
            return
        self.project_ctrl.load_project(kproj_path)
        self.statusBar().showMessage(f"演示工程已加载: {kproj_path}", 5000)

    def _restore_defaults(self) -> None:
        self.project_ctrl.restore_defaults()
        self.params_panel.bind(self.project_ctrl.project)
        self.statusBar().showMessage("已恢复默认参数", 4000)

    # ---------------------------------------------------------------- 会话/就绪

    def _on_session(self, session) -> None:  # PreparedSession
        self.preview.set_session(session)
        ctx = session.ctx
        duration = ctx.duration if ctx.duration > 0 else self.audio.duration_s()
        self.timeline.set_duration(duration)
        self.timeline.set_marks(line_starts(ctx.intervals))

        cover_size = (
            f"{ctx.cover.width}×{ctx.cover.height}" if ctx.cover is not None else None
        )
        self.input_panel.set_info(
            duration=ctx.duration if ctx.duration > 0 else None,
            title=ctx.meta.title,
            artist=ctx.meta.artist,
            album=ctx.meta.album,
            lrc_lines=len(ctx.lyrics) or None,
            cover_size=cover_size,
        )
        self.params_panel.set_palette_preview(ctx.palette)

        audio_path = str(ctx.audio_path) if ctx.audio_path is not None else None
        if audio_path != self._loaded_audio:
            self._loaded_audio = audio_path
            self.audio.load(audio_path)
            self._engine_label.setText(
                f"音频: {_ENGINE_LABELS.get(self.audio.engine, '')}"
            )

        self._update_readiness()
        self.statusBar().showMessage(
            f"资源就绪 · {len(ctx.lyrics)} 行歌词 · 时长 {format_time(ctx.duration)}",
            6000,
        )

    def _update_readiness(self) -> None:
        has_session = self.preview.session() is not None
        self.timeline.setEnabled(has_session)
        # 设计：音频或 LRC 未加载时，导出与播放置灰
        can_export = (
            has_session and self.project_ctrl.has_audio and self.project_ctrl.has_lrc
        )
        self._export_btn.setEnabled(can_export and not self.export_ctrl.is_running)

    # ---------------------------------------------------------------- 播放

    def _toggle_play_guarded(self) -> None:
        fw = QApplication.focusWidget()
        if isinstance(
            fw, (QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit, QTextEdit, QPushButton)
        ):
            return  # 焦点控件自行处理空格
        self._toggle_play()

    def _toggle_play(self) -> None:
        if self.audio.engine == "" or self.preview.session() is None:
            self.statusBar().showMessage("请先加载音频文件", 4000)
            return
        self.preview.set_exact_frame(None)
        self.audio.toggle()

    def _on_playback_changed(self, playing: bool) -> None:
        self.timeline.set_playing(playing)
        if playing:
            self.preview.set_exact_frame(None)

    def _on_player_duration(self, duration: float) -> None:
        if duration > 0:
            self.timeline.set_duration(duration)

    def _on_tick(self) -> None:
        if not self.audio.is_playing():
            return
        t = self.audio.position_s()
        duration = self.timeline.duration
        if 0 < duration <= t:
            self.audio.pause()
            t = duration
        self.preview.update()
        self.timeline.set_time(t)

    def _jump(self, t: float) -> None:
        if self.preview.session() is None:
            return
        self.preview.set_exact_frame(None)
        self.audio.seek(t)
        self.preview.update()
        self.timeline.set_time(t)

    def _jump_end(self) -> None:
        duration = self.audio.duration_s() or self.project_ctrl.project.output.fps * 0
        if duration <= 0:
            return
        self._jump(duration)

    # ---------------------------------------------------------------- scrub

    def _on_scrub_start(self, t: float) -> None:
        self._scrub_was_playing = self.audio.is_playing()
        if self._scrub_was_playing:
            self.audio.pause()
        self._pending_seek = t
        self._seek_timer.start()

    def _on_scrub_moved(self, t: float) -> None:
        self._pending_seek = t
        self._seek_timer.start()
        # 预览即时跟随：只重锚预览时钟，不触碰媒体引擎
        self.audio.seek(t, sync_media=False)
        self.preview.update()
        self.timeline.set_time(t)

    def _on_scrub_finished(self, t: float) -> None:
        self._seek_timer.stop()
        self._pending_seek = None
        self.preview.set_exact_frame(None)
        self.audio.seek(t)
        self.preview.update()
        self.timeline.set_time(t)
        if self._scrub_was_playing and self.audio.engine != "":
            self.audio.play()
        self._scrub_was_playing = False

    def _flush_pending_seek(self) -> None:
        if self._pending_seek is not None:
            self.audio.seek(self._pending_seek)

    # ---------------------------------------------------------------- 精确预览

    def _exact_preview(self) -> None:
        session = self.preview.session()
        if session is None:
            self.statusBar().showMessage("暂无可预览内容", 4000)
            return
        t = self.audio.position_s()
        img = QImage(CANVAS_W, CANVAS_H, QImage.Format.Format_RGB888)
        img.fill(Qt.GlobalColor.black)
        painter = QPainter(img)
        try:
            composite(painter, session.scene.eval(t), session.assets)
        finally:
            painter.end()
        self.preview.set_exact_frame(img)
        self.statusBar().showMessage(
            f"已按 {CANVAS_W}×{CANVAS_H} 离屏合成当前帧（与导出一致）", 6000
        )

    # ---------------------------------------------------------------- 导出

    def _on_export_button(self) -> None:
        if self.export_ctrl.is_running:
            self.export_ctrl.cancel()
            self.statusBar().showMessage("正在取消导出…", 4000)
            return
        if self.preview.session() is None or not (
            self.project_ctrl.has_audio and self.project_ctrl.has_lrc
        ):
            missing = []
            if not self.project_ctrl.has_audio:
                missing.append("音频")
            if not self.project_ctrl.has_lrc:
                missing.append("LRC 歌词")
            self.statusBar().showMessage(f"缺少 {' 和 '.join(missing)}，无法导出", 6000)
            return
        suggested = default_output_name(self.project_ctrl.project.files.audio)
        path, _ = QFileDialog.getSaveFileName(
            self, "导出视频", suggested, "MP4 (*.mp4)"
        )
        if not path:
            return
        if not path.lower().endswith(".mp4"):
            path += ".mp4"
        self.export_ctrl.start(
            self.project_ctrl.project, self.project_ctrl.base_dir, Path(path)
        )

    def _on_export_started(self) -> None:
        self._export_btn.setText("取消导出")
        self._export_btn.setEnabled(True)
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setVisible(True)
        self.statusBar().showMessage("导出中…", 0)

    def _on_export_progress(self, done: int, total: int) -> None:
        self._progress.setMaximum(total)
        self._progress.setValue(done)
        self._progress.setFormat(f"%p% ({done}/{total} 帧)")

    def _on_export_finished(self, result) -> None:  # ExportResult
        self._reset_export_ui()
        self.statusBar().showMessage(
            f"导出完成: {result.output}（{result.encoder} · {result.frames} 帧）", 10000
        )
        QMessageBox.information(
            self,
            "导出完成",
            f"{result.output}\n\n编码器 {result.encoder} · {result.frames} 帧 · "
            f"{result.fps} fps · 时长 {result.duration:.2f}s",
        )

    def _on_export_cancelled(self) -> None:
        self._reset_export_ui()
        self.statusBar().showMessage("导出已取消", 5000)

    def _on_export_failed(self, message: str) -> None:
        self._reset_export_ui()
        QMessageBox.critical(self, "导出失败", message)

    def _reset_export_ui(self) -> None:
        self._export_btn.setText("导出视频")
        self._export_btn.setEnabled(self._can_export_now())
        self._progress.setVisible(False)

    def _can_export_now(self) -> bool:
        return (
            self.preview.session() is not None
            and self.project_ctrl.has_audio
            and self.project_ctrl.has_lrc
        )

    # ---------------------------------------------------------------- 编码器探测

    def _start_encoder_probe(self) -> None:
        ffmpeg = find_binary("ffmpeg")
        ffprobe = find_binary("ffprobe")
        if ffmpeg is None:
            self._encoder_label.setText("编码器: 未找到 ffmpeg（仅预览）")
            self._encoder_label.setToolTip(
                "请将 ffmpeg.exe 放入 ffmpeg/ 目录或加入 PATH"
            )
            return
        if ffprobe is None:
            # 导出本身只需要 ffmpeg；ffprobe 缺失时 audio_duration 会按
            # mutagen 回退，但把这个启动自检结果明确展示给用户。
            self._encoder_label.setToolTip(
                "未找到 ffprobe：时长探测将回退 mutagen；建议将 ffprobe.exe "
                "放入 ffmpeg/ 目录或加入 PATH"
            )
        self._probe_worker = EncoderProbeWorker(self)
        self._probe_worker.probed.connect(self._on_encoder_probed)
        self._probe_worker.unavailable.connect(
            lambda: self._encoder_label.setText("编码器: 探测失败（导出走 libx264）")
        )
        self._probe_worker.finished.connect(self._on_probe_finished)
        self._probe_worker.start()

    def _on_probe_finished(self) -> None:
        # 线程结束后清空引用：C++ 对象稍后由 deleteLater 回收，
        # 避免 closeEvent 触到已删除包装（libshiboken RuntimeError）
        self._probe_worker = None

    def _on_encoder_probed(self, name: str) -> None:
        self.export_ctrl.probed_encoder = name
        self._encoder_label.setText(f"编码器: {name}")

    # ---------------------------------------------------------------- 其他

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "关于 LVM",
            "LVM — LRC Video Maker\n\n音频 + LRC 双语歌词 + 封面 → 1920×1080@60fps MP4。\n"
            "M3：参数 schema、自动取色、kproj 工程与元数据显示。",
        )

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        if self.export_ctrl.is_running:
            ret = QMessageBox.question(
                self,
                "退出确认",
                "导出仍在进行，退出将中断导出。确定退出吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ret != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.export_ctrl.cancel()
            self.export_ctrl.wait(5000)
        self.audio.stop()
        self._wait_probe_worker()
        self.closed.emit()
        super().closeEvent(event)

    def _wait_probe_worker(self) -> None:
        """探测线程若仍在跑，退出前等待收尾（QThread 运行中销毁会导致硬崩溃）。"""
        worker = self._probe_worker
        self._probe_worker = None
        if worker is None:
            return
        try:
            running = worker.isRunning()
        except RuntimeError:
            return  # C++ 对象已被 deleteLater 回收，无需等待
        if running:
            worker.wait(5000)


def run_gui() -> int:
    """启动 GUI 应用（真实桌面平台；测试/CLI 用 QT_QPA_PLATFORM=offscreen 覆盖）。"""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    assert isinstance(
        app, QApplication
    )  # instance() 类型为 QApplication | QCoreApplication
    app.setApplicationName("LVM")
    app.setApplicationDisplayName("LVM — LRC Video Maker")
    win = MainWindow()
    win.show()
    return app.exec()
