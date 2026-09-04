"""音频播放与纠漂时钟（DESIGN §4.9）。

预览时钟规则：
- 主时钟 = 单调钟：t = t0 + (monotonic() - m0)，播放开始/seek 时重锚；
- 每 ~500ms 用播放器 PTS（QMediaPlayer.position 或 QAudioSink 已处理微秒）纠漂，
  偏差超过阈值（80ms）才重锚，避免 PTS 阶跃导致画面抖动；
- 禁止每帧读 raw QMediaPlayer.position() 当时钟。

引擎回退：QMediaPlayer（Qt FFmpeg 后端）优先；解码失败（如个别 FLAC/容器）
自动切 ffmpeg 解 PCM → QAudioSink，时钟改用已处理微秒数。
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QIODevice, QObject, QProcess, QUrl, Signal
from PySide6.QtMultimedia import QAudioFormat, QAudioOutput, QAudioSink, QMediaPlayer

from ..core.encoder import find_binary

PCM_SAMPLE_RATE = 48000
PCM_CHANNELS = 2
# PCM 环形缓冲：256KB ≈ 1.3s（48k×2ch×s16），足够覆盖解码抖动
PCM_BUFFER_BYTES = 256 * 1024

# 纠漂：偏差超过该值才重锚（阈值太小时 QMediaPlayer 的 50–100ms 量化噪声会导致抖动）
REANCHOR_THRESHOLD_S = 0.08
# play/seek 后忽略 PTS 的宽限期（等待播放器真正跳到新位置）
REANCHOR_HOLDOUT_S = 0.30
# 纠漂检查周期（由 MainWindow 的定时器调用 tick()）
REANCHOR_PERIOD_S = 0.5


class DriftClock:
    """单调钟 + 锚点。now() = t0 + (monotonic() - m0)。"""

    __slots__ = ("_t0", "_m0")

    def __init__(self) -> None:
        self._t0 = 0.0
        self._m0 = time.monotonic()

    def anchor(self, media_t: float | None = None) -> None:
        """重锚：把当前单调时刻映射到 media_t（None 视为 0）。"""
        self._t0 = 0.0 if media_t is None else media_t
        self._m0 = time.monotonic()

    def now(self) -> float:
        return self._t0 + (time.monotonic() - self._m0)

    def needs_reanchor(
        self, pts: float, threshold_s: float = REANCHOR_THRESHOLD_S
    ) -> bool:
        return abs(self.now() - pts) > threshold_s


class _PcmEngine(QObject):
    """ffmpeg 解码 → QAudioSink 推送模式（QMediaPlayer 无法解码时的回退路径）。

    时钟主源：QAudioSink.processedUSecs()（已送入设备的微秒数）。
    """

    playbackChanged = Signal(bool)
    finished = Signal()
    error = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        fmt = QAudioFormat()
        fmt.setSampleRate(PCM_SAMPLE_RATE)
        fmt.setChannelCount(PCM_CHANNELS)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        self._format = fmt
        self._sink: QAudioSink | None = None
        self._io: QIODevice | None = None
        self._process: QProcess | None = None
        self._source = ""
        self._base_t = 0.0
        self._playing = False
        self._suspended = False
        self._pending = bytearray()

    # ---- 状态 ----

    def is_playing(self) -> bool:
        return self._playing

    def position_s(self) -> float:
        if self._sink is None:
            return self._base_t
        return self._base_t + self._sink.processedUSecs() / 1e6

    # ---- 控制 ----

    def load(self, source: str) -> None:
        self.stop()
        self._source = source

    def play(self, from_t: float | None = None) -> None:
        if not self._source or self._playing:
            return
        if self._sink is not None and self._suspended:
            # 暂停恢复：processedUSecs 从挂起处继续
            self._sink.resume()
            self._suspended = False
            self._playing = True
            self.playbackChanged.emit(True)
            return
        self._start_stream(from_t if from_t is not None else self._base_t)

    def pause(self) -> None:
        if self._sink is not None and self._playing and not self._suspended:
            self._base_t = self.position_s()
            self._sink.suspend()
            self._suspended = True
            self._playing = False
            self.playbackChanged.emit(False)

    def stop(self) -> None:
        if self._process is not None:
            self._process.close()
            self._process.deleteLater()
            self._process = None
        if self._sink is not None:
            self._sink.stop()
            self._sink.deleteLater()
            self._sink = None
        self._io = None
        self._base_t = 0.0
        self._pending.clear()
        self._suspended = False
        was = self._playing
        self._playing = False
        if was:
            self.playbackChanged.emit(False)

    def seek(self, t: float) -> None:
        """seek：杀进程重启解码流（-ss 快速定位）。"""
        was_playing = self._playing or self._suspended
        self.stop()
        self._base_t = t
        if was_playing:
            self._start_stream(t)

    # ---- 内部 ----

    def _start_stream(self, from_t: float) -> None:
        if not self._source:
            return
        ffmpeg = find_binary("ffmpeg")
        if not ffmpeg:
            self.error.emit("未找到 ffmpeg，无法解码该音频格式")
            return
        self._base_t = from_t
        sink = QAudioSink(self._format)
        sink.setBufferSize(PCM_BUFFER_BYTES)
        sink.setVolume(1.0)
        self._io = sink.start()
        self._sink = sink
        sink.stateChanged.connect(lambda _s: self._flush())

        process = QProcess(self)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        process.finished.connect(self._on_process_finished)
        process.readyReadStandardOutput.connect(self._on_stdout)
        args = [
            "-v",
            "error",
            "-ss",
            f"{max(0.0, from_t):.3f}",
            "-i",
            self._source,
            "-map",
            "0:a:0",
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-ac",
            str(PCM_CHANNELS),
            "-ar",
            str(PCM_SAMPLE_RATE),
            "pipe:1",
        ]
        process.start(ffmpeg, args)
        self._process = process
        self._playing = True
        self._suspended = False
        self.playbackChanged.emit(True)

    def _on_stdout(self) -> None:
        if self._process is None:
            return
        self._pending.extend(self._process.readAllStandardOutput().data())
        self._flush()

    def _flush(self) -> None:
        """按剩余缓冲写入，多余字节留在 _pending（readyRead/stateChanged 再驱动）。"""
        if self._io is None or self._sink is None or not self._pending:
            return
        free = self._sink.bytesFree()
        if free <= 0:
            return
        n = min(len(self._pending), free)
        written = self._io.write(bytes(self._pending[:n]))
        if written > 0:
            del self._pending[:written]

    def _on_process_finished(self, code: int, _status) -> None:
        if code != 0:
            return
        was = self._playing
        self._playing = False
        self._suspended = False
        if was:
            self.playbackChanged.emit(False)
        self.finished.emit()


class AudioPlayer(QObject):
    """统一播放接口：QMediaPlayer 主路径 + _PcmEngine 回退 + DriftClock。"""

    playbackChanged = Signal(bool)
    durationChanged = Signal(float)
    engineChanged = Signal(str)  # "qt" | "pcm"
    errorOccurred = Signal(str)
    finished = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.clock = DriftClock()
        self._engine = ""
        self._source = ""
        self._frozen_t = 0.0  # 暂停/未播放时的位置
        self._duration = 0.0
        self._holdout_until = 0.0  # mono 时刻，之前不做 PTS 纠漂

        self._player = QMediaPlayer(self)
        self._audio_out = QAudioOutput(self)
        self._audio_out.setVolume(0.9)
        self._player.setAudioOutput(self._audio_out)
        self._player.positionChanged.connect(self._on_position_changed)
        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.errorOccurred.connect(self._on_qt_error)
        self._pcm = _PcmEngine(self)
        self._pcm.playbackChanged.connect(self.playbackChanged)
        self._pcm.finished.connect(self._on_finished)
        self._pcm.error.connect(self.errorOccurred)

    # ---- 状态 ----

    @property
    def engine(self) -> str:
        """当前引擎："qt" | "pcm" | ""（未加载）。"""
        return self._engine

    def is_playing(self) -> bool:
        if self._engine == "qt":
            return (
                self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            )
        if self._engine == "pcm":
            return self._pcm.is_playing()
        return False

    def duration_s(self) -> float:
        return self._duration

    def position_s(self) -> float:
        """当前预览时刻：播放中走纠漂时钟，否则返回冻结位置。"""
        if self.is_playing():
            return self.clock.now()
        return self._frozen_t

    # ---- 加载 ----

    def load(self, path: str | None) -> None:
        """加载音频。path=None 卸载。引擎默认 qt，解码出错时回退 pcm。"""
        self.stop()
        self._source = path or ""
        self._frozen_t = 0.0
        self._duration = 0.0
        self._engine = "qt" if path else ""
        if path:
            self._player.setSource(QUrl.fromLocalFile(str(Path(path).resolve())))
        else:
            self._player.setSource(QUrl())
        self.engineChanged.emit(self._engine)

    # ---- 控制 ----

    def play(self) -> None:
        if not self._source:
            return
        start_t = self._frozen_t
        if 0.0 < self._duration <= start_t:
            start_t = 0.0  # 播完后再按播放 → 从头开始
        self._frozen_t = start_t
        self.clock.anchor(start_t)
        self._mark_holdout()
        if self._engine == "qt":
            self._player.setPosition(round(start_t * 1000))
            self._player.play()
        elif self._engine == "pcm":
            self._pcm.play(start_t)
        if self._engine == "qt" and self._duration <= 0.0:
            d = self._player.duration() / 1000.0
            if d > 0:
                self._duration = d
                self.durationChanged.emit(d)

    def pause(self) -> None:
        if not self._source:
            return
        if self.is_playing():
            self._frozen_t = self.clock.now()
        if self._engine == "qt":
            self._player.pause()
        elif self._engine == "pcm":
            self._pcm.pause()

    def toggle(self) -> None:
        if self.is_playing():
            self.pause()
        else:
            self.play()

    def stop(self) -> None:
        was = self.is_playing()
        self._frozen_t = 0.0
        self.clock.anchor(0.0)
        if self._engine == "qt":
            self._player.stop()
        elif self._engine == "pcm":
            self._pcm.stop()
        if was:
            self.playbackChanged.emit(False)

    def seek(self, t: float, sync_media: bool = True) -> None:
        """seek：立即重锚时钟（预览即时）。

        sync_media=False 仅重锚预览时钟（scrub 拖动中逐帧调用），引擎位置由
        合并后的完整 seek 同步。
        """
        t = max(0.0, t)
        if self._duration > 0:
            t = min(t, self._duration)
        if not self._source:
            self._frozen_t = t
            self.clock.anchor(t)
            return
        self._frozen_t = t
        self.clock.anchor(t)
        if sync_media:
            self._mark_holdout()
            if self._engine == "qt":
                self._player.setPosition(round(t * 1000))
            elif self._engine == "pcm":
                self._pcm.seek(t)

    def set_volume(self, v: float) -> None:
        self._audio_out.setVolume(max(0.0, min(1.0, v)))

    # ---- 纠漂 ----

    def tick(self) -> None:
        """由 ~500ms 定时器调用：用播放器 PTS 纠漂。"""
        if not self.is_playing() or not self._source:
            return
        if time.monotonic() < self._holdout_until:
            return
        pts = self._pts()
        if pts is not None and self.clock.needs_reanchor(pts):
            self.clock.anchor(pts)

    def _pts(self) -> float | None:
        if self._engine == "qt":
            return self._player.position() / 1000.0
        if self._engine == "pcm":
            return self._pcm.position_s()
        return None

    def _mark_holdout(self) -> None:
        self._holdout_until = time.monotonic() + REANCHOR_HOLDOUT_S

    # ---- 引擎信号 ----

    def _on_position_changed(self, ms: int) -> None:
        if not self.is_playing():
            self._frozen_t = ms / 1000.0

    def _on_duration_changed(self, ms: int) -> None:
        self._duration = ms / 1000.0
        if self._duration > 0:
            self.durationChanged.emit(self._duration)

    def _on_qt_error(self, error, error_string: str) -> None:
        if error == QMediaPlayer.Error.NoError:
            return
        was_playing = self.is_playing()
        self._engine = "pcm"
        self._pcm.load(self._source)
        self.engineChanged.emit("pcm")
        self.errorOccurred.emit(
            f"Qt 解码失败（{error_string or error}），已切换 ffmpeg PCM 回退"
        )
        if was_playing:
            self.clock.anchor(self._frozen_t)
            self._pcm.play(self._frozen_t)

    def _on_finished(self) -> None:
        self._frozen_t = (
            self._duration if self._duration > 0 else self._pcm.position_s()
        )
        self.playbackChanged.emit(False)
        self.finished.emit()
