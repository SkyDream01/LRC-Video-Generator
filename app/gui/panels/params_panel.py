"""右侧参数面板：歌词样式 / 动画（按 params_schema 自动生成）/ 色彩 / 输出。

动画参数控件完全由 ANIM_REGISTRY + params_schema 生成，GUI 不写死任何动画参数
（DESIGN §4.5）；所有修改直接写入 KProj 并发 paramsChanged（主窗口 80ms 防抖 prepare）。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...core.anims.base import (
    ANIM_REGISTRY,
    KIND_BACKGROUND,
    KIND_COVER,
    KIND_LYRICS,
    KINDS,
    ParamSpec,
)
from ...core.color import Palette, rgb_to_hex
from ...core.context import APP_ROOT, FontCache
from ...core.project import KProj

_KIND_TITLES = {
    KIND_BACKGROUND: "背景动画",
    KIND_LYRICS: "歌词动画",
    KIND_COVER: "封面动画",
}

_ENCODER_ITEMS = (
    ("自动探测", "auto"),
    ("NVIDIA NVENC", "h264_nvenc"),
    ("AMD AMF", "h264_amf"),
    ("Intel QSV", "h264_qsv"),
    ("libx264 软编", "libx264"),
)

_BITRATE_PRESETS = ("8M", "12M", "16M", "24M")
_AUDIO_BITRATE_PRESETS = ("320k", "256k", "192k", "128k")


def _luma(hex_color: str) -> float:
    c = QColor(hex_color)
    return 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()


class ColorButton(QPushButton):
    """色块按钮：点击弹出 QColorDialog，显示 #RRGGBB。"""

    colorChanged = Signal(str)

    def __init__(self, color: str = "#FFFFFF", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("colorButton")
        self._color = "#FFFFFF"
        self.clicked.connect(self._pick)
        self.set_color(color)

    def color(self) -> str:
        return self._color

    def set_color(self, color: str) -> None:
        """直接设置（重绑定时用，不发信号）。"""
        candidate = QColor(color)
        self._color = (
            candidate.name(QColor.NameFormat.HexRgb).upper()
            if candidate.isValid()
            else "#FFFFFF"
        )
        self._apply_style()

    def _apply_style(self) -> None:
        fg = "#101014" if _luma(self._color) > 140 else "#FFFFFF"
        self.setText(self._color)
        self.setStyleSheet(
            f"QPushButton {{ background-color: {self._color}; color: {fg};"
            f" border: 1px solid rgba(255,255,255,0.25); border-radius: 7px;"
            f" min-height: 22px; padding: 4px 8px; }}"
        )

    def _pick(self) -> None:
        c = QColorDialog.getColor(QColor(self._color), self, "选择颜色")
        if c.isValid():
            self._color = c.name(QColor.NameFormat.HexRgb).upper()
            self._apply_style()
            self.colorChanged.emit(self._color)


@contextmanager
def _blocked(*objs: Any) -> Iterator[None]:
    for o in objs:
        o.blockSignals(True)
    try:
        yield
    finally:
        for o in objs:
            o.blockSignals(False)


class ParamsPanel(QWidget):
    """参数面板。bind(project) 后所有修改直接写 project 并发 paramsChanged。"""

    paramsChanged = Signal()
    restoreDefaultsRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("paramsPanel")
        self._project: KProj | None = None
        self._fonts = FontCache(APP_ROOT / "font")

        self._font_main = QComboBox(self)
        self._font_sub = QComboBox(self)
        self._size_main = QSpinBox(self)
        self._size_sub = QSpinBox(self)
        self._stroke_w = QSpinBox(self)
        self._color_main = ColorButton(parent=self)
        self._color_sub = ColorButton(parent=self)
        self._color_stroke = ColorButton(parent=self)

        self._anim_combos: dict[str, QComboBox] = {}
        self._anim_forms: dict[str, QFormLayout] = {}

        self._auto_extract = QCheckBox("自动从封面提取主色/辅色", self)
        self._color_primary = ColorButton(parent=self)
        self._color_secondary = ColorButton(parent=self)
        self._color_stroke2 = ColorButton(parent=self)
        self._palette_status = QLabel("当前有效取色：等待封面", self)
        self._palette_status.setObjectName("paletteStatus")
        self._palette_status.setWordWrap(True)
        self._palette_status.setTextFormat(Qt.TextFormat.RichText)

        self._fps = QComboBox(self)
        self._encoder = QComboBox(self)
        self._vbitrate = QComboBox(self)
        self._abitrate = QComboBox(self)
        self._show_meta = QCheckBox("画面叠加「标题 − 艺术家」", self)

        tabs = QTabWidget(self)
        tabs.setObjectName("settingsTabs")
        tabs.setDocumentMode(True)
        tabs.setUsesScrollButtons(False)
        tabs.addTab(self._build_style_tab(), "歌词样式")
        tabs.addTab(self._build_anim_tab(), "动画")
        tabs.addTab(self._build_color_tab(), "色彩")
        tabs.addTab(self._build_output_tab(), "输出")

        restore = QPushButton("恢复默认参数", self)
        restore.setObjectName("restoreButton")
        restore.setToolTip("恢复歌词样式、动画与色彩为默认值（保留文件与输出设置）")
        restore.clicked.connect(self.restoreDefaultsRequested)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(11)

        eyebrow = QLabel("CONTROL  /  LOOK & FEEL", self)
        eyebrow.setObjectName("panelEyebrow")
        title = QLabel("参数", self)
        title.setObjectName("panelTitle")
        subtitle = QLabel("微调歌词、动画、色彩和成片规格。", self)
        subtitle.setObjectName("panelSubtitle")
        root.addWidget(eyebrow)
        root.addWidget(title)
        root.addWidget(subtitle)
        root.addWidget(tabs, 1)
        root.addWidget(restore)

        self._connect_signals()

    # ---------------------------------------------------------------- 构建

    def _build_style_tab(self) -> QWidget:
        w = QWidget(self)
        form = QFormLayout(w)
        form.setSpacing(6)
        form.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        for combo in (self._font_main, self._font_sub):
            combo.addItem("(系统默认)", "")
            for name in self._fonts.available_fonts():
                combo.addItem(name, name)
        self._size_main.setRange(10, 300)
        self._size_sub.setRange(10, 300)
        self._stroke_w.setRange(0, 20)
        form.addRow("主歌词字体", self._font_main)
        form.addRow("主歌词字号", self._size_main)
        form.addRow("主歌词颜色", self._color_main)
        form.addRow("译文字体", self._font_sub)
        form.addRow("译文字号", self._size_sub)
        form.addRow("译文颜色", self._color_sub)
        form.addRow("描边颜色", self._color_stroke)
        form.addRow("描边宽度", self._stroke_w)
        return w

    def _build_anim_tab(self) -> QWidget:
        w = QWidget(self)
        root = QVBoxLayout(w)
        root.setSpacing(8)
        for kind in KINDS:
            box = QGroupBox(_KIND_TITLES[kind], w)
            box.setObjectName("animationGroup")
            form = QFormLayout(box)
            combo = QComboBox(box)
            for type_key, cls in ANIM_REGISTRY[kind].items():
                combo.addItem(cls.label, type_key)
            combo.currentIndexChanged.connect(
                lambda _i, k=kind, c=combo: self._on_anim_type_changed(
                    k, c.currentData()
                )
            )
            params_form = QFormLayout()
            params_form.setContentsMargins(0, 0, 0, 0)
            params_form.setLabelAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            form.addRow("类型", combo)
            form.addRow(params_form)
            self._anim_combos[kind] = combo
            self._anim_forms[kind] = params_form
            root.addWidget(box)
        root.addStretch(1)
        return w

    def _build_color_tab(self) -> QWidget:
        w = QWidget(self)
        form = QFormLayout(w)
        form.setSpacing(6)
        form.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        form.addRow(self._auto_extract)
        form.addRow("主色（动画用）", self._color_primary)
        form.addRow("辅色（动画用）", self._color_secondary)
        form.addRow("描边色", self._color_stroke2)
        form.addRow("实际取色", self._palette_status)
        return w

    def _build_output_tab(self) -> QWidget:
        w = QWidget(self)
        form = QFormLayout(w)
        form.setSpacing(6)
        form.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self._fps.addItem("60 fps", 60)
        self._fps.addItem("30 fps", 30)
        for label, value in _ENCODER_ITEMS:
            self._encoder.addItem(label, value)
        self._vbitrate.setEditable(True)
        for preset in _BITRATE_PRESETS:
            self._vbitrate.addItem(preset)
        for preset in _AUDIO_BITRATE_PRESETS:
            self._abitrate.addItem(preset)
        form.addRow("帧率", self._fps)
        form.addRow("编码器", self._encoder)
        form.addRow("视频码率", self._vbitrate)
        form.addRow("音频码率", self._abitrate)
        form.addRow(self._show_meta)
        return w

    # ---------------------------------------------------------------- 信号

    def _connect_signals(self) -> None:
        self._font_main.currentIndexChanged.connect(self._on_style_changed)
        self._font_sub.currentIndexChanged.connect(self._on_style_changed)
        self._size_main.valueChanged.connect(self._on_style_changed)
        self._size_sub.valueChanged.connect(self._on_style_changed)
        self._stroke_w.valueChanged.connect(self._on_style_changed)
        self._color_main.colorChanged.connect(self._on_style_changed)
        self._color_sub.colorChanged.connect(self._on_style_changed)
        self._color_stroke.colorChanged.connect(self._on_style_changed)

        self._auto_extract.toggled.connect(self._on_color_changed)
        self._color_primary.colorChanged.connect(self._on_color_changed)
        self._color_secondary.colorChanged.connect(self._on_color_changed)
        self._color_stroke2.colorChanged.connect(self._on_color_changed)

        self._fps.currentIndexChanged.connect(self._on_output_changed)
        self._encoder.currentIndexChanged.connect(self._on_output_changed)
        self._vbitrate.editTextChanged.connect(self._on_output_changed)
        self._abitrate.currentIndexChanged.connect(self._on_output_changed)
        self._show_meta.toggled.connect(self._on_output_changed)

    def _on_style_changed(self, *_a: Any) -> None:
        p = self._project
        if p is None:
            return
        p.lyric_style.main_font = str(self._font_main.currentData() or "")
        p.lyric_style.sub_font = str(self._font_sub.currentData() or "")
        p.lyric_style.main_size = self._size_main.value()
        p.lyric_style.sub_size = self._size_sub.value()
        p.lyric_style.stroke_width = self._stroke_w.value()
        p.lyric_style.main_color = self._color_main.color()
        p.lyric_style.sub_color = self._color_sub.color()
        p.lyric_style.stroke_color = self._color_stroke.color()
        self.paramsChanged.emit()

    def _on_color_changed(self, *_a: Any) -> None:
        p = self._project
        if p is None:
            return
        auto_extract = self._auto_extract.isChecked()
        was_auto_extract = p.colors.auto_extract
        if not auto_extract and was_auto_extract:
            # 自动模式下按钮显示的是本次封面的有效色；切回手动时先
            # 恢复工程里保存的备用色，避免把自动结果误写成手动配置。
            self._color_primary.set_color(p.colors.primary)
            self._color_secondary.set_color(p.colors.secondary)
        p.colors.auto_extract = auto_extract
        if not (auto_extract and not was_auto_extract):
            p.colors.primary = self._color_primary.color()
            p.colors.secondary = self._color_secondary.color()
        p.colors.stroke = self._color_stroke2.color()
        self._set_color_controls_enabled(not p.colors.auto_extract)
        self.paramsChanged.emit()

    def _on_output_changed(self, *_a: Any) -> None:
        p = self._project
        if p is None:
            return
        fps = self._fps.currentData()
        if fps:
            p.output.fps = round(fps)
        enc = self._encoder.currentData()
        if enc:
            p.output.encoder = str(enc)
        p.output.video_bitrate = self._vbitrate.currentText().strip() or "12M"
        ab = self._abitrate.currentText().strip()
        if ab:
            p.output.audio_bitrate = ab
        p.output.show_metadata = self._show_meta.isChecked()
        self.paramsChanged.emit()

    def _on_anim_type_changed(self, kind: str, type_key: Any) -> None:
        p = self._project
        if p is None or not type_key:
            return
        spec = getattr(p.animations, kind)
        if spec.type == str(type_key):
            return
        spec.type = str(type_key)
        cls = ANIM_REGISTRY[kind][str(type_key)]
        spec.params = cls.defaults()  # 切换 type → 新 schema 默认值（DESIGN §4.5）
        self._rebuild_anim_params(kind)
        self.paramsChanged.emit()

    def _set_anim_param(self, kind: str, key: str, value: Any) -> None:
        p = self._project
        if p is None:
            return
        getattr(p.animations, kind).params[key] = value
        self.paramsChanged.emit()

    # ---------------------------------------------------------------- schema 控件

    def _rebuild_anim_params(self, kind: str) -> None:
        """按当前 type 的 params_schema 重建参数控件。"""
        p = self._project
        form = self._anim_forms[kind]
        while form.rowCount() > 0:
            form.removeRow(0)
        if p is None:
            return
        spec_obj = getattr(p.animations, kind)
        cls = ANIM_REGISTRY[kind].get(spec_obj.type) or next(
            iter(ANIM_REGISTRY[kind].values())
        )
        # 绑定/切换时把当前 JSON 参数收敛到 schema，避免非法值只在真正
        # 渲染时才被静默修正，导致界面显示值与保存内容不一致。
        spec_obj.params = cls.resolve_params(spec_obj.params)
        for spec in cls.params_schema():
            widget = self._build_param_widget(
                kind, spec, spec_obj.params.get(spec.key, spec.default)
            )
            form.addRow(spec.label, widget)

    def _build_param_widget(self, kind: str, spec: ParamSpec, current: Any) -> QWidget:
        lo = spec.min if spec.min is not None else 0.0
        hi = spec.max if spec.max is not None else 9999.0
        if spec.kind == "int":
            w = QSpinBox(self)
            w.setRange(round(lo), round(hi))
            w.setValue(round(current) if current is not None else round(spec.default))
            w.valueChanged.connect(
                lambda v, k=kind, key=spec.key: self._set_anim_param(k, key, v)
            )
            return w
        if spec.kind == "float":
            w = QDoubleSpinBox(self)
            w.setRange(lo, hi)
            w.setDecimals(2)
            w.setSingleStep(0.1)
            w.setValue(current if current is not None else spec.default)
            w.valueChanged.connect(
                lambda v, k=kind, key=spec.key: self._set_anim_param(k, key, v)
            )
            return w
        if spec.kind == "bool":
            w = QCheckBox(self)
            w.setChecked(bool(current))
            w.toggled.connect(
                lambda v, k=kind, key=spec.key: self._set_anim_param(k, key, v)
            )
            return w
        if spec.kind == "choice":
            w = QComboBox(self)
            for choice in spec.choices:
                w.addItem(choice, choice)
            idx = w.findData(str(current))
            w.setCurrentIndex(max(idx, 0))
            w.currentIndexChanged.connect(
                lambda _i, k=kind, key=spec.key, c=w: self._set_anim_param(
                    k, key, c.currentData()
                )
            )
            return w
        label = QLabel(self)
        label.setText(f"（不支持参数类型 {spec.kind}）")
        return label

    # ---------------------------------------------------------------- 绑定

    def _set_color_controls_enabled(self, enabled: bool) -> None:
        """自动取色时锁定主色/辅色编辑，保留配置值供切回手动模式。"""
        self._color_primary.setEnabled(enabled)
        self._color_secondary.setEnabled(enabled)
        self._color_primary.setToolTip(
            "关闭自动取色后可手动指定" if not enabled else "点击选择动画主色"
        )
        self._color_secondary.setToolTip(
            "关闭自动取色后可手动指定" if not enabled else "点击选择动画辅色"
        )

    def set_palette_preview(self, palette: Palette | None) -> None:
        """显示本次 prepare 使用的有效主色/辅色，不改写工程配置。"""
        if palette is None:
            self._palette_status.setText("当前有效取色：等待封面")
            return
        primary = rgb_to_hex(palette.primary)
        secondary = rgb_to_hex(palette.secondary)
        if self._project is not None and self._project.colors.auto_extract:
            # 色块仅作为有效值预览；set_color 不发信号，工程里仍保留
            # 手动模式的备用颜色，切换回手动时可恢复。
            with _blocked(self._color_primary, self._color_secondary):
                self._color_primary.set_color(primary)
                self._color_secondary.set_color(secondary)
        self._palette_status.setText(
            f"<span style='color:{primary}'>■</span> 主色 {primary}&nbsp;&nbsp;"
            f"<span style='color:{secondary}'>■</span> 辅色 {secondary}"
        )
        self._palette_status.setToolTip(
            f"本次渲染实际使用：主色 {primary}，辅色 {secondary}"
        )

    def bind(self, project: KProj) -> None:
        """从 project 刷新全部控件（阻断信号，不触发 prepare）。"""
        self._project = project
        style = project.lyric_style
        with _blocked(
            self._font_main,
            self._font_sub,
            self._size_main,
            self._size_sub,
            self._stroke_w,
            self._color_main,
            self._color_sub,
            self._color_stroke,
            self._auto_extract,
            self._color_primary,
            self._color_secondary,
            self._color_stroke2,
            self._fps,
            self._encoder,
            self._vbitrate,
            self._abitrate,
            self._show_meta,
        ):
            self._font_main.setCurrentIndex(
                max(0, self._font_main.findData(style.main_font))
            )
            self._font_sub.setCurrentIndex(
                max(0, self._font_sub.findData(style.sub_font))
            )
            self._size_main.setValue(style.main_size)
            self._size_sub.setValue(style.sub_size)
            self._stroke_w.setValue(style.stroke_width)
            self._color_main.set_color(style.main_color)
            self._color_sub.set_color(style.sub_color)
            self._color_stroke.set_color(style.stroke_color)

            self._auto_extract.setChecked(project.colors.auto_extract)
            self._color_primary.set_color(project.colors.primary)
            self._color_secondary.set_color(project.colors.secondary)
            self._color_stroke2.set_color(project.colors.stroke)

            self._fps.setCurrentIndex(max(0, self._fps.findData(project.output.fps)))
            self._encoder.setCurrentIndex(
                max(0, self._encoder.findData(project.output.encoder))
            )
            found = self._vbitrate.findText(project.output.video_bitrate)
            if found >= 0:
                self._vbitrate.setCurrentIndex(found)
            else:
                self._vbitrate.setEditText(project.output.video_bitrate)
            self._abitrate.setCurrentIndex(
                max(0, self._abitrate.findText(project.output.audio_bitrate))
            )
            self._show_meta.setChecked(project.output.show_metadata)

        for kind in KINDS:
            combo = self._anim_combos[kind]
            with _blocked(combo):
                combo.setCurrentIndex(
                    max(0, combo.findData(getattr(project.animations, kind).type))
                )
            self._rebuild_anim_params(kind)
        self._set_color_controls_enabled(not project.colors.auto_extract)
        self.set_palette_preview(None)
