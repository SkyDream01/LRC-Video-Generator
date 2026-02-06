# ui_components.py
# UI 组件工厂模块
from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QComboBox, QSpinBox, QSlider, QWidget, QProgressBar, QTextEdit,
    QSizePolicy, QGridLayout, QDoubleSpinBox
)
from PySide6.QtCore import Qt
from animations import BACKGROUND_ANIMATIONS, TEXT_ANIMATIONS, COVER_ANIMATIONS

def create_file_group(main_window):
    """创建文件与工程分组框"""
    group = QGroupBox("1. 工程与文件")
    layout = QVBoxLayout(group)
    layout.setSpacing(10)

    # 加载/保存工程按钮
    project_layout = QHBoxLayout()
    load_button = QPushButton("📂 加载工程")
    load_button.clicked.connect(main_window.load_project)
    save_button = QPushButton("💾 保存工程")
    save_button.clicked.connect(main_window.save_project)
    project_layout.addWidget(load_button)
    project_layout.addWidget(save_button)
    layout.addLayout(project_layout)
    layout.addWidget(_create_separator())

    # 文件选择器
    main_window.line_edits = {}
    file_types = {
        "audio": "🎵 音频文件",
        "cover": "🖼️ 封面图片",
        "lrc": "📝 LRC 歌词",
        "background": "🌄 背景图片 (可选)"
    }
    for key, desc in file_types.items():
        _create_file_selector(main_window, layout, key, desc)
    return group

def create_style_group(main_window):
    """创建样式与动画分组框"""
    group = QGroupBox("2. 样式与动画")
    layout = QVBoxLayout(group)
    layout.setSpacing(10)

    # 动画选择
    anim_layout = QGridLayout()
    anim_layout.setVerticalSpacing(10)
    main_window.bg_anim_combo = _create_combo_row(anim_layout, 0, "背景动画:", BACKGROUND_ANIMATIONS.keys())
    main_window.text_anim_combo = _create_combo_row(anim_layout, 1, "歌词动画:", TEXT_ANIMATIONS.keys())
    main_window.cover_anim_combo = _create_combo_row(anim_layout, 2, "封面动画:", COVER_ANIMATIONS.keys())
    layout.addLayout(anim_layout)

    layout.addWidget(_create_separator())

    # [新增] 布局比例控制
    layout_layout = QHBoxLayout()
    layout_layout.addWidget(QLabel("左右布局比例:"))
    
    # 滑块控制 (范围 20-80)
    main_window.layout_split_slider = QSlider(Qt.Horizontal)
    main_window.layout_split_slider.setRange(20, 80)
    main_window.layout_split_slider.setValue(38) # 默认 38.2%
    main_window.layout_split_slider.setToolTip("左侧封面区域所占宽度的百分比")
    
    # 数字显示
    main_window.layout_split_spin = QDoubleSpinBox()
    main_window.layout_split_spin.setRange(0.20, 0.80)
    main_window.layout_split_spin.setSingleStep(0.01)
    main_window.layout_split_spin.setValue(0.38)
    main_window.layout_split_spin.setDecimals(2)
    main_window.layout_split_spin.setSuffix(" (左侧)")
    
    # 联动逻辑
    def on_slider_change(val):
        main_window.layout_split_spin.setValue(val / 100.0)
        
    def on_spin_change(val):
        main_window.layout_split_slider.setValue(int(val * 100))

    main_window.layout_split_slider.valueChanged.connect(on_slider_change)
    main_window.layout_split_spin.valueChanged.connect(on_spin_change)

    layout_layout.addWidget(main_window.layout_split_slider)
    layout_layout.addWidget(main_window.layout_split_spin)
    layout.addLayout(layout_layout)

    layout.addWidget(_create_separator())

    # 颜色提取
    color_extract_button = QPushButton("🎨 智能提取配色 (从封面)")
    if not main_window.COLOR_EXTRACTION_AVAILABLE:
        color_extract_button.setDisabled(True)
        color_extract_button.setToolTip("需要安装 Pillow 和 scikit-learn")
    color_extract_button.clicked.connect(main_window.auto_extract_colors)
    layout.addWidget(color_extract_button)

    layout.addWidget(_create_separator())
    
    # 字体设置区域
    font_refresh_btn = QPushButton("🔄 刷新字体")
    font_refresh_btn.clicked.connect(main_window.populate_fonts)
    layout.addWidget(font_refresh_btn)

    # 主歌词设置
    layout.addWidget(QLabel("<b>主歌词样式</b>"))
    layout.addLayout(_create_font_style_row(main_window, "primary", 56, "#FFFFFF"))

    # 翻译歌词设置
    layout.addWidget(QLabel("<b>翻译歌词样式</b>"))
    layout.addLayout(_create_font_style_row(main_window, "secondary", 42, "#E0E0E0"))

    # 描边设置
    outline_layout = QHBoxLayout()
    main_window.outline_width_spin = QSpinBox()
    main_window.outline_width_spin.setRange(0, 20)
    main_window.outline_width_spin.setValue(3)
    main_window.outline_width_spin.setSuffix(" px")
    
    _create_color_selector(main_window, outline_layout, "outline_color", "描边颜色", "#000000")
    outline_layout.addSpacing(20)
    outline_layout.addWidget(QLabel("描边宽度:"))
    outline_layout.addWidget(main_window.outline_width_spin)
    layout.addLayout(outline_layout)

    return group

def create_preview_group(main_window):
    """创建实时预览分组框"""
    group = QGroupBox("3. 实时预览")
    layout = QVBoxLayout(group)
    layout.setSpacing(8)

    main_window.preview_display = QLabel("请先加载文件")
    main_window.preview_display.setAlignment(Qt.AlignCenter)
    main_window.preview_display.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    main_window.preview_display.setStyleSheet("background-color: #1E1E1E; color: #666; border-radius: 4px;")
    main_window.preview_display.setMinimumHeight(240)
    layout.addWidget(main_window.preview_display, 1)

    controls_layout = QHBoxLayout()
    
    main_window.preview_time_label = QLabel("00:00.00")
    main_window.preview_time_label.setFixedWidth(60)
    main_window.preview_time_label.setAlignment(Qt.AlignCenter)
    main_window.preview_time_label.setStyleSheet("background-color: #333; color: white; border-radius: 3px; padding: 2px;")
    
    main_window.preview_slider = QSlider(Qt.Horizontal)
    main_window.preview_slider.setRange(0, 0)
    main_window.preview_slider.valueChanged.connect(main_window.update_preview_time_label)
    
    main_window.preview_button = QPushButton("👁️ 生成预览帧")
    main_window.preview_button.clicked.connect(main_window.generate_preview)

    controls_layout.addWidget(main_window.preview_time_label)
    controls_layout.addWidget(main_window.preview_slider)
    controls_layout.addWidget(main_window.preview_button)
    layout.addLayout(controls_layout)

    return group

def create_advanced_group(main_window):
    """创建输出与高级设置分组框"""
    group = QGroupBox("4. 输出与高级设置")
    layout = QVBoxLayout(group)
    layout.setSpacing(10)

    # --- 第一行：分辨率与帧率 ---
    res_fps_layout = QHBoxLayout()
    
    res_fps_layout.addWidget(QLabel("分辨率:"))
    main_window.width_spin = QSpinBox()
    main_window.width_spin.setRange(100, 7680)
    main_window.width_spin.setValue(1920)
    main_window.width_spin.setToolTip("视频宽度")
    res_fps_layout.addWidget(main_window.width_spin)
    
    res_fps_layout.addWidget(QLabel("x"))
    
    main_window.height_spin = QSpinBox()
    main_window.height_spin.setRange(100, 4320)
    main_window.height_spin.setValue(1080)
    main_window.height_spin.setToolTip("视频高度")
    res_fps_layout.addWidget(main_window.height_spin)

    res_fps_layout.addSpacing(20)

    res_fps_layout.addWidget(QLabel("帧率:"))
    main_window.fps_spin = QSpinBox()
    main_window.fps_spin.setRange(1, 120)
    main_window.fps_spin.setValue(60)
    res_fps_layout.addWidget(main_window.fps_spin)

    res_fps_layout.addStretch()
    layout.addLayout(res_fps_layout)

    layout.addWidget(_create_separator())

    # --- 第二行：硬件加速 ---
    hw_layout = QHBoxLayout()
    hw_layout.addWidget(QLabel("硬件加速:"))
    main_window.hw_accel_combo = QComboBox()
    main_window.hw_accel_combo.addItems(["无 (CPU x264)", "NVIDIA (NVENC)", "AMD (AMF)", "Intel (QSV)"])
    hw_layout.addWidget(main_window.hw_accel_combo, 1)
    layout.addLayout(hw_layout)

    # --- 第三行：FFmpeg 路径 ---
    ffmpeg_layout = QHBoxLayout()
    ffmpeg_layout.addWidget(QLabel("FFmpeg:"))
    main_window.ffmpeg_path_edit = QLineEdit(main_window.ffmpeg_path)
    main_window.ffmpeg_path_edit.setPlaceholderText("系统默认或手动指定...")
    ffmpeg_browse = QPushButton("...")
    ffmpeg_browse.setFixedWidth(30)
    ffmpeg_browse.clicked.connect(main_window.select_ffmpeg_path)
    ffmpeg_layout.addWidget(main_window.ffmpeg_path_edit)
    ffmpeg_layout.addWidget(ffmpeg_browse)
    layout.addLayout(ffmpeg_layout)

    return group

def create_generation_group(main_window):
    """创建生成与日志分组框"""
    group = QGroupBox("5. 生成与日志")
    layout = QVBoxLayout(group)
    layout.setSpacing(8)

    btn_layout = QHBoxLayout()
    main_window.generate_button = QPushButton("🚀 开始渲染视频")
    main_window.generate_button.setMinimumHeight(45)
    main_window.generate_button.setStyleSheet("font-size: 14px; font-weight: bold;")
    main_window.generate_button.clicked.connect(main_window.start_generation)
    btn_layout.addWidget(main_window.generate_button)
    layout.addLayout(btn_layout)

    status_layout = QHBoxLayout()
    main_window.progress_bar = QProgressBar()
    main_window.progress_bar.setTextVisible(True)
    main_window.remaining_time_label = QLabel("")
    status_layout.addWidget(main_window.progress_bar)
    status_layout.addWidget(main_window.remaining_time_label)
    layout.addLayout(status_layout)

    main_window.log_box = QTextEdit()
    main_window.log_box.setReadOnly(True)
    main_window.log_box.setFixedHeight(120)
    main_window.log_box.setStyleSheet("font-family: Consolas, monospace; font-size: 11px;")
    layout.addWidget(main_window.log_box)

    return group

# --- 辅助函数 ---

def _create_separator():
    line = QWidget()
    line.setFixedHeight(1)
    line.setStyleSheet("background-color: #3A3B3C;")
    return line

def _create_combo_row(layout, row, label_text, items):
    combo = QComboBox()
    combo.addItems(items)
    layout.addWidget(QLabel(label_text), row, 0, Qt.AlignRight)
    layout.addWidget(combo, row, 1)
    return combo

def _create_file_selector(main_window, layout, key, desc):
    h_layout = QHBoxLayout()
    label = QLabel(desc)
    label.setFixedWidth(100) 
    line_edit = QLineEdit()
    line_edit.setReadOnly(True)
    line_edit.setPlaceholderText("未选择...")
    main_window.line_edits[key] = line_edit
    browse_btn = QPushButton("浏览")
    browse_btn.clicked.connect(lambda: main_window.select_file(key))
    h_layout.addWidget(label)
    h_layout.addWidget(line_edit)
    if key == 'background':
        clear_btn = QPushButton("❌")
        clear_btn.setFixedWidth(30)
        clear_btn.setToolTip("清除背景图，使用封面作为背景")
        clear_btn.clicked.connect(lambda: main_window.clear_file_selection(key))
        h_layout.addWidget(clear_btn)
    h_layout.addWidget(browse_btn)
    layout.addLayout(h_layout)

def _create_font_style_row(main_window, key, default_size, default_color):
    layout = QHBoxLayout()
    combo = QComboBox()
    combo.setMinimumWidth(150)
    setattr(main_window, f"font_combo_{key}", combo)
    spin = QSpinBox()
    spin.setRange(8, 500)
    spin.setValue(default_size)
    spin.setSuffix(" pt")
    setattr(main_window, f"font_size_spin_{key}", spin)
    layout.addWidget(combo, 2)
    layout.addWidget(QLabel("大小:"), 0)
    layout.addWidget(spin, 1)
    _create_color_selector(main_window, layout, f"color_{key}", "颜色", default_color)
    return layout

def _create_color_selector(main_window, layout, key, text, default_color):
    btn = QPushButton()
    btn.setFixedSize(60, 24)
    btn.clicked.connect(lambda: main_window.select_color(key))
    layout.addWidget(btn)
    if not hasattr(main_window, 'color_buttons'): main_window.color_buttons = {}
    main_window.color_buttons[key] = btn
    if not main_window.settings.value(key):
        main_window.settings.setValue(key, default_color)
    main_window._update_color_button_style(key)