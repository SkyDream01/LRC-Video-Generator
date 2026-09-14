"""Material Design 3 深色主题：语义色、状态与所有 Qt 控件共用。"""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

COLORS = {
    "surface": "#141218", "container_low": "#1D1B20",
    "container": "#211F26", "container_high": "#2B2930",
    "on_surface": "#E6E0E9", "on_surface_variant": "#CAC4D0",
    "primary": "#D0BCFF", "on_primary": "#381E72",
    "primary_container": "#4F378B", "on_primary_container": "#EADDFF",
    "secondary_container": "#4A4458", "on_secondary_container": "#E8DEF8",
    "outline": "#938F99", "outline_variant": "#49454F",
    "error": "#F2B8B5", "disabled": "#938F99",
}

_QSS_TEMPLATE = """
QWidget { color: @on_surface; font-size: 10pt; }
QMainWindow, QDialog, QMessageBox, QWidget#workspace { background: @surface; }
QLabel, QCheckBox, QRadioButton { background: transparent; }
QWidget#inputPanel, QWidget#paramsPanel { background: @container_low; border-radius: 24px; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: @container_low; }
QSplitter::handle { background: @surface; width: 8px; }
QSplitter::handle:hover { background: @outline_variant; border-radius: 4px; }
QMenuBar { background: @surface; padding: 6px 12px; }
QMenuBar::item { padding: 8px 16px; border-radius: 16px; }
QMenuBar::item:selected { background: @secondary_container; }
QMenu { background: @container; border: 1px solid @outline_variant; border-radius: 12px; padding: 8px; }
QMenu::item { padding: 10px 32px 10px 16px; border-radius: 8px; }
QMenu::item:selected { background: @secondary_container; }
QMenu::item:disabled { color: @disabled; }
QMenu::separator { height: 1px; background: @outline_variant; margin: 6px 8px; }
QStatusBar { background: @surface; color: @on_surface_variant; padding: 8px 12px; }
QStatusBar::item { border: none; }
QLabel#statusBrand { color: @primary; font-weight: 700; padding: 0 8px; }
QLabel#statusMetric { color: @on_surface_variant; padding: 0 8px; font-size: 9pt; }
QLabel#panelEyebrow { color: @primary; font-size: 9pt; font-weight: 600; }
QLabel#panelTitle { font-size: 22pt; font-weight: 400; }
QLabel#panelSubtitle, QLabel#fieldLabel { color: @on_surface_variant; font-size: 9pt; }
QGroupBox { background: @container; border: none; border-radius: 16px; margin-top: 24px; padding: 16px 12px 12px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; color: @primary; font-weight: 600; }
QLabel#paletteStatus { background: @secondary_container; color: @on_secondary_container; border-radius: 12px; padding: 10px; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit {
    background: @surface; color: @on_surface; border: 1px solid @outline;
    border-radius: 8px; padding: 8px 10px; min-height: 22px;
    selection-background-color: @primary_container; selection-color: @on_primary_container;
}
QLineEdit:read-only { color: @on_surface_variant; }
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover { border-color: @on_surface; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTextEdit:focus, QPlainTextEdit:focus { border: 2px solid @primary; padding: 7px 9px; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled { color: @disabled; border-color: @outline_variant; background: @container_high; }
QComboBox { padding-right: 28px; }
QComboBox::drop-down { width: 24px; border: none; }
QComboBox QAbstractItemView { background: @container; color: @on_surface; border: 1px solid @outline_variant; padding: 8px; selection-background-color: @secondary_container; selection-color: @on_secondary_container; }
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button { width: 18px; border: none; }
QPushButton, QToolButton { background: @secondary_container; color: @on_secondary_container; border: 2px solid transparent; border-radius: 20px; padding: 8px 16px; min-height: 20px; font-weight: 600; }
QPushButton:hover, QToolButton:hover { background: #595267; }
QPushButton:pressed, QToolButton:pressed { background: #645C72; }
QPushButton:focus, QToolButton:focus { border-color: @primary; }
QPushButton#browseButton { padding: 8px 10px; }
QPushButton#demoButton { background: @primary_container; color: @on_primary_container; }
QPushButton#demoButton:hover { background: #60479B; }
QPushButton#restoreButton { background: transparent; color: @primary; border: 1px solid @outline; border-radius: 16px; }
QPushButton#restoreButton:hover { background: @secondary_container; }
QPushButton#clearButton { background: transparent; color: @error; padding: 6px 2px; border-radius: 16px; }
QPushButton#clearButton:hover { background: #601410; }
QPushButton#exportButton, QToolButton#playButton { background: @primary; color: @on_primary; }
QPushButton#exportButton:hover, QToolButton#playButton:hover { background: #DACBFF; }
QPushButton#exportButton:pressed, QToolButton#playButton:pressed { background: #BEA6F0; }
QPushButton#exportButton:focus, QToolButton#playButton:focus { border-color: @on_primary_container; }
QToolButton#playButton { border-radius: 18px; padding: 0; font-size: 14pt; }
QPushButton:disabled, QToolButton:disabled, QPushButton#exportButton:disabled, QPushButton#demoButton:disabled { background: @container_high; color: @disabled; border-color: transparent; }
QTabWidget::pane { background: @container_low; border: none; }
QTabBar::tab { background: transparent; color: @on_surface_variant; padding: 12px 10px; border-bottom: 3px solid transparent; }
QTabBar::tab:hover { background: @container_high; }
QTabBar::tab:selected { color: @primary; border-bottom: 3px solid @primary; }
QCheckBox, QRadioButton { spacing: 10px; padding: 6px 0; }
QCheckBox:focus, QRadioButton:focus { color: @primary; }
QCheckBox:disabled, QRadioButton:disabled { color: @disabled; }
QWidget#timelineBar { background: @container; border-radius: 24px; }
QLabel#timeLabel { background: @secondary_container; color: @on_secondary_container; border-radius: 16px; padding: 8px 10px; }
QProgressBar { background: @secondary_container; color: @on_surface; border: none; border-radius: 8px; text-align: center; min-height: 18px; }
QProgressBar::chunk { background: @primary_container; border-radius: 8px; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 4px 1px; }
QScrollBar::handle:vertical { background: @outline_variant; min-height: 32px; border-radius: 4px; }
QScrollBar::handle:vertical:hover { background: @outline; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 1px 4px; }
QScrollBar::handle:horizontal { background: @outline_variant; min-width: 32px; border-radius: 4px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QAbstractItemView { background: @surface; alternate-background-color: @container; selection-background-color: @secondary_container; selection-color: @on_secondary_container; border: 1px solid @outline_variant; }
QHeaderView::section { background: @container; color: @on_surface_variant; border: none; padding: 8px; }
QSlider::groove:horizontal { height: 8px; background: @secondary_container; border-radius: 4px; }
QSlider::sub-page:horizontal { background: @primary; border-radius: 4px; }
QSlider::handle:horizontal { background: @primary; width: 8px; margin: -6px 0; border-radius: 4px; }
QToolTip { background: @on_surface; color: @surface; border: none; padding: 8px 12px; }
"""


def _stylesheet() -> str:
    text = _QSS_TEMPLATE
    for role, value in sorted(COLORS.items(), key=lambda item: -len(item[0])):
        text = text.replace("@" + role, value)
    return text


def _ui_font() -> QFont:
    """优先选择具有完整中文字形的系统字体。"""
    installed = set(QFontDatabase.families())
    for family in ("Microsoft YaHei UI", "Noto Sans CJK SC", "Microsoft YaHei", "Segoe UI"):
        if family in installed:
            return QFont(family, 10)
    return QFont("Sans Serif", 10)


def apply_theme(app: QApplication) -> None:
    """应用统一的 MD3 配色，原生绘制的箭头与勾选标记由 Fusion 保留。"""
    app.setStyle("Fusion")
    app.setFont(_ui_font())
    palette = QPalette()
    roles = {
        "Window": "surface", "WindowText": "on_surface", "Base": "surface",
        "AlternateBase": "container", "Text": "on_surface", "Button": "secondary_container",
        "ButtonText": "on_secondary_container", "Highlight": "primary",
        "HighlightedText": "on_primary", "ToolTipBase": "on_surface", "ToolTipText": "surface",
        "PlaceholderText": "on_surface_variant", "Light": "surface", "Mid": "outline_variant",
        "Dark": "outline", "Link": "primary",
    }
    for role, token in roles.items():
        palette.setColor(getattr(QPalette.ColorRole, role), QColor(COLORS[token]))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(COLORS["disabled"]))
    app.setPalette(palette)
    app.setStyleSheet(_stylesheet())
