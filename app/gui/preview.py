"""预览面板：paintEvent 内只做 eval(t) + composite()，与导出共用同一合成。

- 16:9 letterbox 居中，逻辑分辨率恒 1920×1080；
- 时钟来自 AudioPlayer（纠漂时钟），paintEvent 不读 QMediaPlayer.position()；
- prepare 期间保留上一份 assets，叠半透明「更新中…」提示；
- 「精确预览」：离屏 1920×1080 合成一帧再缩小显示（与导出像素一致）。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QWidget

from .composite import composite

if TYPE_CHECKING:
    from PySide6.QtGui import QImage, QPaintEvent

    from .workers import PreparedSession

CANVAS_W = 1920
CANVAS_H = 1080

_BG = QColor("#0a0f16")
_HINT = QColor("#8998aa")
_ACCENT = QColor("#64dbc4")
_FRAME = QColor(255, 255, 255, 20)


class PreviewSurface(QWidget):
    """实时预览控件。payload 由 ProjectController 提供，时钟由 MainWindow 注入。"""

    fpsChanged = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("previewSurface")
        self._payload: PreparedSession | None = None
        self._preparing = False
        self._exact_frame: QImage | None = None
        self._t_provider: Callable[[], float] = lambda: 0.0
        self._fps_window_start = time.monotonic()
        self._fps_count = 0
        self.setMinimumSize(320, 180)
        self.setSizePolicy(self.sizePolicy().horizontalPolicy(), self.sizePolicy().verticalPolicy())
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)

    # ---- 注入 ----

    def set_session(self, payload: PreparedSession | None) -> None:
        self._payload = payload
        self._exact_frame = None
        self.update()

    def set_preparing(self, preparing: bool) -> None:
        self._preparing = preparing
        self.update()

    def set_t_provider(self, provider: Callable[[], float]) -> None:
        self._t_provider = provider

    def set_exact_frame(self, frame: QImage | None) -> None:
        self._exact_frame = frame
        self.update()

    def session(self) -> PreparedSession | None:
        return self._payload

    def current_t(self) -> float:
        return self._t_provider()

    # ---- 绘制 ----

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        try:
            p.fillRect(self.rect(), _BG)
            target = self._target_rect()
            if target.isEmpty():
                return

            if self._exact_frame is not None:
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
                p.drawImage(target, self._exact_frame)
            elif self._payload is not None:
                t = self._t_provider()
                state = self._payload.scene.eval(t)
                p.save()
                p.setClipRect(target)
                p.translate(target.left(), target.top())
                p.scale(target.width() / CANVAS_W, target.height() / CANVAS_H)
                composite(p, state, self._payload.assets)
                p.restore()
                self._count_fps()
            else:
                self._draw_placeholder(p, target)

            self._draw_frame_edge(p, target)

            if self._preparing and self._payload is not None:
                self._draw_updating(p)
        finally:
            p.end()

    def _target_rect(self) -> QRectF:
        """16:9 letterbox：完整铺进控件并水平垂直居中。"""
        inset = min(18.0, max(6.0, min(self.width(), self.height()) * 0.04))
        w = self.width() - inset * 2.0
        h = self.height() - inset * 2.0
        if w <= 0 or h <= 0:
            return QRectF()
        scale = min(w / CANVAS_W, h / CANVAS_H)
        tw, th = CANVAS_W * scale, CANVAS_H * scale
        return QRectF(inset + (w - tw) / 2.0, inset + (h - th) / 2.0, tw, th)

    def _draw_frame_edge(self, p: QPainter, target: QRectF) -> None:
        """给 16:9 画面留一圈克制的取景边，强化预览区与工作区的分界。"""
        if target.isEmpty():
            return
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(_FRAME)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(target.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        p.restore()

    def _draw_placeholder(self, p: QPainter, target: QRectF) -> None:
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(_HINT)
        f = QFont()
        f.setPointSize(13)
        p.setFont(f)
        p.drawText(target, Qt.AlignmentFlag.AlignCenter, "加载音频与 LRC 歌词后开始预览")

    def _draw_updating(self, p: QPainter) -> None:
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        f = QFont()
        f.setPointSize(9)
        p.setFont(f)
        text = "更新中…"
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(text) + 20
        h = fm.height() + 10
        rect = QRectF(self.width() - w - 12, 12, w, h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 140))
        p.drawRoundedRect(rect, 6, 6)
        p.setPen(_ACCENT)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _count_fps(self) -> None:
        self._fps_count += 1
        now = time.monotonic()
        elapsed = now - self._fps_window_start
        if elapsed >= 1.0:
            self.fpsChanged.emit(round(self._fps_count / elapsed))
            self._fps_count = 0
            self._fps_window_start = now
