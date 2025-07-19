# main_ui.py
import sys
import os
import json
import traceback
import subprocess
import tempfile
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QFileDialog, QProgressBar,
    QTextEdit, QGroupBox, QComboBox, QSpinBox, QColorDialog,
    QMessageBox, QDoubleSpinBox, QSlider, QSizePolicy, QGridLayout
)
from PySide6.QtCore import QThread, Signal, QSettings, Qt, QSize
from PySide6.QtGui import QColor, QPixmap, QIcon

from video_processor import create_karaoke_video, create_preview_frame
from animations import BACKGROUND_ANIMATIONS, TEXT_ANIMATIONS, COVER_ANIMATIONS
from lrc_parser import parse_bilingual_lrc_with_metadata

class QtProglogLogger:
    def __init__(self, qt_emitter):
        self.qt_emitter = qt_emitter
        self._last_percent = -1
    def status_update(self, message):
        self.qt_emitter.status.emit(message)
    
    def progress_update(self, percent):
        if percent > self._last_percent:
            self.qt_emitter.progress.emit(percent)
            self._last_percent = percent


class AudioInfoWorker(QThread):
    finished = Signal(float, str)
    status = Signal(str)

    def __init__(self, ffmpeg_path, audio_path):
        super().__init__()
        self.ffmpeg_path_str = ffmpeg_path
        self.audio_path_str = audio_path

    def run(self):
        try:
            ffprobe_exe = 'ffprobe.exe' if sys.platform == 'win32' else 'ffprobe'
            ffprobe_path = ffprobe_exe
            if self.ffmpeg_path_str != 'ffmpeg':
                ffprobe_path = str(Path(self.ffmpeg_path_str).parent / ffprobe_exe)
            
            cmd = [ffprobe_path, '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', self.audio_path_str]
            result = subprocess.run(cmd, check=True, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
            duration = float(result.stdout.strip())
            self.finished.emit(duration, "")
        except Exception as e:
            error_msg = f"获取音频时长失败: {e}"
            self.status.emit(error_msg)
            self.finished.emit(0, error_msg)

class VideoWorker(QThread):
    progress = Signal(int)
    status = Signal(str)
    finished = Signal(str)
    def __init__(self, params):
        super().__init__()
        self.params = params

    def run(self):
        try:
            logger = QtProglogLogger(self)
            self.params['logger'] = logger
            create_karaoke_video(**self.params)
            self.finished.emit("成功！视频已生成。")
        except Exception as e:
            traceback.print_exc()
            self.finished.emit(f"发生错误: {e}")

class PreviewWorker(QThread):
    finished = Signal(QPixmap, str)
    status = Signal(str)

    def __init__(self, params):
        super().__init__()
        self.params = params

    def run(self):
        try:
            logger = QtProglogLogger(self)
            self.params['logger'] = logger
            output_path = self.params["output_image_path"]

            create_preview_frame(**self.params)

            if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
                raise FileNotFoundError("FFmpeg未能成功创建预览图片。")

            pixmap = QPixmap(output_path)
            if pixmap.isNull():
                 self.finished.emit(QPixmap(), "生成的预览图片无效或无法加载。")
            else:
                self.finished.emit(pixmap, "")
        except Exception as e:
            traceback.print_exc()
            self.finished.emit(QPixmap(), f"生成预览时发生错误: {e}")


class MainWindow(QMainWindow):
    status = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("高级歌词视频生成器 (v3.0 - 优化版)")
        self.setGeometry(100, 100, 950, 800)

        self.settings = QSettings("YourCompany", "AdvancedLyricVideo")
        self.file_paths = {"audio": "", "cover": "", "lrc": ""}
        self.ffmpeg_path = self.settings.value("ffmpeg_path", "ffmpeg")
        
        try:
            self.base_dir = Path(__file__).parent.resolve()
        except NameError:
            self.base_dir = Path.cwd().resolve()
        
        self.font_dir = self.base_dir / 'font'
        self.temp_dir = Path(tempfile.gettempdir()) / 'lrc2video'
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.preview_image_path = ""
        self.audio_duration = 0
        self.lrc_metadata = {}

        self.setup_ui()
        self.populate_fonts()
        self.load_settings()
        self.check_ffmpeg()
        
        self.status.connect(self.log_message)

    def setup_ui(self):
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        self.setCentralWidget(main_widget)

        top_grid_layout = QGridLayout()
        
        left_v_layout = QVBoxLayout()
        file_group = self._create_file_group()
        style_group = self._create_style_group()
        left_v_layout.addWidget(file_group)
        left_v_layout.addWidget(style_group)
        left_v_layout.addStretch()
        top_grid_layout.addLayout(left_v_layout, 0, 0)

        right_v_layout = QVBoxLayout()
        preview_group = self._create_preview_group()
        advanced_group = self._create_advanced_group()
        right_v_layout.addWidget(preview_group)
        right_v_layout.addWidget(advanced_group)
        top_grid_layout.addLayout(right_v_layout, 0, 1)

        top_grid_layout.setColumnStretch(0, 1)
        top_grid_layout.setColumnStretch(1, 1)
        main_layout.addLayout(top_grid_layout)

        gen_group = self._create_generation_group()
        main_layout.addWidget(gen_group)
    
    def _create_file_group(self):
        group = QGroupBox("1. 工程与文件")
        layout = QVBoxLayout()
        
        project_layout = QHBoxLayout()
        load_button = QPushButton("📂 加载工程")
        load_button.clicked.connect(self.load_project)
        save_button = QPushButton("💾 保存工程")
        save_button.clicked.connect(self.save_project)
        project_layout.addWidget(load_button)
        project_layout.addWidget(save_button)
        layout.addLayout(project_layout)
        layout.addWidget(self._create_separator())
        
        self.line_edits = {}
        file_types = {"audio": "音频", "cover": "封面", "lrc": "歌词"}
        for key, desc in file_types.items():
            self.line_edits[key] = self._create_file_selector(layout, key, desc)
        group.setLayout(layout)
        return group

    def _create_style_group(self):
        group = QGroupBox("2. 样式与动画")
        layout = QVBoxLayout()
        
        anim_layout = QGridLayout()
        self.bg_anim_combo = self._create_combo_row(anim_layout, 0, "背景:", BACKGROUND_ANIMATIONS.keys())
        self.text_anim_combo = self._create_combo_row(anim_layout, 1, "歌词:", TEXT_ANIMATIONS.keys())
        self.cover_anim_combo = self._create_combo_row(anim_layout, 2, "封面:", COVER_ANIMATIONS.keys())
        layout.addLayout(anim_layout)
        layout.addWidget(self._create_separator())

        layout.addWidget(QLabel("<b>主歌词</b>"))
        layout.addLayout(self._create_font_style_row("primary", 56, "#FFFFFF"))
        layout.addWidget(QLabel("<b>次要歌词</b>"))
        layout.addLayout(self._create_font_style_row("secondary", 48, "#DDDDDD"))

        shared_layout = QHBoxLayout()
        self.outline_width_spin = QSpinBox()
        self.outline_width_spin.setRange(0, 20)
        self._create_color_selector(shared_layout, "outline_color", "描边颜色", "#000000")
        shared_layout.addWidget(QLabel("描边宽度:"))
        shared_layout.addWidget(self.outline_width_spin)
        shared_layout.addStretch()
        layout.addLayout(shared_layout)
        
        group.setLayout(layout)
        return group
    
    def _create_preview_group(self):
        group = QGroupBox("3. 实时预览")
        layout = QVBoxLayout()
        
        controls_layout = QHBoxLayout()
        controls_layout.addWidget(QLabel("时间点:"))
        self.preview_slider = QSlider(Qt.Horizontal)
        self.preview_slider.valueChanged.connect(self.update_preview_time_label)
        controls_layout.addWidget(self.preview_slider)
        
        self.preview_time_label = QLabel("0.00s")
        self.preview_time_label.setFixedWidth(50)
        controls_layout.addWidget(self.preview_time_label)
        
        self.preview_button = QPushButton("生成预览")
        self.preview_button.clicked.connect(self.generate_preview)
        controls_layout.addWidget(self.preview_button)
        
        self.preview_display = QLabel("加载音频文件后可进行预览")
        self.preview_display.setAlignment(Qt.AlignCenter)
        self.preview_display.setMinimumHeight(250)
        self.preview_display.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.preview_display.setStyleSheet("background-color: #333; color: #888; border: 1px solid #555;")
        
        layout.addLayout(controls_layout)
        layout.addWidget(self.preview_display)
        group.setLayout(layout)
        return group

    def _create_advanced_group(self):
        group = QGroupBox("4. 高级设置")
        layout = QVBoxLayout()
        
        ffmpeg_layout = QHBoxLayout()
        ffmpeg_layout.addWidget(QLabel("FFmpeg 路径:"))
        self.ffmpeg_path_edit = QLineEdit(self.ffmpeg_path)
        self.ffmpeg_path_edit.setReadOnly(True)
        ffmpeg_browse_button = QPushButton("..."); ffmpeg_browse_button.setFixedWidth(40)
        ffmpeg_browse_button.clicked.connect(self.select_ffmpeg_path)
        ffmpeg_layout.addWidget(self.ffmpeg_path_edit)
        ffmpeg_layout.addWidget(ffmpeg_browse_button)
        layout.addLayout(ffmpeg_layout)
        
        self.hw_accel_combo = self._create_combo_row(layout, 0, "硬件加速:", ["无 (软件编码 x264)", "NVIDIA (h264_nvenc)", "AMD (h264_amf)", "Intel (h264_qsv)"], is_grid=False)
        
        group.setLayout(layout)
        return group

    def _create_generation_group(self):
        group = QGroupBox("5. 生成与日志")
        layout = QVBoxLayout()
        
        controls_layout = QHBoxLayout()
        self.generate_button = QPushButton("🚀 开始生成视频")
        self.generate_button.setFixedHeight(40)
        self.generate_button.clicked.connect(self.start_generation)
        self.progress_bar = QProgressBar()
        controls_layout.addWidget(self.generate_button, 2)
        controls_layout.addWidget(self.progress_bar, 3)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setLineWrapMode(QTextEdit.NoWrap)
        self.log_box.setPlaceholderText("这里会显示操作日志和FFmpeg的输出...")
        self.log_box.setFixedHeight(150)
        
        layout.addLayout(controls_layout)
        layout.addWidget(QLabel("日志:"))
        layout.addWidget(self.log_box)
        group.setLayout(layout)
        return group
    
    def select_file(self, key):
        filter_map = {"audio": "音频文件 (*.mp3 *.wav *.flac *.m4a)", "cover": "图像文件 (*.jpg *.jpeg *.png *.webp)", "lrc": "LRC 歌词文件 (*.lrc)"}
        path, _ = QFileDialog.getOpenFileName(self, f"选择 {key.upper()} 文件", "", filter_map.get(key, "所有文件 (*)"))
        if not path: return

        self.file_paths[key] = path
        self.line_edits[key].setText(path)
        
        if key == "audio":
            self.get_audio_duration(path)
        elif key == "lrc":
            self.parse_lrc_file(path)

    def get_audio_duration(self, audio_path):
        self.log_message("正在获取音频时长...")
        self.audio_worker = AudioInfoWorker(self.ffmpeg_path, audio_path)
        self.audio_worker.status.connect(self.log_message)
        self.audio_worker.finished.connect(self.on_audio_info_finished)
        self.audio_worker.start()

    def parse_lrc_file(self, lrc_path):
        try:
            with open(lrc_path, 'r', encoding='utf-8') as f:
                lrc_content = f.read()
            _, self.lrc_metadata = parse_bilingual_lrc_with_metadata(lrc_content)
            self.log_message(f"LRC元数据解析成功: {self.lrc_metadata}")
        except Exception as e:
            self.log_message(f"解析LRC元数据失败: {e}")
            self.lrc_metadata = {}

    def on_audio_info_finished(self, duration, error_message):
        if error_message:
            self.log_message(error_message)
            self.audio_duration = 0
            self.preview_slider.setRange(0, 0)
            self.preview_display.setText("加载音频文件失败，无法预览")
        else:
            self.audio_duration = duration
            self.log_message(f"音频文件加载成功，时长: {self.audio_duration:.2f} 秒。")
            self.preview_slider.setRange(0, int(self.audio_duration * 100))
            self.preview_display.setText("可以拖动滑块并点击“生成预览”")

    def update_preview_time_label(self, value):
        time_in_seconds = value / 100.0
        self.preview_time_label.setText(f"{time_in_seconds:.2f}s")
    
    def _gather_parameters(self):
        """收集所有用于视频/预览生成的参数。"""
        # 1. 检查文件路径
        for key, desc in {"audio": "音频", "cover": "封面", "lrc": "歌词"}.items():
            path = self.file_paths.get(key)
            if not path or not os.path.exists(path):
                QMessageBox.warning(self, "输入错误", f"请先选择一个有效的 {desc} 文件！")
                return None
        
        # 2. 检查字体文件
        font_primary_file = self.font_combo_primary.currentText()
        font_secondary_file = self.font_combo_secondary.currentText()
        if not font_primary_file or not font_secondary_file:
            QMessageBox.critical(self, "字体错误", f"请在 '{self.font_dir}' 文件夹中放置字体文件，并在此处选择它们。")
            return None

        # 3. 收集所有参数
        return {
            "audio_path": self.file_paths["audio"], 
            "cover_path": self.file_paths["cover"], 
            "lrc_path": self.file_paths["lrc"],
            "font_primary": str(self.font_dir / font_primary_file), 
            "font_size_primary": self.font_size_spin_primary.value(),
            "font_secondary": str(self.font_dir / font_secondary_file), 
            "font_size_secondary": self.font_size_spin_secondary.value(),
            "color_primary": self.settings.value("color_primary"), 
            "color_secondary": self.settings.value("color_secondary"),
            "outline_color": self.settings.value("outline_color"), 
            "outline_width": self.outline_width_spin.value(),
            "background_anim": self.bg_anim_combo.currentText(),
            "text_anim": self.text_anim_combo.currentText(),
            "cover_anim": self.cover_anim_combo.currentText(),
            "ffmpeg_path": self.ffmpeg_path,
        }

    def generate_preview(self):
        if not self.check_ffmpeg(): return
        
        params = self._gather_parameters()
        if not params: return

        try:
            # 使用更稳健的临时文件路径
            self.preview_image_path = self.temp_dir / f"preview_{os.urandom(8).hex()}.png"
            
            params["output_image_path"] = str(self.preview_image_path)
            params["preview_time"] = self.preview_slider.value() / 100.0
            
            self.log_message("--- 开始生成预览 ---")
            self.set_ui_enabled(False)
            self.preview_display.setText("正在生成...")
            
            self.preview_worker = PreviewWorker(params)
            self.preview_worker.status.connect(self.log_message)
            self.preview_worker.finished.connect(self.on_preview_finished)
            self.preview_worker.start()

        except Exception as e:
            self.log_message(f"准备预览时发生错误: {traceback.format_exc()}")
            QMessageBox.critical(self, "预览失败", f"准备预览时发生错误: \n{e}")
            self.set_ui_enabled(True)
            
    def on_preview_finished(self, pixmap, error_message):
        self.set_ui_enabled(True)

        if error_message:
            self.log_message(f"预览生成失败: {error_message}")
            QMessageBox.critical(self, "预览失败", f"生成预览时发生错误:\n{error_message}")
            self.preview_display.setText("预览生成失败")
        else:
            self.preview_display.setPixmap(pixmap.scaled(
                self.preview_display.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            ))
            self.log_message("--- 预览生成成功 ---")

        if self.preview_image_path and os.path.exists(self.preview_image_path):
            try:
                os.remove(self.preview_image_path)
            except OSError:
                pass


    def save_project(self):
        default_filename = "untitled.kproj"
        if title := self.lrc_metadata.get("ti"):
            if artist := self.lrc_metadata.get("ar"):
                default_filename = f"{artist} - {title}.kproj"
            else:
                default_filename = f"{title}.kproj"

        path, _ = QFileDialog.getSaveFileName(self, "保存工程文件", default_filename, "Karaoke Project (*.kproj)")
        if not path:
            self.log_message("取消保存工程。")
            return

        project_data = {
            "version": 3.0,
            "file_paths": self.file_paths,
            "settings": {
                "font_primary": self.font_combo_primary.currentText(),
                "font_secondary": self.font_combo_secondary.currentText(),
                "font_size_primary": self.font_size_spin_primary.value(),
                "font_size_secondary": self.font_size_spin_secondary.value(),
                "color_primary": self.settings.value("color_primary"),
                "color_secondary": self.settings.value("color_secondary"),
                "outline_color": self.settings.value("outline_color"),
                "outline_width": self.outline_width_spin.value(),
                "ffmpeg_path": self.ffmpeg_path,
                "background_anim": self.bg_anim_combo.currentText(),
                "text_anim": self.text_anim_combo.currentText(),
                "cover_anim": self.cover_anim_combo.currentText(),
                "hw_accel": self.hw_accel_combo.currentText()
            }
        }
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(project_data, f, ensure_ascii=False, indent=4)
            self.log_message(f"工程已成功保存到: {path}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存工程文件失败: {e}")

    def load_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "加载工程文件", "", "Karaoke Project (*.kproj);;所有文件 (*)")
        if not path:
            self.log_message("取消加载工程。")
            return

        try:
            with open(path, 'r', encoding='utf-8') as f:
                project_data = json.load(f)

            self.file_paths = project_data.get("file_paths", {})
            for key, line_edit in self.line_edits.items():
                line_edit.setText(self.file_paths.get(key, ""))
            
            if audio_file := self.file_paths.get("audio"): self.get_audio_duration(audio_file)
            if lrc_file := self.file_paths.get("lrc"): self.parse_lrc_file(lrc_file)

            s = project_data.get("settings", {})
            
            self._set_combo_text(self.bg_anim_combo, s.get("background_anim"))
            self._set_combo_text(self.text_anim_combo, s.get("text_anim"))
            self._set_combo_text(self.cover_anim_combo, s.get("cover_anim"))
            self._set_combo_text(self.hw_accel_combo, s.get("hw_accel"))
            self._set_combo_text(self.font_combo_primary, s.get("font_primary"))
            self._set_combo_text(self.font_combo_secondary, s.get("font_secondary"))

            self.font_size_spin_primary.setValue(s.get("font_size_primary", 56))
            self.font_size_spin_secondary.setValue(s.get("font_size_secondary", 48))
            self.outline_width_spin.setValue(s.get("outline_width", 3))
            
            for key in ["color_primary", "color_secondary", "outline_color"]:
                if color_val := s.get(key):
                    self.settings.setValue(key, color_val)
                    self._update_color_button_style(key)

            if ffmpeg_path_val := s.get("ffmpeg_path"):
                self.ffmpeg_path = ffmpeg_path_val
                self.ffmpeg_path_edit.setText(self.ffmpeg_path)

            self.log_message(f"工程文件加载成功: {path}")
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载工程文件失败: {e}\n文件可能已损坏或格式不兼容。")

    def _set_combo_text(self, combo, text):
        if text and combo.findText(text) > -1:
            combo.setCurrentText(text)
            
    def _create_separator(self):
        line = QWidget()
        line.setFixedHeight(1)
        line.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        line.setStyleSheet("background-color: #555;")
        return line

    def _create_font_style_row(self, key, default_size, default_color):
        layout = QHBoxLayout()
        combo = QComboBox()
        setattr(self, f"font_combo_{key}", combo)
        spin = QSpinBox()
        spin.setRange(10, 300)
        spin.setValue(default_size)
        setattr(self, f"font_size_spin_{key}", spin)

        layout.addWidget(QLabel("字体:"))
        layout.addWidget(combo, 1)
        layout.addWidget(QLabel("字号:"))
        layout.addWidget(spin)
        self._create_color_selector(layout, f"color_{key}", "颜色", default_color)
        return layout
    
    def _create_combo_row(self, layout, row, label_text, items, is_grid=True):
        combo = QComboBox()
        combo.addItems(items)
        if is_grid:
            layout.addWidget(QLabel(label_text), row, 0)
            layout.addWidget(combo, row, 1)
        else: # QHBoxLayout
            h_layout = QHBoxLayout()
            h_layout.addWidget(QLabel(label_text))
            h_layout.addWidget(combo, 1)
            layout.addLayout(h_layout)
        return combo

    def _create_file_selector(self, layout, key, desc):
        h_layout = QHBoxLayout()
        label = QLabel(f"{desc}:"); label.setFixedWidth(60)
        line_edit = QLineEdit(); line_edit.setReadOnly(True)
        button = QPushButton("浏览..."); button.clicked.connect(lambda: self.select_file(key))
        h_layout.addWidget(label); h_layout.addWidget(line_edit); h_layout.addWidget(button)
        layout.addLayout(h_layout)
        return line_edit

    def _create_color_selector(self, layout, key, text, default_color):
        layout.addWidget(QLabel(text))
        button = QPushButton()
        button.setFixedSize(80, 25)
        button.clicked.connect(lambda: self.select_color(key))
        layout.addWidget(button)
        
        if not hasattr(self, 'color_buttons'): self.color_buttons = {}
        self.color_buttons[key] = button
        if not self.settings.value(key): self.settings.setValue(key, default_color)
        self._update_color_button_style(key)

    def start_generation(self):
        if not self.check_ffmpeg(): return
        
        params = self._gather_parameters()
        if not params: return

        default_filename = "lyric_video.mp4"
        if title := self.lrc_metadata.get("ti"):
            if artist := self.lrc_metadata.get("ar"):
                default_filename = f"{artist} - {title}.mp4"
            else:
                default_filename = f"{title}.mp4"

        output_path, _ = QFileDialog.getSaveFileName(self, "保存视频文件", default_filename, "MP4 视频 (*.mp4)")
        if not output_path: return

        self.save_settings()
        
        params["output_path"] = output_path
        params["hw_accel"] = self.hw_accel_combo.currentText()
        
        self.log_box.clear()
        self.log_message("参数验证通过，准备开始生成...")
        self.set_ui_enabled(False)
        self.progress_bar.setValue(0)

        self.video_worker = VideoWorker(params)
        self.video_worker.progress.connect(self.progress_bar.setValue)
        self.video_worker.status.connect(self.log_message)
        self.video_worker.finished.connect(self.generation_finished)
        self.video_worker.start()

    def generation_finished(self, message):
        self.set_ui_enabled(True)
        is_success = "成功" in message
        
        if is_success:
            QMessageBox.information(self, "完成", message)
            self.progress_bar.setValue(100)
        else:
            QMessageBox.critical(self, "失败", f"生成失败！\n错误: {message}\n\n请检查日志获取详细信息。")
            self.progress_bar.setValue(0)
        self.log_message(f"--- {message} ---")
    
    def set_ui_enabled(self, enabled: bool):
        self.generate_button.setEnabled(enabled)
        self.preview_button.setEnabled(enabled)

    def populate_fonts(self):
        self.log_message(f"正在从 '{self.font_dir}' 加载字体...")
        if not self.font_dir.is_dir():
            self.font_dir.mkdir(parents=True, exist_ok=True)
            self.log_message("已创建字体文件夹。请将您的 .ttf 或 .otf 字体文件放入其中。")
            return
        
        font_files = [f.name for f in self.font_dir.iterdir() if f.suffix.lower() in ('.ttf', '.otf', '.ttc')]
        if font_files:
            self.font_combo_primary.addItems(font_files)
            self.font_combo_secondary.addItems(font_files)
            self.log_message(f"成功加载 {len(font_files)} 个字体。")
        else:
            self.log_message("警告: 在 'font' 文件夹中没有找到任何字体文件。")

    def check_ffmpeg(self):
        self.log_message(f"当前 FFmpeg 路径: {self.ffmpeg_path}")
        try:
            from video_processor import get_ffmpeg_probe_path
            ffprobe_path = get_ffmpeg_probe_path(self.ffmpeg_path)
            subprocess.run([ffprobe_path, '-version'], check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
            self.log_message("FFmpeg 环境检测成功。")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.log_message("警告: FFmpeg 未找到或路径无效。请在“高级设置”中指定正确的 ffmpeg 可执行文件路径。")
            QMessageBox.warning(self, "依赖警告", "未找到有效的 FFmpeg。请在“高级设置”中指定其路径。")
            return False

    def select_color(self, key):
        initial_color = self.settings.value(key, "#ffffff")
        color = QColorDialog.getColor(QColor(initial_color), self, "选择颜色")
        if color.isValid():
            self.settings.setValue(key, color.name())
            self._update_color_button_style(key)

    def _update_color_button_style(self, key):
        if not hasattr(self, 'color_buttons') or key not in self.color_buttons: return
        color_name = self.settings.value(key)
        button = self.color_buttons[key]
        button.setText(color_name)
        q_color = QColor(color_name)
        text_color = 'white' if q_color.lightness() < 128 else 'black'
        button.setStyleSheet(f"background-color: {color_name}; color: {text_color};")

    def select_ffmpeg_path(self):
        executable_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
        path, _ = QFileDialog.getOpenFileName(self, f"选择 {executable_name}", "", f"{executable_name};;所有文件 (*)")
        if path:
            self.ffmpeg_path = path
            self.ffmpeg_path_edit.setText(path)
            self.settings.setValue("ffmpeg_path", path)
            self.log_message(f"FFmpeg 路径已更新为: {path}")
            self.check_ffmpeg()

    def log_message(self, message): 
        self.log_box.append(message)
        self.log_box.verticalScrollBar().setValue(self.log_box.verticalScrollBar().maximum())

    def save_settings(self):
        self.settings.setValue("ffmpeg_path", self.ffmpeg_path)
        self.settings.setValue("background_anim", self.bg_anim_combo.currentText())
        self.settings.setValue("text_anim", self.text_anim_combo.currentText())
        self.settings.setValue("cover_anim", self.cover_anim_combo.currentText())
        self.settings.setValue("hw_accel", self.hw_accel_combo.currentText())
        if hasattr(self, 'color_buttons'):
            for key in self.color_buttons.keys():
                self.settings.setValue(key, self.settings.value(key))
        self.log_message("临时设置已保存。")

    def load_settings(self):
        self.ffmpeg_path = self.settings.value("ffmpeg_path", "ffmpeg")
        self.ffmpeg_path_edit.setText(self.ffmpeg_path)
        
        self._set_combo_text(self.bg_anim_combo, self.settings.value("background_anim"))
        self._set_combo_text(self.text_anim_combo, self.settings.value("text_anim"))
        self._set_combo_text(self.cover_anim_combo, self.settings.value("cover_anim"))
        self._set_combo_text(self.hw_accel_combo, self.settings.value("hw_accel"))
        
        self.outline_width_spin.setValue(int(self.settings.value("outline_width", 3)))
        self._set_combo_text(self.font_combo_primary, self.settings.value("font_primary"))
        self.font_size_spin_primary.setValue(int(self.settings.value("font_size_primary", 56)))
        self._set_combo_text(self.font_combo_secondary, self.settings.value("font_secondary"))
        self.font_size_spin_secondary.setValue(int(self.settings.value("font_size_secondary", 48)))

        self._update_color_button_style("color_primary")
        self._update_color_button_style("color_secondary")
        self._update_color_button_style("outline_color")
        self.log_message("已加载基础设置。")

    def closeEvent(self, event):
        self.save_settings()
        # 清理整个临时目录
        try:
            import shutil
            shutil.rmtree(self.temp_dir)
            self.log_message(f"已清理临时目录: {self.temp_dir}")
        except OSError as e:
            self.log_message(f"清理临时目录失败: {e}")
        super().closeEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 如果有预览图，则在窗口大小改变时重新缩放
        # if self.preview_display.pixmap() and not self.preview_display.pixmap().isNull():
        #     self.preview_display.setPixmap(self.preview_display.pixmap().scaled(
        #         self.preview_display.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        #     ))

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())