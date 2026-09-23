"""导出速度、剩余时间与编码器重试的确定性测试。"""

import pytest

from app.gui.export_timing import ExportTiming


def test_estimate_and_stalled_progress():
    timing = ExportTiming(100.0, 60, 100.0)
    assert timing.estimate(100.0) == (None, None)
    timing.update(600, 1800, 105.0)
    assert timing.estimate(105.0) == pytest.approx((10.0, 2.0))
    assert timing.estimate(110.0) == pytest.approx((20.0, 1.0))
    assert timing.elapsed(110.0) == 10.0


def test_retry_resets_estimate_but_keeps_total_elapsed():
    timing = ExportTiming(100.0, 30, 100.0)
    timing.update(300, 900, 110.0)
    timing.update(0, 900, 115.0)
    assert timing.estimate(115.0) == (None, None)
    timing.update(300, 900, 120.0)
    assert timing.estimate(120.0) == pytest.approx((10.0, 2.0))
    assert timing.elapsed(120.0) == 20.0
    timing.update(900, 900, 130.0)
    assert timing.estimate(130.0) == pytest.approx((0.0, 2.0))
