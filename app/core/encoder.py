"""ffmpeg/ffprobe 封装：二进制查找、时长探测、编码器实编码探测、rawvideo 编码管道、yuv420p 转换。

外部进程策略：rawvideo 帧走 stdin 管道（bufsize ≥ 8MB），不落中间文件。
"""

from __future__ import annotations

import contextlib
import subprocess
import sys
import threading
from pathlib import Path

import numpy as np

# 应用目录下的 ffmpeg/（随包分发）优先于 PATH
FFMPEG_DIR = Path(__file__).resolve().parents[2] / "ffmpeg"
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

HARDWARE_ENCODERS = ("h264_nvenc", "h264_amf", "h264_qsv")
SOFTWARE_ENCODER = "libx264"
ENCODER_FALLBACK_CHAIN = HARDWARE_ENCODERS + (SOFTWARE_ENCODER,)

PIPE_BUFSIZE = 8 * 1024 * 1024
STDERR_TAIL_BYTES = 64 * 1024


class EncoderError(RuntimeError):
    """ffmpeg 编码失败。"""


def normalize_encoder(name: str | None) -> str:
    """把工程/命令行中的编码器名收敛为受支持的编码器。"""
    return name if name in ENCODER_FALLBACK_CHAIN else SOFTWARE_ENCODER


def find_binary(name: str) -> str | None:
    """查找 ffmpeg/ffprobe：① 应用目录 ffmpeg/ ② 系统 PATH。"""
    local = FFMPEG_DIR / f"{name}.exe"
    if local.is_file():
        return str(local)
    return shutil_which(name)


def shutil_which(name: str) -> str | None:
    import shutil

    return shutil.which(name)


def _run(
    cmd: list[str], timeout: float = 30.0, input_bytes: bytes | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        input=input_bytes,
        capture_output=True,
        timeout=timeout,
        creationflags=_CREATE_NO_WINDOW,
    )


# ---------------------------------------------------------------- 时长与元数据


def probe_duration_ffprobe(
    ffprobe: str, media_path: str | Path, timeout: float = 15.0
) -> float | None:
    """ffprobe 读媒体时长（秒）；失败返回 None。"""
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(media_path),
    ]
    try:
        proc = _run(cmd, timeout=timeout)
        if proc.returncode != 0:
            return None
        text = proc.stdout.decode("utf-8", "replace").strip()
        value = float(text.splitlines()[0]) if text else 0.0
    except (subprocess.SubprocessError, ValueError, IndexError):
        return None
    return value if value > 0 else None


def audio_duration(audio_path: str | Path, ffprobe: str | None = None) -> float:
    """音频时长：优先 ffprobe，失败回退 mutagen；两者都失败抛 ValueError。"""
    path = str(audio_path)
    probe_bin = ffprobe or find_binary("ffprobe")
    if probe_bin:
        duration = probe_duration_ffprobe(probe_bin, path)
        if duration:
            return duration
    try:
        from mutagen._file import File as MutagenFile

        media = MutagenFile(path)
        if media is not None and getattr(media.info, "length", 0.0):
            length = float(media.info.length)
            if length > 0:
                return length
    except Exception as exc:  # mutagen 对损坏/不识别文件抛各类异常
        raise ValueError(f"无法读取音频时长: {path}") from exc
    raise ValueError(f"无法读取音频时长: {path}")


def read_audio_meta(audio_path: str | Path) -> dict[str, str | None]:
    """mutagen 读 ID3/容器标签 → {'title','artist','album'}（缺省 None）。"""
    meta: dict[str, str | None] = {"title": None, "artist": None, "album": None}
    if not audio_path:
        return meta
    try:
        from mutagen._file import File as MutagenFile

        media = MutagenFile(str(audio_path), easy=True)
        if media is None or media.tags is None:
            return meta
        tags = media.tags

        def first(*keys: str) -> str | None:
            for key in keys:
                value = tags.get(key)
                if value is None and hasattr(tags, "getall"):
                    # raw ID3 标签使用 TIT2/TPE1/TALB，easy=True 通常已
                    # 映射为 title/artist/album；这里保留对原始帧的兼容。
                    with contextlib.suppress(Exception):
                        value = tags.getall(key)
                if value is None:
                    continue
                if isinstance(value, (list, tuple)):
                    values = value
                else:
                    values = (value,)
                for item in values:
                    if hasattr(item, "text"):
                        item = item.text
                    if isinstance(item, (list, tuple)):
                        item_values = item
                    else:
                        item_values = (item,)
                    for item_value in item_values:
                        if isinstance(item_value, bytes):
                            text = item_value.decode("utf-8", "replace").strip()
                        else:
                            text = str(item_value).strip()
                        if text:
                            return text
            return None

        meta["title"] = first("title", "TIT2", "©nam")
        meta["artist"] = first("artist", "TPE1", "aART")
        meta["album"] = first("album", "TALB", "©alb")
    except Exception:
        return meta
    return meta


# ---------------------------------------------------------------- 编码器探测


def probe_encoder(ffmpeg: str, encoder: str, timeout: float = 25.0) -> bool:
    """实编码探测：渲染 1 帧黑图试编码（-encoders 列表存在 ≠ 可用）。"""
    cmd = [
        ffmpeg,
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=256x144:r=30",
        "-frames:v",
        "1",
        "-c:v",
        encoder,
        "-f",
        "null",
        "-",
    ]
    try:
        return _run(cmd, timeout=timeout).returncode == 0
    except subprocess.SubprocessError:
        return False


def detect_encoder(ffmpeg: str) -> str:
    """探测链：NVENC → AMF → QSV → libx264 兜底。"""
    for name in HARDWARE_ENCODERS:
        if probe_encoder(ffmpeg, name):
            return name
    return SOFTWARE_ENCODER


# ---------------------------------------------------------------- 编码命令


def _encoder_options(encoder: str, video_bitrate: str) -> list[str]:
    """各编码器的质量参数（DESIGN.md §6）。"""
    if encoder == "h264_nvenc":
        return [
            "-preset",
            "p5",
            "-rc",
            "vbr",
            "-cq",
            "19",
            "-b:v",
            "0",
            "-maxrate",
            "24M",
            "-bufsize",
            "24M",
        ]
    if encoder == "h264_amf":
        return [
            "-quality",
            "quality",
            "-rc",
            "vbr_peak",
            "-b:v",
            video_bitrate,
            "-maxrate",
            "24M",
        ]
    if encoder == "h264_qsv":
        return ["-preset", "medium", "-global_quality", "20"]
    return ["-preset", "medium", "-crf", "17"]


def build_encode_command(
    *,
    ffmpeg: str,
    width: int,
    height: int,
    fps: int,
    frames: int,
    audio_path: str | Path,
    output_path: str | Path,
    encoder: str = SOFTWARE_ENCODER,
    video_bitrate: str = "12M",
    audio_bitrate: str = "320k",
) -> list[str]:
    """构建完整编码命令：rawvideo stdin + 音频 + BT.709/tv + faststart。"""
    encoder = normalize_encoder(encoder)
    return [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        # 输入 0：紧凑 RGB rawvideo。颜色空间转换交给 FFmpeg 的原生
        # scale/filter 路径，避免 Python/NumPy 每帧分配大块浮点数组。
        "-f",
        "rawvideo",
        "-video_size",
        f"{width}x{height}",
        "-framerate",
        str(fps),
        "-pix_fmt",
        "rgb24",
        "-colorspace",
        "bt709",
        "-color_primaries",
        "bt709",
        "-color_trc",
        "bt709",
        "-color_range",
        "pc",
        "-i",
        "pipe:0",
        # 输入 1：音频
        "-i",
        str(audio_path),
        "-map",
        "0:v",
        "-map",
        "1:a",
        # RGB full-range → BT.709 limited-range YUV420P；显式写出矩阵，
        # 避免 FFmpeg 按输入尺寸猜测 BT.601/BT.709。
        "-vf",
        "scale=in_range=full:out_range=tv:in_color_matrix=bt709:out_color_matrix=bt709,format=yuv420p",
        "-c:v",
        encoder,
        *_encoder_options(encoder, video_bitrate),
        # 1080p 歌词视频按 H.264 High Profile 输出；三种硬件编码器和
        # libx264 都接受该 profile，播放器兼容性也比默认 profile 明确。
        "-profile:v",
        "high",
        "-pix_fmt",
        "yuv420p",
        "-colorspace",
        "bt709",
        "-color_primaries",
        "bt709",
        "-color_trc",
        "bt709",
        "-color_range",
        "tv",
        "-g",
        str(2 * fps),
        "-c:a",
        "aac",
        "-b:a",
        audio_bitrate,
        "-ar",
        "48000",
        "-frames:v",
        str(frames),
        "-shortest",
        "-movflags",
        "+faststart",
        str(output_path),
    ]


# ---------------------------------------------------------------- rawvideo 管道


class EncoderSession:
    """ffmpeg 编码子进程：write_frame() 逐帧写原始帧缓冲。"""

    def __init__(self, command: list[str], bufsize: int = PIPE_BUFSIZE) -> None:
        self.command = command
        self._bufsize = bufsize
        self._proc: subprocess.Popen | None = None
        self._stderr_tail = b""
        self._stderr_thread: threading.Thread | None = None
        self._stderr_lock = threading.Lock()

    def __enter__(self) -> EncoderSession:
        try:
            self._proc = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                bufsize=self._bufsize,
                creationflags=_CREATE_NO_WINDOW,
            )
        except OSError as exc:
            raise EncoderError(f"无法启动 ffmpeg: {exc}") from exc

        # 不在 finish() 才读取 stderr：当 ffmpeg 反复报错时，PIPE 缓冲区
        # 可能先被写满，wait() 会与子进程互相等待，表现为 Windows 导出卡死。
        if self._proc.stderr is not None:
            self._stderr_thread = threading.Thread(
                target=self._drain_stderr,
                args=(self._proc.stderr,),
                name="lvm-ffmpeg-stderr",
                daemon=True,
            )
            self._stderr_thread.start()
        return self

    def write_frame(
        self, frame: bytes | bytearray | memoryview | np.ndarray
    ) -> None:
        """写入一帧原始帧，优先接受不复制的连续 buffer 视图。"""
        if self._proc is None or self._proc.stdin is None:
            raise EncoderError("编码会话未启动")
        poll = getattr(self._proc, "poll", None)
        if poll is not None:
            try:
                returncode = poll()
            except OSError:
                returncode = None
            if isinstance(returncode, int):
                raise EncoderError(
                    self._diagnostic(f"ffmpeg 已退出（退出码 {returncode}）")
                )
        try:
            if isinstance(frame, np.ndarray):
                # 保留对旧调用方/测试中 ndarray 的兼容；生产导出传入
                # QImage 的 memoryview，不会走这条分配路径。
                raw = memoryview(np.ascontiguousarray(frame, dtype=np.uint8))
            else:
                raw = memoryview(frame)
                if not raw.contiguous:
                    raw = memoryview(bytes(raw))
            if raw.format != "B" or raw.ndim != 1:
                raw = raw.cast("B")
            self._proc.stdin.write(raw)
        except (TypeError, ValueError) as exc:
            raise EncoderError("帧缓冲必须是连续的 byte buffer") from exc
        except (BrokenPipeError, OSError) as exc:
            # BrokenPipeError 是 OSError 子类；统一转为可触发硬件回退的
            # EncoderError，并保留 ffmpeg 的最后一段诊断信息。
            raise EncoderError(self._diagnostic("ffmpeg 管道已中断")) from exc

    def finish(self) -> None:
        """正常收尾：关 stdin，等待 ffmpeg 退出；非零退出码抛 EncoderError。"""
        proc = self._proc
        if proc is None:
            return
        close_error: OSError | None = None
        if self._proc.stdin is not None:
            try:
                self._proc.stdin.close()
            except OSError as exc:
                close_error = exc
        if close_error is not None:
            self.abort()
            raise EncoderError(self._diagnostic("关闭 ffmpeg 管道失败")) from close_error
        try:
            returncode = proc.wait()
        except (OSError, subprocess.SubprocessError) as exc:
            self.abort()
            raise EncoderError("等待 ffmpeg 结束失败") from exc
        self._join_stderr()
        stderr_tail = self._stderr_text()
        self._proc = None
        if returncode != 0:
            raise EncoderError(stderr_tail or f"ffmpeg 退出码 {returncode}")

    def abort(self) -> None:
        """取消：杀进程（用于导出中断）。"""
        proc = self._proc
        if proc is None:
            return
        if proc.stdin is not None:
            with contextlib.suppress(OSError):
                proc.stdin.close()
        with contextlib.suppress(OSError, ProcessLookupError):
            proc.kill()
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            proc.wait()
        self._join_stderr()
        self._proc = None

    def _diagnostic(self, fallback: str) -> str:
        """stderr 尾部信息，空则用 fallback。"""
        text = self._stderr_text()
        return text if text else fallback

    def _stderr_text(self) -> str:
        with self._stderr_lock:
            tail = self._stderr_tail
        return tail.decode("utf-8", "replace")

    def _drain_stderr(self, stream) -> None:
        """持续读取 stderr，只保留尾部诊断，避免子进程被 PIPE 背压。"""
        try:
            while True:
                chunk = stream.read(16 * 1024)
                if not chunk:
                    break
                if not isinstance(chunk, (bytes, bytearray, memoryview)):
                    # 也让测试替身/非标准 Popen 实现安全结束，不在后台
                    # 线程里对一个永久返回 Mock 的 read() 忙等。
                    break
                with self._stderr_lock:
                    self._stderr_tail = (
                        self._stderr_tail + bytes(chunk)
                    )[-STDERR_TAIL_BYTES:]
        except (OSError, ValueError):
            # 取消时父线程可能先关闭管道；此时已有的尾部信息仍然有效。
            return

    def _join_stderr(self) -> None:
        thread = self._stderr_thread
        if thread is not None:
            thread.join(timeout=1.0)
            self._stderr_thread = None

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._proc is not None:
            self.abort()


# ---------------------------------------------------------------- 颜色空间转换


# BT.709 系数
_KR = 0.2126
_KB = 0.0722


def rgb_to_yuv420p(rgb: np.ndarray) -> np.ndarray:
    """RGB (H, W, 3) uint8 → yuv420p (H*3/2, W) uint8（BT.709，limited range）。

    Python 侧先转再喂管道（Windows 上比 rgb24 管道约减半带宽）。
    H、W 必须为偶数（1920×1080 满足）。
    """
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError(f"期望 (H, W, 3) RGB 数组，得到 {rgb.shape}")
    h, w = rgb.shape[:2]
    if h % 2 or w % 2:
        raise ValueError(f"宽高必须为偶数: {w}x{h}")

    src = rgb.astype(np.float32) / 255.0
    r, g, b = src[..., 0], src[..., 1], src[..., 2]
    y = _KR * r + (1.0 - _KR - _KB) * g + _KB * b
    pb = (b - y) / (2.0 * (1.0 - _KB))
    pr = (r - y) / (2.0 * (1.0 - _KR))

    y_code = np.clip(16.0 + 219.0 * y, 16.0, 235.0)
    cb_code = np.clip(128.0 + 224.0 * pb, 16.0, 240.0)
    cr_code = np.clip(128.0 + 224.0 * pr, 16.0, 240.0)

    # 2×2 下采样取平均
    cb = (
        cb_code[0::2, 0::2]
        + cb_code[1::2, 0::2]
        + cb_code[0::2, 1::2]
        + cb_code[1::2, 1::2]
    ) * 0.25
    cr = (
        cr_code[0::2, 0::2]
        + cr_code[1::2, 0::2]
        + cr_code[0::2, 1::2]
        + cr_code[1::2, 1::2]
    ) * 0.25

    y_plane = y_code.astype(np.uint8)
    cb_plane = cb.astype(np.uint8)
    cr_plane = cr.astype(np.uint8)
    # yuv420p 帧布局：Y(h,w) + Cb(h/2,w/2) + Cr(h/2,w/2) 顺序字节流
    return np.concatenate(
        [y_plane.ravel(), cb_plane.ravel(), cr_plane.ravel()]
    ).reshape(h * 3 // 2, w)
