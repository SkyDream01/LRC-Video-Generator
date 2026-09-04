"""离屏导出：offscreen Qt + Scene + composite → ffmpeg yuv420p 管道。

与 GUI 导出共用 composite()（所见即所得）。M2 的 ExportWorker(QThread) 直接复用
render_video()；worker 线程只允许 QImage，禁止 QPixmap。
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from ..core.context import RenderContext, build_context
from ..core.encoder import (
    EncoderError,
    EncoderSession,
    build_encode_command,
    detect_encoder,
    find_binary,
    normalize_encoder,
)
from ..core.project import KProj
from ..core.scene import Scene
from .composite import GuiAssets, composite, qimage_rgb24_buffer

ProgressCallback = Callable[[int, int], None]
CancelCallback = Callable[[], bool]

# 进度只用于 UI/CLI 反馈，不需要按每一帧发送；高频 signal/flush 会在
# 导出热路径上产生可见开销。
PROGRESS_HZ = 10


class ExportCancelled(RuntimeError):
    """用户取消导出。"""


@dataclass(frozen=True)
class ExportResult:
    """导出结果摘要。"""

    output: Path
    frames: int
    encoder: str
    duration: float
    fps: int


def ensure_qt_app() -> QApplication:
    """保证存在 QApplication（CLI 场景用 offscreen 平台）。

    用 QApplication 而非 QGuiApplication：同一进程后续若创建 QWidget（GUI/测试），
    仅 QGuiApplication 会因缺少 QApplication 实例而致命。
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    assert isinstance(app, QApplication)  # 本项目只会创建 QApplication
    return app


def frame_count(duration: float, fps: int) -> int:
    """导出帧数 N = round(duration * fps)。"""
    return max(1, round(duration * fps))


def _new_temp_output(output: Path) -> Path:
    """在最终输出同目录创建一个可由 ffmpeg 写入的临时路径。"""
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(
        prefix=f".{output.stem}.", suffix=".mp4", dir=str(output.parent)
    )
    os.close(fd)
    return Path(name)


def _remove_temp(path: Path) -> None:
    """尽力清理一次导出尝试留下的临时文件。"""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        # 临时文件若仍被第三方进程占用，不覆盖原始编码错误；下次启动
        # 时可以由用户清理同目录下的隐藏 .<name>.*.mp4 文件。
        pass


def render_video(
    project: KProj,
    base_dir: str | Path,
    output_path: str | Path,
    *,
    duration_override: float | None = None,
    encoder_override: str | None = None,
    max_frames: int | None = None,
    progress: ProgressCallback | None = None,
    cancel: CancelCallback | None = None,
) -> ExportResult:
    """渲染工程到 MP4。

    每种编码器都先写入输出目录下的临时文件，编码成功后才原子替换最终
    文件。这样硬件编码失败或用户取消时不会留下半个 MP4，也不会损坏
    已存在的成品；硬件编码中途失败会完整重跑一次 libx264。
    """
    ffmpeg = find_binary("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("未找到 ffmpeg（请放入 ffmpeg/ 目录或加入 PATH）")
    if project.files.audio is None:
        raise ValueError("工程未配置音频文件，无法导出")
    output = Path(output_path)
    if max_frames is not None and max_frames < 1:
        raise ValueError("max_frames 必须为正整数")
    if cancel is not None and cancel():
        raise ExportCancelled("导出已取消")

    ensure_qt_app()
    ctx: RenderContext = build_context(
        project, base_dir, duration_override=duration_override
    )
    if ctx.duration <= 0:
        raise ValueError("无法确定时长（缺少音频或 LRC）")
    if ctx.audio_path is None:
        raise ValueError("音频文件不存在或不可读")

    scene = Scene(ctx)
    scene.prepare()
    gui_assets = GuiAssets.from_context(ctx)

    fps = ctx.fps
    width, height = ctx.width, ctx.height
    if width % 2 or height % 2:
        raise ValueError(f"YUV420P 要求输出宽高为偶数：{width}×{height}")
    total = frame_count(ctx.duration, fps)
    if max_frames is not None:
        total = min(total, max_frames)
    progress_interval = max(1, (fps + PROGRESS_HZ - 1) // PROGRESS_HZ)

    encoder_name = encoder_override or project.output.encoder
    if encoder_name == "auto":
        encoder_name = detect_encoder(ffmpeg)
    encoder_name = normalize_encoder(encoder_name)

    def run_once(enc: str) -> None:
        temp_output = _new_temp_output(output)
        try:
            command = build_encode_command(
                ffmpeg=ffmpeg,
                width=width,
                height=height,
                fps=fps,
                frames=total,
                audio_path=str(ctx.audio_path),
                output_path=str(temp_output),
                encoder=enc,
                video_bitrate=project.output.video_bitrate,
                audio_bitrate=project.output.audio_bitrate,
            )
            image = QImage(width, height, QImage.Format.Format_RGB888)
            # 所有内置背景都会覆盖完整画布；只有缺失背景资源时才需要
            # 每帧清空，避免上一帧残留。
            needs_clear = gui_assets.bg_image is None
            if needs_clear:
                image.fill(Qt.GlobalColor.black)
            packed_scratch: bytearray | None = None
            with EncoderSession(command) as session:
                painter = QPainter(image)
                try:
                    for i in range(total):
                        if cancel is not None and cancel():
                            raise ExportCancelled("导出已取消")
                        if needs_clear:
                            image.fill(Qt.GlobalColor.black)
                        state = scene.eval(i / fps)
                        composite(painter, state, gui_assets)
                        frame, packed_scratch = qimage_rgb24_buffer(
                            image, packed_scratch
                        )
                        session.write_frame(frame)
                        done = i + 1
                        if progress is not None and (
                            done == 1
                            or done == total
                            or done % progress_interval == 0
                        ):
                            progress(done, total)
                finally:
                    painter.end()
                session.finish()

            if cancel is not None and cancel():
                raise ExportCancelled("导出已取消")
            # ffmpeg 已经关闭输出文件；同卷 os.replace 在 Windows 也是
            # 原子的，最终路径在此之前始终保持旧文件或不存在。
            os.replace(temp_output, output)
        finally:
            _remove_temp(temp_output)

    try:
        run_once(encoder_name)
    except EncoderError as first_error:
        if encoder_name == "libx264":
            raise
        # 硬件编码器中途失败 → 软件兜底重跑整段
        if progress is not None:
            progress(0, total)
        try:
            run_once("libx264")
        except EncoderError as software_error:
            raise EncoderError(
                f"硬件编码器 {encoder_name} 失败；libx264 兜底也失败：{software_error}"
            ) from first_error
        encoder_name = "libx264"

    return ExportResult(
        output=output,
        frames=total,
        encoder=encoder_name,
        duration=ctx.duration,
        fps=fps,
    )
