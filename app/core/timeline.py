"""时间轴：行区间计算与 bisect 当前行定位。"""

from __future__ import annotations

from bisect import bisect_right

from .lrc import LyricLine

# 音频时长未知时，最后一行的兜底持续时长（秒）
DEFAULT_TAIL_S = 5.0


def line_intervals(
    lines: list[LyricLine], total_duration: float | None
) -> list[tuple[float, float]]:
    """计算每行区间 [start, end)：end = 下一行 start；最后一行 end = 音频总时长（未知则 start + 兜底）。"""
    if not lines:
        return []
    intervals: list[tuple[float, float]] = []
    for i, line in enumerate(lines):
        start = max(0.0, line.time)
        if i + 1 < len(lines):
            end = max(start, max(0.0, lines[i + 1].time))
        else:
            end = start + (
                total_duration - start
                if total_duration and total_duration > start
                else DEFAULT_TAIL_S
            )
        intervals.append((start, end))
    return intervals


def line_starts(intervals: list[tuple[float, float]]) -> list[float]:
    """行起始时间列表（供 bisect 使用，保证升序）。"""
    return [iv[0] for iv in intervals]


def current_index(starts: list[float], t: float) -> int:
    """bisect 定位当前行：返回区间索引，t 在首行之前返回 -1。O(log n)。"""
    if not starts:
        return -1
    idx = bisect_right(starts, t) - 1
    return idx if idx >= 0 else -1


def locate(
    lines: list[LyricLine], total_duration: float | None, t: float
) -> tuple[int, list[tuple[float, float]]]:
    """一步到位：给定行列表与总时长，返回 (当前行索引, 行区间)。"""
    intervals = line_intervals(lines, total_duration)
    return current_index(line_starts(intervals), t), intervals
