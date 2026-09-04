"""应用控制层：ProjectController（prepare 调度）与 ExportController（导出调度）。

prepare 规则（DESIGN §4.9）：资源/参数变化 → 80ms 防抖 → 快照 KProj → 后台
AssetPrepWorker；结果带 prep_gen，主线程只接受最新一代，worker 运行中新请求排队。
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from ..core.project import KProj, load_kproj, save_kproj
from .workers import AssetPrepWorker, ExportWorker, PreparedSession

PREPARE_DEBOUNCE_MS = 80


class ProjectController(QObject):
    """持有 KProj 与 prepare 调度。所有 UI 修改都收敛到这里再触发防抖 prepare。"""

    sessionReady = Signal(object)  # PreparedSession
    prepareFailed = Signal(str)
    preparingChanged = Signal(bool)
    projectLoaded = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.project = KProj()
        self.base_dir = Path.cwd()
        self.kproj_path: Path | None = None

        self._gen = 0
        self._queued = False
        self._preparing = False
        self._worker: AssetPrepWorker | None = None
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(PREPARE_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._start_prepare)

    # ---- 工程 ----

    def set_media(self, key: str, path: str) -> None:
        setattr(self.project.files, key, path)
        self.request_prepare()

    def clear_media(self, key: str) -> None:
        setattr(self.project.files, key, None)
        self.request_prepare()

    def load_project(self, path: str | Path) -> None:
        """加载 .kproj（损坏抛 ValueError，由调用方提示）。"""
        project = load_kproj(path)
        self.project = project
        self.kproj_path = Path(path)
        self.base_dir = Path(path).parent
        self.projectLoaded.emit()
        self.request_prepare()

    def new_project(self) -> None:
        """新建空工程（保留输出参数之外的默认值）。"""
        self.project = KProj()
        self.kproj_path = None
        self.projectLoaded.emit()
        self.request_prepare()

    def restore_defaults(self) -> None:
        """恢复歌词样式/动画/色彩为默认值（保留文件与输出设置）。"""
        p = self.project
        p.lyric_style = KProj().lyric_style
        p.animations = KProj().animations
        p.colors = KProj().colors
        self.request_prepare()

    def save_project(self, path: str | Path | None = None) -> Path:
        """保存 .kproj（媒体路径相对化到工程目录）。"""
        target = Path(path) if path is not None else self.kproj_path
        if target is None:
            raise ValueError("未指定保存路径")
        saved = save_kproj(self.project, target)
        self.kproj_path = saved
        return saved

    @property
    def has_audio(self) -> bool:
        return bool(self.project.files.audio)

    @property
    def has_lrc(self) -> bool:
        return bool(self.project.files.lrc)

    # ---- prepare 调度 ----

    def request_prepare(self) -> None:
        """80ms 防抖：连续修改合并为一次 prepare。"""
        # 代数在请求到达时递增，而不是 worker 启动时递增。这样当前
        # worker 运行期间的参数修改会立即让旧结果失效，避免旧 assets
        # 在新一轮 prepare 前短暂覆盖最新工程状态。
        self._gen += 1
        if self._worker is not None and self._worker.isRunning():
            self._queued = True
        self._debounce.start()

    def _start_prepare(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._queued = True  # 当前 worker 结束后立刻跑最新快照
            return
        gen = self._gen
        snapshot = deepcopy(self.project)  # 防止 prepare 期间 UI 并发改同一对象
        worker = AssetPrepWorker(gen, snapshot, self.base_dir)
        worker.finished_ok.connect(self._on_worker_ok)
        worker.failed.connect(self._on_worker_failed)
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        worker.start()
        if not self._preparing:
            self._preparing = True
            self.preparingChanged.emit(True)

    def _on_worker_ok(
        self, gen: int, ctx: object, scene: object, assets: object
    ) -> None:
        self._worker = None
        if gen == self._gen:
            self._preparing = False
            self.preparingChanged.emit(False)
            self.sessionReady.emit(PreparedSession(gen, ctx, scene, assets))  # type: ignore[arg-type]
        self._drain_queue()

    def _on_worker_failed(self, gen: int, message: str) -> None:
        self._worker = None
        if gen == self._gen:
            self._preparing = False
            self.preparingChanged.emit(False)
            self.prepareFailed.emit(message)
        self._drain_queue()

    def _drain_queue(self) -> None:
        if self._queued:
            self._queued = False
            self._start_prepare()


class ExportController(QObject):
    """导出调度：快照工程 → ExportWorker（可取消）。"""

    exportStarted = Signal()
    exportProgress = Signal(int, int)
    exportFinished = Signal(object)  # ExportResult
    exportCancelled = Signal()
    exportFailed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._worker: ExportWorker | None = None
        self.probed_encoder: str | None = None  # 会话内实编码探测结果缓存

    @property
    def is_running(self) -> bool:
        return self._worker is not None

    def start(self, project: KProj, base_dir: Path, output: Path) -> None:
        if self._worker is not None:
            return
        encoder_override = None
        if project.output.encoder == "auto" and self.probed_encoder:
            encoder_override = self.probed_encoder
        snapshot = deepcopy(project)
        worker = ExportWorker(snapshot, base_dir, output, encoder_override)
        worker.progress.connect(self.exportProgress)
        worker.succeeded.connect(self._on_finished)
        worker.cancelled.connect(self._on_cancelled)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        worker.start()
        self.exportStarted.emit()

    def cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

    def wait(self, timeout_ms: int) -> bool:
        if self._worker is not None:
            return self._worker.wait(timeout_ms)
        return True

    def _on_finished(self, result: object) -> None:
        self._worker = None
        self.exportFinished.emit(result)

    def _on_cancelled(self) -> None:
        self._worker = None
        self.exportCancelled.emit()

    def _on_failed(self, message: str) -> None:
        self._worker = None
        self.exportFailed.emit(message)
