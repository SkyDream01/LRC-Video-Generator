"""演示工程生成：确定性合成音频/封面/LRC，供 CLI 冒烟出片与 M1 验收。

不依赖 ffmpeg（音频用 wave 标准库写出），全部产物按固定种子可复现。
"""

from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np
from PIL import Image

from .project import KProj, save_kproj

DEMO_DURATION_S = 8.0
DEMO_SAMPLE_RATE = 48000

_DEMO_LRC = """[ti:LVM Demo Song]
[ar:LVM]
[al:Milestone M1]
[00:00.50]First line of the demo song
[00:00.50]演示歌曲的第一行
[00:02.50]Second line shines bright
[00:02.50]第二行闪亮登场
[00:04.50]第三行只有中文没有译文
[00:06.00]The final line fades out
[00:06.00]最后一行缓缓淡出
"""


def make_demo_audio(
    path: Path, duration: float = DEMO_DURATION_S, sample_rate: int = DEMO_SAMPLE_RATE
) -> Path:
    """双声道 440/660Hz 正弦 + 结尾淡出（int16 PCM WAV）。"""
    n = round(duration * sample_rate)
    t = np.arange(n, dtype=np.float64) / sample_rate
    fade = np.clip((duration - t) / 1.5, 0.0, 1.0)
    left = 0.35 * np.sin(2.0 * math.pi * 440.0 * t) * fade
    right = 0.35 * np.sin(2.0 * math.pi * 660.0 * t) * fade
    pcm = (np.stack([left, right], axis=1) * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())
    return path


def make_demo_cover(path: Path, size: int = 600) -> Path:
    """对角渐变 + 圆形装饰的演示封面（无文字，避免字体依赖）。"""
    xs = np.linspace(0.0, 1.0, size, dtype=np.float64)
    grad = xs[None, :] * 0.6 + xs[:, None] * 0.4  # 对角权重
    top = np.array([46.0, 134.0, 171.0])  # 深青
    bottom = np.array([246.0, 162.0, 30.0])  # 暖橙
    arr = (
        top[None, None, :] * (1.0 - grad[..., None])
        + bottom[None, None, :] * grad[..., None]
    )

    yy, xx = np.mgrid[0:size, 0:size]
    d1 = np.sqrt((xx - size * 0.32) ** 2 + (yy - size * 0.38) ** 2)
    d2 = np.sqrt((xx - size * 0.70) ** 2 + (yy - size * 0.66) ** 2)
    for d, radius, color in (
        (d1, size * 0.16, (255, 255, 255)),
        (d2, size * 0.22, (20, 30, 40)),
    ):
        mask = np.clip(1.0 - np.abs(d - radius) / 24.0, 0.0, 1.0) * 0.55
        arr = (
            arr * (1.0 - mask[..., None])
            + np.asarray(color, dtype=np.float64)[None, None, :] * mask[..., None]
        )

    Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB").save(path)
    return path


def make_demo_project(work_dir: str | Path) -> tuple[KProj, Path]:
    """在 work_dir 下生成 demo.mp3 同款 WAV/封面/LRC 与 .kproj，返回 (工程, kproj 路径)。"""
    base = Path(work_dir)
    base.mkdir(parents=True, exist_ok=True)
    audio = make_demo_audio(base / "demo.wav")
    cover = make_demo_cover(base / "demo_cover.png")
    lrc = base / "demo.lrc"
    lrc.write_text(_DEMO_LRC, encoding="utf-8")

    project = KProj()
    project.files.audio = str(audio)
    project.files.cover = str(cover)
    project.files.lrc = str(lrc)
    project.animations.background.type = "gradient_wave"
    project.animations.lyrics.type = "scroll_list"
    project.animations.cover.type = "disc_rotate"
    kproj_path = save_kproj(project, base / "demo.kproj")
    return project, kproj_path
