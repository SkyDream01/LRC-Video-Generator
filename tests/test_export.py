"""离屏导出冒烟测试（qt 标记；需要 ffmpeg，缺失时 skip）。"""

import subprocess
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.qt

from app.core.encoder import find_binary  # noqa: E402


def _require_ffmpeg() -> str:
    ffmpeg = find_binary("ffmpeg")
    if not ffmpeg:
        pytest.skip("未找到 ffmpeg，跳过导出冒烟测试")
    return ffmpeg


@pytest.mark.parametrize("encoder", ["auto", "libx264"])
def test_render_video_smoke(tmp_path: Path, encoder):
    from app.core.demo import make_demo_project
    from app.gui.exporter import render_video

    _require_ffmpeg()
    work = tmp_path / "demo"
    project, _kproj = make_demo_project(work)
    progress: list[tuple[int, int]] = []
    encoders: list[str] = []
    project.output.encoder = encoder
    result = render_video(
        project,
        work,
        tmp_path / "out.mp4",
        max_frames=30,
        encoder_changed=encoders.append,
        progress=lambda done, total: progress.append((done, total)),
    )

    assert result.frames == 30
    assert encoders[-1] == result.encoder
    if encoder == "libx264":
        assert encoders == ["libx264"]
    assert result.output.exists()
    assert result.output.stat().st_size > 1000
    assert (1, 30) in progress
    assert progress[-1] == (30, 30)
    assert len(progress) <= 13  # 一次运行 6 次；硬件回退最多再跑一次

    ffprobe = find_binary("ffprobe")
    if ffprobe:
        proc = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height,r_frame_rate,nb_frames,color_space,color_primaries,color_transfer,color_range",
                "-of",
                "csv=p=0",
                str(result.output),
            ],
            capture_output=True,
            check=True,
        )
        assert b"1920,1080" in proc.stdout
        assert b"60/1" in proc.stdout
        assert b"bt709" in proc.stdout
        assert b"tv" in proc.stdout
        assert b"30" in proc.stdout.strip().split(b",")


def test_render_video_cancelled(tmp_path: Path):
    from app.core.demo import make_demo_project
    from app.gui.exporter import ExportCancelled, render_video

    _require_ffmpeg()
    work = tmp_path / "demo"
    project, _kproj = make_demo_project(work)
    with pytest.raises(ExportCancelled):
        render_video(
            project, work, tmp_path / "out.mp4", max_frames=10, cancel=lambda: True
        )
    assert not (tmp_path / "out.mp4").exists()


def test_encoder_notification_tracks_software_fallback(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from app.core.project import KProj
    from app.gui import exporter

    project = KProj()
    project.files.audio = "audio.wav"
    project.output.encoder = "h264_nvenc"
    ctx = SimpleNamespace(duration=1, audio_path=Path("audio.wav"), fps=30, width=2, height=2)
    monkeypatch.setattr(exporter, "find_binary", lambda name: "ffmpeg")
    monkeypatch.setattr(exporter, "build_context", lambda *args, **kwargs: ctx)
    monkeypatch.setattr(exporter, "Scene", Mock())
    monkeypatch.setattr(exporter.GuiAssets, "from_context", lambda ctx: SimpleNamespace(bg_image=None))
    monkeypatch.setattr(exporter, "composite", lambda *args: None)
    commands = []

    class Session:
        def __init__(self, command):
            commands.append(command)

        def __enter__(self):
            if len(commands) == 1:
                raise exporter.EncoderError("hardware failed")
            return self

        def __exit__(self, *args):
            pass

        def write_frame(self, frame):
            pass

        def finish(self):
            pass

    monkeypatch.setattr(exporter, "EncoderSession", Session)
    encoders = []
    result = exporter.render_video(
        project, tmp_path, tmp_path / "out.mp4", max_frames=1,
        encoder_changed=encoders.append,
    )
    assert encoders == ["h264_nvenc", "libx264"]
    assert [cmd[cmd.index("-c:v") + 1] for cmd in commands] == encoders
    assert result.encoder == "libx264"


def test_render_video_requires_audio(tmp_path: Path):
    # pi-lens-ignore: reportMissingImports
    from app.core.project import KProj
    from app.gui.exporter import render_video

    _require_ffmpeg()
    project = KProj()
    with pytest.raises(ValueError):
        render_video(project, tmp_path, tmp_path / "out.mp4")
