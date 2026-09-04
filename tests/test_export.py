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


def test_render_video_smoke(tmp_path: Path):
    from app.core.demo import make_demo_project
    from app.gui.exporter import render_video

    _require_ffmpeg()
    work = tmp_path / "demo"
    project, _kproj = make_demo_project(work)
    progress: list[tuple[int, int]] = []
    result = render_video(
        project,
        work,
        tmp_path / "out.mp4",
        max_frames=30,
        progress=lambda done, total: progress.append((done, total)),
    )

    assert result.frames == 30
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
                "stream=width,height,r_frame_rate,color_space,color_primaries,color_transfer,color_range",
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


def test_render_video_requires_audio(tmp_path: Path):
    # pi-lens-ignore: reportMissingImports
    from app.core.project import KProj
    from app.gui.exporter import render_video

    _require_ffmpeg()
    project = KProj()
    with pytest.raises(ValueError):
        render_video(project, tmp_path, tmp_path / "out.mp4")
