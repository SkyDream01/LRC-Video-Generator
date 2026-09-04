"""时间轴测试：bisect 当前行定位、行区间边界。"""

from app.core.lrc import parse_lrc
from app.core.timeline import current_index, line_intervals, line_starts, locate


def _doc(text: str):
    return parse_lrc(text).lines


def test_intervals_chain():
    lines = _doc("[00:01.00]A\n[00:05.00]B\n[00:09.00]C\n")
    intervals = line_intervals(lines, 12.0)
    assert intervals == [(1.0, 5.0), (5.0, 9.0), (9.0, 12.0)]


def test_last_line_end_uses_duration():
    lines = _doc("[00:01.00]A\n[00:02.00]B\n")
    intervals = line_intervals(lines, 10.0)
    assert intervals[-1][1] == 10.0


def test_last_line_end_fallback_without_duration():
    lines = _doc("[00:01.00]A\n")
    intervals = line_intervals(lines, None)
    assert intervals[-1][1] == 6.0  # start + DEFAULT_TAIL_S


def test_current_index_bisect():
    starts = [1.0, 5.0, 9.0]
    assert current_index(starts, 0.5) == -1  # 首行前
    assert current_index(starts, 1.0) == 0
    assert current_index(starts, 4.99) == 0
    assert current_index(starts, 5.0) == 1
    assert current_index(starts, 100.0) == 2  # 最后一行后
    assert current_index([], 1.0) == -1


def test_locate():
    lines = _doc("[00:01.00]A\n[00:05.00]B\n")
    idx, intervals = locate(lines, 10.0, 6.0)
    assert idx == 1
    assert len(intervals) == 2


def test_line_starts_sorted():
    lines = _doc("[00:10.00]B\n[00:01.00]A\n")
    assert line_starts(line_intervals(lines, None)) == [1.0, 10.0]
