"""GUI 工作线程：AssetPrepWorker / ExportWorker / EncoderProbeWorker。

线程约定（DESIGN §4.9）：
- worker 里只允许 QImage / numpy，禁止创建 QPixmap；
- prepare 与导出不占用 GUI 线程，播放路径上只有 eval(t) + composite；
- prepare 结果带 prep_gen，主线程只接受最新一代，过期结果丢弃。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Any

from PySide6.QtCore import QThread, Signal

from ..core.context import RenderContext, build_context
from ..core.encoder import detect_encoder, find_binary
from ..core.project import KProj
from ..core.scene import Scene
from .composite import GuiAssets


@dataclass
class PreparedSession:
    """一次成功 prepare 的完整产物（gen 匹配时才被主线程采纳）。"""

    gen: int
    ctx: RenderContext
    scene: Scene
    assets: GuiAssets


class AssetPrepWorker(QThread):
    """后台 prepare：build_context + Scene.prepare + QImage 转换。"""

    finished_ok = Signal(int, object, object, object)  # gen, ctx, scene, gui_assets
    failed = Signal(int, str)

    def __init__(
        self, gen: int, project: KProj, base_dir: Path, parent: Any = None
    ) -> None:
        super().__init__(parent)
        self.gen = gen
        self._project = project
        self._base_dir = Path(base_dir)

    def run(self) -> None:
        try:
            if not self._project.files.audio or not self._project.files.lrc:
                raise ValueError("缺少音频与歌词，无法渲染")
            ctx = build_context(self._project, self._base_dir)
            if not ctx.lyrics:
                raise ValueError("缺少音频与歌词，无法渲染")
            scene = Scene(ctx)
            scene.prepare()
            assets = GuiAssets.from_context(ctx)
            self.finished_ok.emit(self.gen, ctx, scene, assets)
        except Exception as exc:  # noqa: BLE001 - 线程边界，任何异常转信号
            self.failed.emit(self.gen, str(exc))


class ExportWorker(QThread):
    """后台导出：复用 render_video（离屏 Qt + ffmpeg 管道）。

    render_video 会把每次编码尝试写到临时文件；因此取消或硬件回退时，
    GUI 线程看到的目标路径不会出现半成品。
    """

    progress = Signal(int, int)
    succeeded = Signal(object)  # ExportResult
    cancelled = Signal()
    failed = Signal(str)

    def __init__(
        self,
        project: KProj,
        base_dir: Path,
        output: Path,
        encoder_override: str | None = None,
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self._project = project
        self._base_dir = Path(base_dir)
        self._output = Path(output)
        self._encoder_override = encoder_override
        self._cancel_event = Event()

    def cancel(self) -> None:
        """请求取消；真正杀掉 ffmpeg 由导出线程完成。"""
        self._cancel_event.set()

    def run(self) -> None:
        from .exporter import ExportCancelled, render_video

        try:
            result = render_video(
                self._project,
                self._base_dir,
                self._output,
                encoder_override=self._encoder_override,
                progress=lambda done, total: self.progress.emit(done, total),
                cancel=self._cancel_event.is_set,
            )
        except ExportCancelled:
            self.cancelled.emit()
        except Exception as exc:  # noqa: BLE001 - 线程边界，任何异常转信号
            self.failed.emit(str(exc))
        else:
            self.succeeded.emit(result)


class EncoderProbeWorker(QThread):
    """实编码探测（启动后后台执行，不阻塞 UI；结果缓存到会话）。"""

    probed = Signal(str)  # 可用编码器名（含 libx264 兜底）
    unavailable = Signal()  # 未找到 ffmpeg

    def run(self) -> None:
        ffmpeg = find_binary("ffmpeg")
        if not ffmpeg:
            self.unavailable.emit()
            return
        try:
            self.probed.emit(detect_encoder(ffmpeg))
        except Exception:  # noqa: BLE001 - 探测失败按不可用处理
            self.unavailable.emit()
