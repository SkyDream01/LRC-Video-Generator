"""左侧输入面板：音频 / 封面 / LRC / 背景四类文件选择 + 媒体信息展示。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..timefmt import format_time

MEDIA_FILTERS = {
    "audio": "音频文件 (*.mp3 *.wav *.flac *.m4a)",
    "cover": "图片文件 (*.jpg *.jpeg *.png *.webp)",
    "lrc": "LRC 歌词 (*.lrc)",
    "background": "图片文件 (*.jpg *.jpeg *.png *.webp)",
}

_ROW_TITLES = {
    "audio": "音频文件",
    "cover": "封面图片",
    "lrc": "LRC 歌词",
    "background": "背景图片（可选）",
}

_INFO_ROWS = (
    ("duration", "时长"),
    ("title", "标题"),
    ("artist", "艺术家"),
    ("album", "专辑"),
    ("lrc_lines", "LRC 行数"),
    ("cover_size", "封面尺寸"),
)


class InputPanel(QWidget):
    """文件选择与媒体信息。选择后发 mediaSelected，由主窗口触发 prepare。"""

    mediaSelected = Signal(str, str)  # key, path
    mediaCleared = Signal(str)  # key
    loadDemoRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("inputPanel")
        self._edits: dict[str, QLineEdit] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(11)

        eyebrow = QLabel("PROJECT  /  MEDIA", self)
        eyebrow.setObjectName("panelEyebrow")
        title = QLabel("素材", self)
        title.setObjectName("panelTitle")
        subtitle = QLabel("准备音乐、封面与歌词，LVM 会自动生成预览。", self)
        subtitle.setObjectName("panelSubtitle")
        subtitle.setWordWrap(True)
        root.addWidget(eyebrow)
        root.addWidget(title)
        root.addWidget(subtitle)

        files_box = QGroupBox("媒体素材", self)
        files_box.setObjectName("mediaFilesBox")
        files_form = QFormLayout(files_box)
        files_form.setSpacing(6)
        files_form.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        for key, title in _ROW_TITLES.items():
            edit = QLineEdit(files_box)
            edit.setReadOnly(True)
            edit.setPlaceholderText("未选择")
            browse = QPushButton("浏览…", files_box)
            browse.setObjectName("browseButton")
            browse.clicked.connect(lambda _=False, k=key: self._browse(k))
            row = QWidget(files_box)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(4)
            row_layout.addWidget(edit, 1)
            row_layout.addWidget(browse)
            if key == "background":
                clear = QPushButton("✕", files_box)
                clear.setObjectName("clearButton")
                clear.setFixedWidth(28)
                clear.setToolTip("清除背景图片")
                clear.clicked.connect(
                    lambda _=False: self.mediaCleared.emit("background")
                )
                row_layout.addWidget(clear)
            self._edits[key] = edit
            label = QLabel(title, files_box)
            label.setObjectName("fieldLabel")
            files_form.addRow(label, row)
        root.addWidget(files_box)

        demo = QPushButton("载入演示工程", self)
        demo.setObjectName("demoButton")
        demo.setToolTip("生成确定性演示素材（音频/封面/LRC）并加载")
        demo.clicked.connect(self.loadDemoRequested)
        root.addWidget(demo)

        info_box = QGroupBox("媒体信息", self)
        info_box.setObjectName("mediaInfoBox")
        info_form = QFormLayout(info_box)
        info_form.setSpacing(4)
        info_form.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self._info_labels: dict[str, QLabel] = {}
        for key, title in _INFO_ROWS:
            value = QLabel("—", info_box)
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self._info_labels[key] = value
            label = QLabel(title, info_box)
            label.setObjectName("fieldLabel")
            info_form.addRow(label, value)
        root.addWidget(info_box)
        root.addStretch(1)

    # ---- 状态 ----

    def set_media_path(self, key: str, path: str | None) -> None:
        edit = self._edits.get(key)
        if edit is not None:
            edit.setText(path or "")
            edit.setToolTip(path or "")

    def set_info(
        self,
        *,
        duration: float | None = None,
        title: str | None = None,
        artist: str | None = None,
        album: str | None = None,
        lrc_lines: int | None = None,
        cover_size: str | None = None,
    ) -> None:
        """刷新媒体信息；None 的项显示为 —。"""
        values: dict[str, str] = {
            "duration": format_time(duration) if duration and duration > 0 else "—",
            "title": title or "—",
            "artist": artist or "—",
            "album": album or "—",
            "lrc_lines": str(lrc_lines) if lrc_lines else "—",
            "cover_size": cover_size or "—",
        }
        for key, label in self._info_labels.items():
            label.setText(values.get(key, "—"))

    # ---- 内部 ----

    def _browse(self, key: str) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, f"选择{_ROW_TITLES[key]}", "", MEDIA_FILTERS[key]
        )
        if path:
            self.mediaSelected.emit(key, path)
