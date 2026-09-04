"""encoder 测试：mock 探测回退链、编码命令规格校验、yuv420p 转换。"""

import subprocess
from unittest import mock

import numpy as np
import pytest

from app.core import encoder
from app.core.encoder import (
    ENCODER_FALLBACK_CHAIN,
    build_encode_command,
    detect_encoder,
    probe_duration_ffprobe,
    probe_encoder,
    rgb_to_yuv420p,
)


def _completed(returncode: int) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=b"", stderr=b""
    )


def test_fallback_chain_order():
    assert ENCODER_FALLBACK_CHAIN == ("h264_nvenc", "h264_amf", "h264_qsv", "libx264")


def test_detect_encoder_prefers_nvenc():
    with mock.patch.object(encoder, "_run", return_value=_completed(0)):
        assert detect_encoder("ffmpeg") == "h264_nvenc"


def test_detect_encoder_skips_failing_and_picks_amf():
    responses = {
        "h264_nvenc": _completed(1),
        "h264_amf": _completed(0),
        "h264_qsv": _completed(0),
    }

    def fake_run(cmd, **kwargs):
        return responses[cmd[cmd.index("-c:v") + 1]]

    with mock.patch.object(encoder, "_run", side_effect=fake_run):
        assert detect_encoder("ffmpeg") == "h264_amf"


def test_detect_encoder_falls_back_to_libx264():
    with mock.patch.object(encoder, "_run", return_value=_completed(1)):
        assert detect_encoder("ffmpeg") == "libx264"


def test_probe_encoder_handles_subprocess_error():
    with mock.patch.object(
        encoder, "_run", side_effect=subprocess.TimeoutExpired(cmd=[], timeout=1)
    ):
        assert probe_encoder("ffmpeg", "h264_nvenc") is False


def test_build_encode_command_contains_spec_flags():
    cmd = build_encode_command(
        ffmpeg="ffmpeg",
        width=1920,
        height=1080,
        fps=60,
        frames=300,
        audio_path="a.flac",
        output_path="out.mp4",
        encoder="libx264",
    )
    joined = " ".join(cmd)
    assert "-pix_fmt rgb24" in joined
    assert "-color_range pc" in joined
    assert (
        "-vf scale=in_range=full:out_range=tv:in_color_matrix=bt709:"
        "out_color_matrix=bt709,format=yuv420p"
    ) in joined
    assert "-frames:v 300" in joined
    assert "-g 120" in joined
    assert "-colorspace bt709" in joined
    assert "-color_primaries bt709" in joined
    assert "-color_trc bt709" in joined
    assert "-color_range tv" in joined
    assert "+faststart" in joined
    assert "-c:a aac" in joined
    assert "-b:a 320k" in joined
    assert "-ar 48000" in joined
    assert "pipe:0" in cmd
    assert "-c:v libx264 -preset medium -crf 17" in joined


def test_build_encode_command_hardware_options():
    cmd = build_encode_command(
        ffmpeg="ffmpeg",
        width=64,
        height=64,
        fps=30,
        frames=1,
        audio_path="a.wav",
        output_path="o.mp4",
        encoder="h264_nvenc",
    )
    joined = " ".join(cmd)
    assert "-c:v h264_nvenc -preset p5 -rc vbr -cq 19" in joined


def test_build_encode_command_unknown_encoder_forced_libx264():
    cmd = build_encode_command(
        ffmpeg="f",
        width=64,
        height=64,
        fps=30,
        frames=1,
        audio_path="a.wav",
        output_path="o.mp4",
        encoder="mpeg4",
    )
    assert "-c:v libx264" in " ".join(cmd)


def test_encoder_session_accepts_memoryview_without_numpy_conversion():
    process = mock.Mock()
    process.stdin = mock.Mock()
    process.stderr = None
    process.poll.return_value = None
    process.wait.return_value = 0
    with mock.patch.object(encoder.subprocess, "Popen", return_value=process):
        with encoder.EncoderSession(["ffmpeg"]) as session:
            frame = memoryview(b"\0" * 6)
            session.write_frame(frame)

    written = process.stdin.write.call_args.args[0]
    assert isinstance(written, memoryview)
    assert written.tobytes() == b"\0" * 6


def test_rgb_to_yuv420p_reference_values():
    white = rgb_to_yuv420p(np.full((64, 64, 3), 255, dtype="uint8"))
    assert white.shape == (96, 64)  # 64 * 1.5
    assert white[0, 0] == 235  # limited range 白
    black = rgb_to_yuv420p(np.zeros((64, 64, 3), dtype="uint8"))
    assert black[0, 0] == 16
    # 色度平面为中性灰
    assert white[64, 0] == 128 and white[64, 32] == 128


def test_rgb_to_yuv420p_deterministic():
    rng = np.random.default_rng(7)
    rgb = rng.integers(0, 256, size=(32, 32, 3), dtype="uint8")
    a = rgb_to_yuv420p(rgb)
    b = rgb_to_yuv420p(rgb)
    assert np.array_equal(a, b)


def test_rgb_to_yuv420p_rejects_odd_dimensions():
    with pytest.raises(ValueError):
        rgb_to_yuv420p(np.zeros((33, 64, 3), dtype="uint8"))


def test_probe_duration_ffprobe_parses_output():
    proc = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=b"12.5\n", stderr=b""
    )
    with mock.patch.object(encoder, "_run", return_value=proc):
        assert probe_duration_ffprobe("ffprobe", "a.flac") == 12.5


def test_probe_duration_ffprobe_failure_returns_none():
    proc = subprocess.CompletedProcess(args=[], returncode=1, stdout=b"", stderr=b"err")
    with mock.patch.object(encoder, "_run", return_value=proc):
        assert probe_duration_ffprobe("ffprobe", "a.flac") is None
    with mock.patch.object(
        encoder, "_run", side_effect=subprocess.SubprocessError("boom")
    ):
        assert probe_duration_ffprobe("ffprobe", "a.flac") is None
