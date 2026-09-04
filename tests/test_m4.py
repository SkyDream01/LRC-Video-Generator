"""M4 回归：编码会话不会被 stderr 背压卡住，取消会杀掉子进程。"""

from __future__ import annotations

import io
from unittest import mock

import numpy as np

from app.core import encoder
from app.core.encoder import EncoderSession, PIPE_BUFSIZE


class _FakeStdin:
    def __init__(self) -> None:
        self.data = bytearray()
        self.closed = False

    def write(self, value) -> int:
        raw = bytes(value)
        self.data.extend(raw)
        return len(raw)

    def close(self) -> None:
        self.closed = True


class _FakeProcess:
    def __init__(self, returncode: int = 0) -> None:
        self.stdin = _FakeStdin()
        self.stderr = io.BytesIO(b"ffmpeg diagnostic")
        self.returncode = returncode
        self.ended = False
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode if self.ended else None

    def wait(self) -> int:
        self.ended = True
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.ended = True


def test_encoder_session_drains_stderr_and_uses_large_pipe_buffer():
    process = _FakeProcess()
    with mock.patch.object(encoder.subprocess, "Popen", return_value=process) as popen:
        with EncoderSession(["ffmpeg", "-i", "pipe:0"]) as session:
            session.write_frame(np.zeros((3, 2), dtype=np.uint8))
            session.finish()

    kwargs = popen.call_args.kwargs
    assert kwargs["bufsize"] >= PIPE_BUFSIZE
    assert kwargs["stdin"] is encoder.subprocess.PIPE
    assert process.stdin.closed
    assert bytes(process.stdin.data) == b"\0" * 6


def test_encoder_session_abort_kills_process_and_closes_input():
    process = _FakeProcess()
    with mock.patch.object(encoder.subprocess, "Popen", return_value=process):
        with EncoderSession(["ffmpeg"]) as session:
            session.abort()

    assert process.killed
    assert process.stdin.closed
