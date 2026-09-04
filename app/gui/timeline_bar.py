"""底部时间轴：播放/暂停按钮 + 自绘歌词刻度条 + 播放头 + 时间标签。

播放中由 MainWindow 的 tick 定时器喂 set_time(t)（只重绘本控件）；拖动时发
scrubStarted/scrubMoved/scrubFinished，预览即时跟随，音频 seek 由主窗口合并。
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from .timefmt import format_time

_BG_GROOVE = QColor("#0f1722")
_FILL = QColor("#43576d")
_PLAYED = QColor("#f1b86b")
_TICK = QColor("#496078")
_TICK_TEXT = QColor("#8798aa")
_HEAD = QColor("#ffffff")


class _Ruler(QWidget):
    """自绘刻度条：歌词行刻度 + 已播进度 + 播放头。"""

    scrubStarted = Signal(float)
    scrubMoved = Signal(float)
    scrubFinished = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._duration = 0.0
        self._t = 0.0
        self._starts: list[float] = []
        self._scrubbing = False
        self._hover_x = -1
        self._static_layer: QPixmap | None = None
        self._static_key: tuple[object, ...] | None = None
        self.setObjectName("timelineRuler")
        self.setMinimumHeight(40)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)

    # ---- 数据 ----

    def set_duration(self, duration: float) -> None:
        self._duration = max(0.0, duration)
        self._invalidate_static()
        self.setEnabled(self._duration > 0.0)
        self.update()

    def set_marks(self, starts: list[float]) -> None:
        self._starts = list(starts)
        self._invalidate_static()
        self.update()

    def set_time(self, t: float) -> None:
        if t == self._t:
            return
        self._t = t
        self.update()

    def is_scrubbing(self) -> bool:
        return self._scrubbing

    # ---- 坐标换算 ----

    def _t_at(self, x: int) -> float:
        w = max(1, self.width() - 2 * 10)
        ratio = min(1.0, max(0.0, (x - 10) / w))
        return ratio * self._duration

    # ---- 鼠标 ----

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        if event.button() == Qt.MouseButton.LeftButton and self._duration > 0:
            self._scrubbing = True
            t = self._t_at(event.position().toPoint().x())
            self._t = t
            self.update()
            self.scrubStarted.emit(t)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        self._hover_x = event.position().toPoint().x()
        if self._scrubbing:
            t = self._t_at(self._hover_x)
            self._t = t
            self.update()
            self.scrubMoved.emit(t)
        else:
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        if self._scrubbing and event.button() == Qt.MouseButton.LeftButton:
            self._scrubbing = False
            t = self._t_at(event.position().toPoint().x())
            self._t = t
            self.update()
            self.scrubFinished.emit(t)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        self._hover_x = -1
        self.update()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        self._invalidate_static()
        super().resizeEvent(event)

    # ---- 静态层缓存 ----

    def _invalidate_static(self) -> None:
        self._static_layer = None
        self._static_key = None

    def _static_cache_key(self) -> tuple[object, ...]:
        return (
            self.width(),
            self.height(),
            round(self.devicePixelRatioF(), 3),
            self._duration,
            tuple(self._starts),
            self.font().toString(),
        )

    def _ensure_static_layer(self) -> None:
        if self.width() <= 0 or self.height() <= 0:
            self._invalidate_static()
            return
        key = self._static_cache_key()
        if self._static_layer is not None and self._static_key == key:
            return

        dpr = max(1.0, float(self.devicePixelRatioF()))
        pixmap = QPixmap(
            max(1, round(self.width() * dpr)), max(1, round(self.height() * dpr))
        )
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            self._draw_static(painter)
        finally:
            painter.end()
        self._static_layer = pixmap
        self._static_key = key

    # ---- 绘制 ----

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        self._ensure_static_layer()
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            if self._static_layer is not None:
                p.drawPixmap(0, 0, self._static_layer)
            self._draw_dynamic(p)
        finally:
            p.end()

    def _draw_static(self, p: QPainter) -> None:
        """绘制时长、歌词刻度和空轨道等不随播放头变化的内容。"""
        w, h = self.width(), self.height()
        m = 10
        groove_y = h - 14.0
        groove_h = 6.0

        if self._duration > 0:
            p.setPen(_TICK)
            f = self.font()
            f.setPointSize(7)
            p.setFont(f)
            for start in self._starts:
                r = min(1.0, max(0.0, start / self._duration))
                x = m + r * (w - 2 * m)
                p.drawLine(round(x), 6, round(x), 14)
            p.setPen(_TICK_TEXT)
            for i, start in enumerate(self._starts):
                if i > 40:
                    break
                r = min(1.0, max(0.0, start / self._duration))
                x = m + r * (w - 2 * m)
                if i % 2 == 0 and x < w - 24:
                    p.drawText(
                        QRectF(x + 2, 2, 44, 12),
                        Qt.AlignmentFlag.AlignLeft,
                        format_time(start),
                    )

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_BG_GROOVE)
        p.drawRoundedRect(QRectF(m, groove_y, w - 2 * m, groove_h), 3, 3)

    def _draw_dynamic(self, p: QPainter) -> None:
        """绘制播放进度、悬停指示和播放头。"""
        w, h = self.width(), self.height()
        m = 10
        groove_y = h - 14.0
        groove_h = 6.0
        ratio = (
            0.0
            if self._duration <= 0
            else min(1.0, max(0.0, self._t / self._duration))
        )
        head_x = m + ratio * (w - 2 * m)

        p.setPen(Qt.PenStyle.NoPen)
        if self._duration > 0 and head_x > m:
            p.setBrush(_PLAYED)
            p.drawRoundedRect(QRectF(m, groove_y, head_x - m, groove_h), 3, 3)
        p.setBrush(_FILL)
        p.drawRoundedRect(QRectF(head_x - 1, groove_y, 2, groove_h), 1, 1)

        if self._hover_x >= m and self._duration > 0 and not self._scrubbing:
            p.setBrush(QColor(255, 255, 255, 60))
            p.drawRoundedRect(
                QRectF(self._hover_x - 1, groove_y, 2, groove_h), 1, 1
            )

        p.setBrush(_HEAD)
        p.drawEllipse(QRectF(head_x - 5, groove_y + groove_h / 2 - 5, 10, 10))


class TimelineBar(QWidget):
    """播放/暂停 + 刻度条 + 时间标签。"""

    playToggled = Signal()
    scrubStarted = Signal(float)
    scrubMoved = Signal(float)
    scrubFinished = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("timelineBar")
        self._playing = False

        self._btn = QToolButton(self)
        self._btn.setObjectName("playButton")
        self._btn.setText("▶")
        self._btn.setCheckable(False)
        self._btn.setFixedSize(36, 36)
        self._btn.setToolTip("播放 / 暂停（空格）")
        self._btn.clicked.connect(self.playToggled)

        self._ruler = _Ruler(self)
        self._ruler.scrubStarted.connect(self.scrubStarted)
        self._ruler.scrubMoved.connect(self.scrubMoved)
        self._ruler.scrubFinished.connect(self.scrubFinished)

        self._label = QLabel("00:00.0 / 00:00.0", self)
        self._label.setObjectName("timeLabel")
        mono = self._label.font()
        mono.setPointSize(9)
        self._label.setFont(mono)
        self._label.setFixedWidth(150)
        self._label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 7, 18, 9)
        layout.setSpacing(12)
        layout.addWidget(self._btn)
        layout.addWidget(self._ruler, 1)
        layout.addWidget(self._label)

        self._ruler.set_duration(0.0)

    # ---- 状态 ----

    def set_duration(self, duration: float) -> None:
        self._ruler.set_duration(duration)
        self._refresh_label()

    def set_marks(self, starts: list[float]) -> None:
        self._ruler.set_marks(starts)

    def set_time(self, t: float) -> None:
        """播放中由 tick 定时器调用；拖动时跳过（播放头已由拖动逻辑更新）。"""
        if self._ruler.is_scrubbing():
            return
        self._ruler.set_time(t)
        self._refresh_label()

    def set_playing(self, playing: bool) -> None:
        self._playing = playing
        self._btn.setText("❚❚" if playing else "▶")

    @property
    def is_scrubbing(self) -> bool:
        return self._ruler.is_scrubbing()

    @property
    def duration(self) -> float:
        return self._ruler._duration  # noqa: SLF001 - 同模块私有状态

    @property
    def time(self) -> float:
        return self._ruler._t  # noqa: SLF001 - 同模块私有状态

    def _refresh_label(self) -> None:
        text = format_time(self._ruler._t) + " / " + format_time(self._ruler._duration)
        if text != self._label.text():
            self._label.setText(text)
