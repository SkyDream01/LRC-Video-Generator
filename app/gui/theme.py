"""LVM GUI 的统一视觉主题。

主题把系统默认控件收拢成一套夜间剪辑工作台：冷静的午夜蓝承载长时间
工作，琥珀色只强调主要动作，青绿色表达“已就绪”的状态。所有样式集中
在这里，面板本身只负责声明语义化 objectName。
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication


_QSS = """
/* ---- base / workspace ---- */
QWidget {
    background: #0d121a;
    color: #edf2f7;
    font-size: 10pt;
}
QMainWindow {
    background: #0d121a;
}
QWidget#workspace {
    background: #0d121a;
}
QWidget#inputPanel,
QWidget#paramsPanel {
    background: #141c27;
}
QWidget#previewSurface {
    background: #0a0f16;
}
QSplitter::handle {
    background: #0d121a;
}
QSplitter::handle:horizontal {
    width: 5px;
}
QSplitter::handle:hover {
    background: #2b3b4d;
}

/* ---- menu / status ---- */
QMenuBar {
    background: #111923;
    color: #aebaca;
    padding: 4px 8px;
    border-bottom: 1px solid #253344;
}
QMenuBar::item {
    padding: 6px 11px;
    border-radius: 6px;
}
QMenuBar::item:selected {
    background: #223142;
    color: #f1b86b;
}
QMenu {
    background: #18222e;
    color: #edf2f7;
    border: 1px solid #33465a;
    padding: 6px;
}
QMenu::item {
    padding: 7px 28px 7px 12px;
    border-radius: 5px;
}
QMenu::item:selected {
    background: #2b3b4d;
    color: #f1c986;
}
QMenu::separator {
    height: 1px;
    background: #2a394b;
    margin: 5px 8px;
}
QStatusBar {
    background: #111923;
    color: #8f9dad;
    border-top: 1px solid #253344;
    padding: 3px 8px;
}
QStatusBar::item {
    border: 0;
}
QLabel#statusBrand {
    color: #f1b86b;
    font-size: 9pt;
    font-weight: 700;
    padding: 0 8px 0 2px;
}
QLabel#statusMetric {
    color: #aebaca;
    padding: 0 8px;
}

/* ---- panel hierarchy ---- */
QLabel#panelEyebrow {
    color: #64dbc4;
    font-size: 8pt;
    font-weight: 700;
}
QLabel#panelTitle {
    color: #f5f7fa;
    font-size: 16pt;
    font-weight: 600;
}
QLabel#panelSubtitle {
    color: #8998aa;
    font-size: 9pt;
}
QGroupBox {
    background: #18222e;
    border: 1px solid #29394b;
    border-radius: 10px;
    margin-top: 17px;
    padding: 14px 10px 10px 10px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 11px;
    padding: 0 6px;
    color: #f1b86b;
    background: #141c27;
    font-weight: 600;
}
QLabel#fieldLabel {
    color: #aebaca;
    font-size: 9pt;
}
QLabel#paletteStatus {
    background: #101821;
    border: 1px solid #29394b;
    border-radius: 7px;
    padding: 7px 8px;
    color: #aebaca;
}

/* ---- fields ---- */
QLineEdit,
QComboBox,
QSpinBox,
QDoubleSpinBox {
    background: #0f1722;
    color: #edf2f7;
    border: 1px solid #2b3b4d;
    border-radius: 7px;
    padding: 5px 8px;
    min-height: 18px;
    selection-background-color: #d9984e;
    selection-color: #1a1410;
}
QLineEdit:read-only {
    color: #aebaca;
}
QLineEdit:hover,
QComboBox:hover,
QSpinBox:hover,
QDoubleSpinBox:hover {
    border-color: #46617b;
}
QLineEdit:focus,
QComboBox:focus,
QSpinBox:focus,
QDoubleSpinBox:focus {
    border: 1px solid #f1b86b;
}
QComboBox::drop-down {
    width: 25px;
    border: 0;
    border-left: 1px solid #2b3b4d;
}
QComboBox::down-arrow {
    image: none;
    width: 0;
    height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #8f9dad;
}
QComboBox QAbstractItemView {
    background: #18222e;
    color: #edf2f7;
    border: 1px solid #33465a;
    selection-background-color: #2b3b4d;
    selection-color: #f1c986;
    padding: 4px;
}
QAbstractSpinBox::up-button,
QAbstractSpinBox::down-button {
    background: transparent;
    border: 0;
    width: 17px;
}

/* ---- actions ---- */
QPushButton {
    background: #243244;
    color: #edf2f7;
    border: 1px solid #3a4d63;
    border-radius: 7px;
    padding: 6px 12px;
    min-height: 18px;
}
QPushButton:hover {
    background: #2c3d51;
    border-color: #54708d;
}
QPushButton:pressed {
    background: #1c2836;
    padding-top: 7px;
    padding-bottom: 5px;
}
QPushButton:focus,
QToolButton:focus {
    border-color: #f1b86b;
}
QPushButton:disabled,
QToolButton:disabled {
    background: #1a232d;
    color: #596676;
    border-color: #263342;
}
QPushButton#browseButton {
    min-width: 50px;
    padding-left: 8px;
    padding-right: 8px;
}
QPushButton#demoButton {
    background: #17322f;
    color: #76dfca;
    border-color: #2d665d;
    min-height: 22px;
}
QPushButton#demoButton:hover {
    background: #1e443f;
    border-color: #4b9b8c;
}
QPushButton#restoreButton {
    background: transparent;
    color: #aebaca;
    border-color: #33465a;
}
QPushButton#restoreButton:hover {
    color: #f1c986;
    background: #1b2938;
}
QPushButton#clearButton {
    color: #e99b89;
    border-color: #65413f;
    padding: 3px 7px;
}
QPushButton#clearButton:hover {
    background: #3a2426;
    border-color: #a65d57;
}
QPushButton#exportButton {
    background: #f1b86b;
    color: #21170e;
    border: 1px solid #f6ca8b;
    border-radius: 8px;
    font-weight: 700;
    padding: 7px 16px;
    min-width: 90px;
}
QPushButton#exportButton:hover {
    background: #f7c982;
    color: #21170e;
}
QPushButton#exportButton:pressed {
    background: #d99a50;
}
QPushButton#exportButton:disabled {
    background: #3d3428;
    color: #907e65;
    border-color: #5a4935;
}

/* ---- tabs / checks ---- */
QTabWidget#settingsTabs::pane {
    background: #151f2b;
    border: 1px solid #29394b;
    border-radius: 10px;
    top: -1px;
}
QTabWidget#settingsTabs QTabBar::tab {
    background: transparent;
    color: #8796a8;
    padding: 8px 10px;
    margin-right: 2px;
    border: 1px solid transparent;
    border-bottom: 2px solid transparent;
}
QTabWidget#settingsTabs QTabBar::tab:hover {
    color: #d6dde5;
    background: #192632;
}
QTabWidget#settingsTabs QTabBar::tab:selected {
    color: #f1c986;
    background: #1b2938;
    border: 1px solid #33465a;
    border-bottom: 2px solid #f1b86b;
}
QCheckBox {
    color: #c6d0db;
    spacing: 8px;
    padding: 3px 0;
}
QCheckBox::indicator {
    width: 15px;
    height: 15px;
    background: #0f1722;
    border: 1px solid #46617b;
    border-radius: 4px;
}
QCheckBox::indicator:hover {
    border-color: #64dbc4;
}
QCheckBox::indicator:checked {
    background: #64dbc4;
    border-color: #83ead6;
}
QCheckBox::indicator:checked:disabled {
    background: #34534f;
    border-color: #4f756e;
}

/* ---- timeline ---- */
QWidget#timelineBar {
    background: #141c27;
    border-top: 1px solid #2a394b;
}
QToolButton#playButton {
    background: #f1b86b;
    color: #21170e;
    border: 1px solid #f6ca8b;
    border-radius: 18px;
    font-size: 12pt;
    font-weight: 700;
    padding: 0;
}
QToolButton#playButton:hover {
    background: #f7c982;
}
QToolButton#playButton:pressed {
    background: #d99a50;
}
QLabel#timeLabel {
    background: #0f1722;
    color: #f1c986;
    border: 1px solid #2f4155;
    border-radius: 7px;
    padding: 5px 9px;
    font-weight: 600;
}

/* ---- progress / scroll ---- */
QProgressBar {
    background: #0f1722;
    color: #dce5ed;
    border: 1px solid #2b3b4d;
    border-radius: 6px;
    text-align: center;
    min-height: 16px;
}
QProgressBar::chunk {
    background: #64dbc4;
    border-radius: 5px;
}
QScrollBar:vertical {
    background: #111923;
    width: 10px;
    margin: 3px 2px 3px 0;
}
QScrollBar::handle:vertical {
    background: #34485d;
    min-height: 28px;
    border-radius: 5px;
}
QScrollBar::handle:vertical:hover {
    background: #4e6882;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: transparent;
    height: 0;
}
QToolTip {
    background: #18222e;
    color: #edf2f7;
    border: 1px solid #46617b;
    padding: 5px 7px;
}
"""


def _ui_font() -> QFont:
    """挑选中文 Windows 与跨平台环境都较稳定的 UI 字体。"""
    installed = set(QFontDatabase.families())
    for family in (
        "Microsoft YaHei UI",
        "Microsoft YaHei",
        "Noto Sans CJK SC",
        "Source Han Sans SC",
        "Segoe UI",
    ):
        if family in installed:
            return QFont(family, 10)
    return QFont("Sans Serif", 10)


def apply_theme(app: QApplication) -> None:
    """将 LVM 主题应用到 QApplication（可重复调用）。"""
    app.setStyle("Fusion")
    app.setFont(_ui_font())

    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#0d121a"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#edf2f7"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#0f1722"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#18222e"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#edf2f7"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#243244"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#edf2f7"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#d9984e"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#1a1410"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#18222e"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#edf2f7"))
    app.setPalette(palette)
    app.setStyleSheet(_QSS)

