# ui_components.py
from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QComboBox, QSpinBox, QSlider, QWidget, QStyle, QProgressBar, QTextEdit,
    QGridLayout, QSizePolicy
)
from PySide6.QtCore import Qt
from animations import BACKGROUND_ANIMATIONS, TEXT_ANIMATIONS, COVER_ANIMATIONS

def create_file_group(main_window):
    """创建文件与工程分组"""
    group = QGroupBox("1. 工程与文件")
    layout = QVBoxLayout(group)
    layout.setSpacing(8)

    project_layout = QHBoxLayout()
    load_button = QPushButton(" 加载工程")
    load_button.setIcon(main_window.style().standardIcon(QStyle.SP_DialogOpenButton))
    load_button.clicked.connect(main_window.load_project)
    save_button = QPushButton(" 保存工程")
    save_button.setIcon(main_window.style().standardIcon(QStyle.SP_DialogSaveButton))
    save_button.clicked.connect(main_window.save_project)
    project_layout.addWidget(load_button)
    project_layout.addWidget(save_button)
    layout.addLayout(project_layout)
    layout.addWidget(_create_separator())

    main_window.line_edits = {}
    file_types = {
        "audio": "音频",
        "cover": "封面",
        "lrc": "歌词",
        "background": "背景 (可选)"
    }
    for key, desc in file_types.items():
        main_window.line_edits[key] = _create_file_selector(main_window, layout, key, desc)
    return group

def create_style_group(main_window):
    """创建样式与动画分组"""
    group = QGroupBox("2. 样式与动画")
    layout = QVBoxLayout(group)
    layout.setSpacing(8)

    anim_layout = QGridLayout()
    anim_layout.setSpacing(8)
    main_window.bg_anim_combo = _create_combo_row(anim_layout, 0, "背景:", BACKGROUND_ANIMATIONS.keys())
    main_window.text_anim_combo = _create_combo_row(anim_layout, 1, "歌词:", TEXT_ANIMATIONS.keys())
    main_window.cover_anim_combo = _create_combo_row(anim_layout, 2, "封面:", COVER_ANIMATIONS.keys())
    layout.addLayout(anim_layout)

    color_extract_button = QPushButton("🎨 从封面提取颜色")
    if not main_window.COLOR_EXTRACTION_AVAILABLE:
        color_extract_button.setDisabled(True)
        color_extract_button.setToolTip("请先安装 'Pillow' 和 'scikit-learn' 库以启用此功能。\npip install Pillow scikit-learn")
    color_extract_button.clicked.connect(main_window.auto_extract_colors)
    layout.addWidget(color_extract_button)

    layout.addWidget(_create_separator())

    font_refresh_button = QPushButton("刷新字体列表") # [MODIFIED]
    font_refresh_button.clicked.connect(main_window.populate_fonts) # [MODIFIED]
    layout.addWidget(font_refresh_button) # [MODIFIED]

    layout.addWidget(QLabel("<b>主歌词</b>"))
    layout.addLayout(_create_font_style_row(main_window, "primary", 48, "#FFFFFF"))
    layout.addWidget(QLabel("<b>次要歌词</b>"))
    layout.addLayout(_create_font_style_row(main_window, "secondary", 42, "#DDDDDD"))

    shared_layout = QHBoxLayout()
    main_window.outline_width_spin = QSpinBox()
    main_window.outline_width_spin.setRange(0, 20)
    _create_color_selector(main_window, shared_layout, "outline_color", "描边颜色", "#000000")
    shared_layout.addWidget(QLabel("描边宽度:"))
    shared_layout.addWidget(main_window.outline_width_spin)
    shared_layout.addStretch()
    layout.addLayout(shared_layout)

    return group

def create_preview_group(main_window):
    """创建实时预览分组"""
    group = QGroupBox("3. 实时预览")
    layout = QVBoxLayout(group)
    layout.setSpacing(8)

    controls_layout = QHBoxLayout()
    controls_layout.addWidget(QLabel("时间点:"))
    main_window.preview_slider = QSlider(Qt.Horizontal)
    main_window.preview_slider.valueChanged.connect(main_window.update_preview_time_label)
    controls_layout.addWidget(main_window.preview_slider)

    main_window.preview_time_label = QLabel("0.00s")
    main_window.preview_time_label.setFixedWidth(50)
    controls_layout.addWidget(main_window.preview_time_label)

    main_window.preview_button = QPushButton(" 生成预览")
    main_window.preview_button.setIcon(main_window.style().standardIcon(QStyle.SP_MediaPlay))
    main_window.preview_button.clicked.connect(main_window.generate_preview)
    controls_layout.addWidget(main_window.preview_button)

    preview_container = QWidget()
    preview_container_layout = QVBoxLayout(preview_container)
    preview_container_layout.setContentsMargins(0, 0, 0, 0)

    main_window.preview_display = QLabel("加载音频文件后可进行预览")
    main_window.preview_display.setAlignment(Qt.AlignCenter)
    main_window.preview_display.setMinimumHeight(250)
    main_window.preview_display.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    main_window.preview_display.setStyleSheet("background-color: #252627; color: #888; border: 1px dashed #555; border-radius: 5px;")

    preview_container_layout.addWidget(main_window.preview_display)

    layout.addLayout(controls_layout)
    layout.addWidget(preview_container, 1)
    return group

def create_advanced_group(main_window):
    """创建高级设置分组"""
    group = QGroupBox("4. 高级设置")
    layout = QVBoxLayout(group)

    ffmpeg_layout = QHBoxLayout()
    ffmpeg_layout.addWidget(QLabel("FFmpeg 路径:"))
    main_window.ffmpeg_path_edit = QLineEdit(main_window.ffmpeg_path)
    main_window.ffmpeg_path_edit.setReadOnly(True)
    ffmpeg_browse_button = QPushButton("..."); ffmpeg_browse_button.setFixedWidth(40)
    ffmpeg_browse_button.clicked.connect(main_window.select_ffmpeg_path)
    ffmpeg_layout.addWidget(main_window.ffmpeg_path_edit)
    ffmpeg_layout.addWidget(ffmpeg_browse_button)
    layout.addLayout(ffmpeg_layout)

    main_window.hw_accel_combo = _create_combo_row(layout, 0, "硬件加速:", ["无 (软件编码 x264)", "NVIDIA (h264_nvenc)", "AMD (h264_amf)", "Intel (h264_qsv)"], is_grid=False)
    return group

def create_generation_group(main_window):
    """创建生成与日志分组"""
    group = QGroupBox("5. 生成与日志")
    layout = QVBoxLayout(group)
    layout.setSpacing(8)

    controls_layout = QHBoxLayout()
    main_window.generate_button = QPushButton("🚀 开始生成视频")
    main_window.generate_button.setFixedHeight(40)
    main_window.generate_button.clicked.connect(main_window.start_generation)
    main_window.progress_bar = QProgressBar()
    main_window.progress_bar.setFixedHeight(40)
    main_window.remaining_time_label = QLabel("") # [MODIFIED]
    main_window.remaining_time_label.setFixedWidth(120) # [MODIFIED]

    controls_layout.addWidget(main_window.generate_button, 2)
    controls_layout.addWidget(main_window.progress_bar, 3)
    controls_layout.addWidget(main_window.remaining_time_label) # [MODIFIED]


    main_window.log_box = QTextEdit()
    main_window.log_box.setReadOnly(True)
    main_window.log_box.setLineWrapMode(QTextEdit.NoWrap)
    main_window.log_box.setPlaceholderText("这里会显示操作日志和FFmpeg的输出...")
    main_window.log_box.setFixedHeight(150)

    layout.addLayout(controls_layout)
    layout.addWidget(QLabel("<b>日志输出:</b>"))
    layout.addWidget(main_window.log_box)
    return group

def _create_separator():
    line = QWidget()
    line.setFixedHeight(1)
    line.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    line.setStyleSheet("background-color: #4A4B4C;")
    return line

def _create_combo_row(layout, row, label_text, items, is_grid=True):
    combo = QComboBox()
    combo.addItems(items)
    if is_grid:
        layout.addWidget(QLabel(label_text), row, 0, Qt.AlignRight)
        layout.addWidget(combo, row, 1)
    else: # QHBoxLayout
        h_layout = QHBoxLayout()
        h_layout.addWidget(QLabel(label_text))
        h_layout.addWidget(combo, 1)
        layout.addLayout(h_layout)
    return combo

def _create_file_selector(main_window, layout, key, desc):
    h_layout = QHBoxLayout()
    label_text = f"{desc}:"
    label = QLabel(label_text); label.setFixedWidth(80 if "(可选)" in label_text else 60)
    line_edit = QLineEdit(); line_edit.setReadOnly(True)
    browse_button = QPushButton("浏览..."); browse_button.clicked.connect(lambda: main_window.select_file(key))

    h_layout.addWidget(label)
    h_layout.addWidget(line_edit)

    if key == 'background':
        clear_button = QPushButton("清除"); clear_button.setFixedWidth(60)
        clear_button.clicked.connect(lambda: main_window.clear_file_selection(key))
        h_layout.addWidget(clear_button)

    h_layout.addWidget(browse_button)
    layout.addLayout(h_layout)
    return line_edit

def _create_font_style_row(main_window, key, default_size, default_color):
    layout = QHBoxLayout()
    combo = QComboBox()
    setattr(main_window, f"font_combo_{key}", combo)
    spin = QSpinBox()
    spin.setRange(10, 300)
    spin.setValue(default_size)
    setattr(main_window, f"font_size_spin_{key}", spin)

    layout.addWidget(QLabel("字体:"))
    layout.addWidget(combo, 1)
    layout.addWidget(QLabel("字号:"))
    layout.addWidget(spin)
    _create_color_selector(main_window, layout, f"color_{key}", "颜色", default_color)
    return layout

def _create_color_selector(main_window, layout, key, text, default_color):
    layout.addWidget(QLabel(text))
    button = QPushButton()
    button.setFixedSize(80, 25)
    button.clicked.connect(lambda: main_window.select_color(key))
    layout.addWidget(button)

    if not hasattr(main_window, 'color_buttons'): main_window.color_buttons = {}
    main_window.color_buttons[key] = button
    if not main_window.settings.value(key): main_window.settings.setValue(key, default_color)
    main_window._update_color_button_style(key)