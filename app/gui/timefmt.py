"""时间格式化助手（时间轴刻度 / 输入面板信息 / 状态栏共用）。"""

__all__ = ["format_time"]


def format_time(t: float) -> str:
    """秒 → mm:ss.d（负数按 0 处理）。"""
    tenths = round(max(0.0, t) * 10)
    minutes, rest = divmod(tenths, 600)
    return f"{minutes:02d}:{rest / 10.0:04.1f}"
