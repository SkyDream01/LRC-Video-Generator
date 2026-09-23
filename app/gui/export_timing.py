"""导出计时与当前编码尝试的进度估算（使用单调时钟时间戳）。"""

from dataclasses import dataclass


@dataclass
class ExportTiming:
    """累计耗时保留失败尝试，剩余时间按当前尝试的平均速度估算。"""

    started: float
    fps: float
    attempt_started: float
    done: int = 0
    total: int = 0

    def update(self, done: int, total: int, now: float) -> None:
        if done < self.done:
            self.attempt_started = now
        self.total = max(0, total)
        self.done = max(0, min(done, self.total))

    def elapsed(self, now: float) -> float:
        return max(0.0, now - self.started)

    def estimate(self, now: float) -> tuple[float | None, float | None]:
        """返回预计剩余秒数、相对实时的速度；无有效样本时返回 None。"""
        elapsed = max(0.0, now - self.attempt_started)
        if self.done == 0 or elapsed == 0 or self.fps <= 0:
            return None, None
        speed = self.done / self.fps / elapsed
        remaining = elapsed * (self.total - self.done) / self.done
        return remaining, speed
