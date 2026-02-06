# main_ui.py
# 项目核心文件，负责图形用户界面(GUI)的构建、事件处理和核心业务逻辑。

import sys
import os
import json
import traceback
import subprocess
import tempfile
import shutil
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QFileDialog, QColorDialog, QTextEdit, QProgressBar,
    QMessageBox, QGridLayout, QComboBox
)
from PySide6.QtCore import Signal, QSettings, Qt
from PySide6.QtGui import QColor, QPixmap, QIcon

from lrc_parser import parse_bilingual_lrc_with_metadata
from workers import AudioInfoWorker, VideoWorker, PreviewWorker
from ui_components import (
    create_file_group, create_style_group, create_preview_group,
    create_advanced_group, create_generation_group
)
from video_processor import VideoGenParams, get_ffmpeg_probe_path

try:
    from color_extractor import extract_and_process_colors
    COLOR_EXTRACTION_AVAILABLE = True
except ImportError:
    COLOR_EXTRACTION_AVAILABLE = False


class MainWindow(QMainWindow):
    status = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("LRC Video Generator Pro")
        self.setGeometry(100, 100, 1150, 850)

        self.settings = QSettings("SkyDream", "LRCVideoGenerator")
        self.file_paths = {"audio": "", "cover": "", "lrc": "", "background": ""}
        self.ffmpeg_path = self.settings.value("ffmpeg_path", "ffmpeg")
        self.COLOR_EXTRACTION_AVAILABLE = COLOR_EXTRACTION_AVAILABLE

        try:
            self.base_dir = Path(__file__).parent.resolve()
        except NameError:
            self.base_dir = Path.cwd().resolve()
        
        icon_path = self.base_dir / "icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.font_dir = self.base_dir / 'font'
        self.temp_dir = Path(tempfile.gettempdir()) / 'lrc2video'
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        
        self._preview_temp_file = ""
        self._current_preview_pixmap = None

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
        main_layout.setContentsMargins(15, 15, 15, 15)
        self.setCentralWidget(main_widget)

        top_grid = QGridLayout()
        top_grid.setSpacing(15)

        left_layout = QVBoxLayout()
        left_layout.addWidget(create_file_group(self))
        left_layout.addWidget(create_style_group(self))
        left_layout.addStretch()
        top_grid.addLayout(left_layout, 0, 0)

        right_layout = QVBoxLayout()
        preview_group = create_preview_group(self)
        advanced_group = create_advanced_group(self)
        
        right_layout.addWidget(preview_group)
        right_layout.addWidget(advanced_group)
        right_layout.setStretchFactor(preview_group, 1)
        top_grid.addLayout(right_layout, 0, 1)

        top_grid.setColumnStretch(0, 4)
        top_grid.setColumnStretch(1, 5)
        main_layout.addLayout(top_grid, 1)

        main_layout.addWidget(create_generation_group(self))

    def select_file(self, key: str):
        filter_map = {
            "audio": "音频文件 (*.mp3 *.wav *.flac *.m4a)",
            "cover": "图像文件 (*.jpg *.jpeg *.png *.webp)",
            "lrc": "LRC 歌词文件 (*.lrc)",
            "background": "图像文件 (*.jpg *.jpeg *.png *.webp)"
        }
        path, _ = QFileDialog.getOpenFileName(self, f"选择 {key.upper()} 文件", "", filter_map.get(key, "所有文件 (*)"))
        if not path: return

        self.file_paths[key] = path
        self.line_edits[key].setText(path)
        
        self._current_preview_pixmap = None
        self.preview_display.setText("文件已更改，请重新生成预览")
        
        if key == "audio": self.get_audio_duration(path)
        elif key == "lrc": self.parse_lrc_file(path)

    def clear_file_selection(self, key: str):
        if key in self.file_paths and key in self.line_edits:
            self.file_paths[key] = ""
            self.line_edits[key].setText("")
            self.log_message(f"已清除 {key.capitalize()} 文件选择。")
            self._current_preview_pixmap = None
            self.preview_display.setText("文件已更改，请重新生成预览")

    def get_audio_duration(self, audio_path: str):
        self.log_message("正在获取音频时长...")
        self.audio_worker = AudioInfoWorker(self.ffmpeg_path, audio_path)
        self.audio_worker.status.connect(self.log_message)
        self.audio_worker.finished.connect(self.on_audio_info_finished)
        self.audio_worker.start()

    def parse_lrc_file(self, lrc_path: str):
        try:
            with open(lrc_path, 'r', encoding='utf-8') as f:
                lrc_content = f.read()
            _, self.lrc_metadata = parse_bilingual_lrc_with_metadata(lrc_content)
            self.log_message(f"LRC元数据解析成功: {self.lrc_metadata.get('ti', '未知标题')}")
        except Exception as e:
            self.log_message(f"解析LRC元数据失败: {e}")
            self.lrc_metadata = {}

    def on_audio_info_finished(self, duration: float, error_message: str):
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
            if self.audio_duration > 30:
                self.preview_slider.setValue(int(self.audio_duration * 100 * 0.3))

    def update_preview_time_label(self, value: int):
        time_in_seconds = value / 100.0
        minutes = int(time_in_seconds // 60)
        seconds = time_in_seconds % 60
        self.preview_time_label.setText(f"{minutes:02d}:{seconds:05.2f}")

    def _gather_parameters(self) -> VideoGenParams | None:
        for key, desc in {"audio": "音频", "cover": "封面", "lrc": "歌词"}.items():
            path = self.file_paths.get(key)
            if not path or not os.path.exists(path):
                QMessageBox.warning(self, "输入错误", f"请先选择一个有效的 {desc} 文件！")
                return None

        font_primary_file = self.font_combo_primary.currentText()
        font_secondary_file = self.font_combo_secondary.currentText()
        if not font_primary_file or not font_secondary_file:
            QMessageBox.critical(self, "字体错误", f"请在 '{self.font_dir}' 文件夹中放置字体文件，并在此处选择它们。")
            return None

        background_path = self.file_paths.get("background")
        if not background_path or not os.path.exists(background_path):
            background_path = self.file_paths["cover"]

        try:
            params = VideoGenParams(
                audio_path=Path(self.file_paths["audio"]),
                cover_path=Path(self.file_paths["cover"]),
                lrc_path=Path(self.file_paths["lrc"]),
                background_path=Path(background_path),
                font_primary=self.font_dir / font_primary_file,
                font_size_primary=self.font_size_spin_primary.value(),
                font_secondary=self.font_dir / font_secondary_file,
                font_size_secondary=self.font_size_spin_secondary.value(),
                color_primary=self.settings.value("color_primary"),
                color_secondary=self.settings.value("color_secondary"),
                outline_color=self.settings.value("outline_color"),
                outline_width=self.outline_width_spin.value(),
                background_anim=self.bg_anim_combo.currentText(),
                text_anim=self.text_anim_combo.currentText(),
                cover_anim=self.cover_anim_combo.currentText(),
                ffmpeg_path=self.ffmpeg_path,
                hw_accel=self.hw_accel_combo.currentText(),
                width=self.width_spin.value(),
                height=self.height_spin.value(),
                fps=self.fps_spin.value(),
                # [新增] 收集布局比例
                layout_split=self.layout_split_spin.value()
            )
            return params
        except Exception as e:
            QMessageBox.critical(self, "参数错误", f"收集参数时发生错误: {e}")
            return None

    def generate_preview(self):
        if not self.check_ffmpeg(): return
        params = self._gather_parameters()
        if not params: return

        try:
            if not self._preview_temp_file or not Path(self._preview_temp_file).parent.exists():
                 self._preview_temp_file = self.temp_dir / f"preview_{os.urandom(8).hex()}.png"

            params.output_image_path = Path(self._preview_temp_file)
            params.preview_time = self.preview_slider.value() / 100.0

            self.log_message(f"--- 开始生成预览 ({params.width}x{params.height}) ---")
            self.set_ui_enabled(False)
            self.preview_display.setText("正在生成预览...")

            self.preview_worker = PreviewWorker(params)
            self.preview_worker.status.connect(self.log_message)
            self.preview_worker.finished.connect(self.on_preview_finished)
            self.preview_worker.start()

        except Exception as e:
            self.log_message(f"准备预览时发生错误: {traceback.format_exc()}")
            QMessageBox.critical(self, "预览失败", f"准备预览时发生错误: \n{e}")
            self.set_ui_enabled(True)

    def on_preview_finished(self, pixmap: QPixmap, error_message: str):
        self.set_ui_enabled(True)
        if error_message:
            self.log_message(f"预览生成失败: {error_message}")
            self.preview_display.setText("预览生成失败\n请查看日志")
            self._current_preview_pixmap = None
        else:
            self._current_preview_pixmap = pixmap
            self.update_preview_display()
            self.log_message("--- 预览生成成功 ---")

    def update_preview_display(self):
        if self._current_preview_pixmap and not self._current_preview_pixmap.isNull():
            self.preview_display.setPixmap(self._current_preview_pixmap.scaled(
                self.preview_display.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            ))

    def auto_extract_colors(self):
        if not COLOR_EXTRACTION_AVAILABLE:
            QMessageBox.critical(self, "依赖缺失", "需要 pip install Pillow scikit-learn")
            return

        cover_path = self.file_paths.get("cover")
        if not cover_path or not os.path.exists(cover_path):
            QMessageBox.warning(self, "操作无效", "请先选择一个有效的封面文件！")
            return
            
        self.log_message(f"正在从封面 '{Path(cover_path).name}' 提取颜色...")
        self.set_ui_enabled(False)
        try:
            primary_color, secondary_color, outline_color = extract_and_process_colors(cover_path)
            
            if primary_color and secondary_color and outline_color:
                self.settings.setValue("color_primary", primary_color)
                self.settings.setValue("color_secondary", secondary_color)
                self.settings.setValue("outline_color", outline_color)
                self._update_color_button_style("color_primary")
                self._update_color_button_style("color_secondary")
                self._update_color_button_style("outline_color")
                self.log_message(f"颜色提取成功！{primary_color}, {secondary_color}, {outline_color}")
                QMessageBox.information(self, "成功", "颜色已自动提取。")
            else:
                raise ValueError("未能找到合适的颜色对。")
        except Exception as e:
            self.log_message(f"颜色提取失败: {e}")
            QMessageBox.critical(self, "提取失败", f"错误:\n{e}")
        finally:
            self.set_ui_enabled(True)

    def save_project(self):
        default_filename = "untitled.kproj"
        if title := self.lrc_metadata.get("ti"):
            artist = self.lrc_metadata.get("ar", "")
            default_filename = f"{artist} - {title}.kproj" if artist else f"{title}.kproj"

        path, _ = QFileDialog.getSaveFileName(self, "保存工程文件", default_filename, "Karaoke Project (*.kproj)")
        if not path: return

        project_data = {
            "version": 1.3,
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
                "hw_accel": self.hw_accel_combo.currentText(),
                "width": self.width_spin.value(),
                "height": self.height_spin.value(),
                "fps": self.fps_spin.value(),
                # [新增] 保存布局比例
                "layout_split": self.layout_split_spin.value()
            }
        }
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(project_data, f, ensure_ascii=False, indent=4)
            self.log_message(f"工程已成功保存到: {path}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败: {e}")

    def load_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "加载工程文件", "", "Karaoke Project (*.kproj);;所有文件 (*)")
        if not path: return

        try:
            with open(path, 'r', encoding='utf-8') as f:
                project_data = json.load(f)

            file_paths = project_data.get("file_paths", {})
            file_paths.setdefault("background", "")
            self.file_paths = file_paths

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
            self.font_size_spin_secondary.setValue(s.get("font_size_secondary", 42))
            self.outline_width_spin.setValue(s.get("outline_width", 3))

            self.width_spin.setValue(s.get("width", 1920))
            self.height_spin.setValue(s.get("height", 1080))
            self.fps_spin.setValue(s.get("fps", 60))
            
            # [新增] 恢复布局比例
            if layout_split := s.get("layout_split"):
                self.layout_split_spin.setValue(layout_split)

            for key in ["color_primary", "color_secondary", "outline_color"]:
                if color_val := s.get(key):
                    self.settings.setValue(key, color_val)
                    self._update_color_button_style(key)

            if ffmpeg_path_val := s.get("ffmpeg_path"):
                self.ffmpeg_path = ffmpeg_path_val
                self.ffmpeg_path_edit.setText(self.ffmpeg_path)
                
            self._current_preview_pixmap = None
            self.preview_display.setText("工程已加载，请生成预览")
            self.log_message(f"工程文件加载成功: {path}")

        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载失败: {e}")

    def _set_combo_text(self, combo: QComboBox, text: str):
        if text and combo.findText(text) > -1:
            combo.setCurrentText(text)

    def start_generation(self):
        if not self.check_ffmpeg(): return
        params = self._gather_parameters()
        if not params: return

        default_filename = "output.mp4"
        if title := self.lrc_metadata.get("ti"):
            artist = self.lrc_metadata.get("ar", "")
            default_filename = f"{artist} - {title}.mp4" if artist else f"{title}.mp4"

        output_path, _ = QFileDialog.getSaveFileName(self, "保存视频文件", default_filename, "MP4 视频 (*.mp4)")
        if not output_path: return

        self.save_settings()
        params.output_path = Path(output_path)
        
        self.log_box.clear()
        self.log_message(f"准备生成视频: {params.width}x{params.height} @ {params.fps}fps")
        self.set_ui_enabled(False)
        self.progress_bar.setValue(0)

        self.video_worker = VideoWorker(params)
        self.video_worker.progress.connect(self.update_progress)
        self.video_worker.status.connect(self.log_message)
        self.video_worker.finished.connect(self.generation_finished)
        self.video_worker.start()

    def update_progress(self, percent: int, remaining_time_str: str):
        self.progress_bar.setValue(percent)
        self.remaining_time_label.setText(remaining_time_str)

    def generation_finished(self, message: str):
        self.set_ui_enabled(True)
        is_success = "成功" in message
        if is_success:
            QMessageBox.information(self, "完成", message)
            self.progress_bar.setValue(100)
        else:
            QMessageBox.critical(self, "失败", f"生成失败！\n错误: {message}")
            self.progress_bar.setValue(0)
        self.log_message(f"--- {message} ---")
        self.remaining_time_label.setText("")

    def set_ui_enabled(self, enabled: bool):
        self.generate_button.setEnabled(enabled)
        self.preview_button.setEnabled(enabled)

    def populate_fonts(self):
        self.log_message(f"正在从 '{self.font_dir}' 加载字体...")
        if not self.font_dir.is_dir():
            self.font_dir.mkdir(parents=True, exist_ok=True)
            self.log_message("已创建字体文件夹。")
            return
        
        self.font_combo_primary.clear()
        self.font_combo_secondary.clear()
        font_files = [f.name for f in self.font_dir.iterdir() if f.suffix.lower() in ('.ttf', '.otf', '.ttc')]
        if font_files:
            self.font_combo_primary.addItems(font_files)
            self.font_combo_secondary.addItems(font_files)
            self.log_message(f"成功加载 {len(font_files)} 个字体。")
        else:
            self.log_message("警告: 在 'font' 文件夹中没有找到任何字体文件。")

    def check_ffmpeg(self) -> bool:
        if not self.ffmpeg_path:
            self.ffmpeg_path = "ffmpeg"
        try:
            ffprobe_path = get_ffmpeg_probe_path(self.ffmpeg_path)
            if not ffprobe_path:
                raise FileNotFoundError("ffprobe not found")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            self.log_message(f"警告: FFmpeg 未找到。{e}")
            QMessageBox.warning(self, "依赖警告", "未找到有效的 FFmpeg。")
            return False

    def select_color(self, key: str):
        initial_color = self.settings.value(key, "#ffffff")
        color = QColorDialog.getColor(QColor(initial_color), self, "选择颜色")
        if color.isValid():
            self.settings.setValue(key, color.name())
            self._update_color_button_style(key)

    def _update_color_button_style(self, key: str):
        if not hasattr(self, 'color_buttons') or key not in self.color_buttons:
            return
        color_name = self.settings.value(key)
        if not color_name:
            return
        button = self.color_buttons[key]
        button.setText(color_name)
        q_color = QColor(color_name)
        text_color = 'white' if q_color.lightness() < 128 else 'black'
        button.setStyleSheet(f"background-color: {color_name}; color: {text_color}; border: 1px solid #888; border-radius: 4px;")

    def select_ffmpeg_path(self):
        executable_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
        path, _ = QFileDialog.getOpenFileName(self, f"选择 {executable_name}", "", f"{executable_name};;所有文件 (*)")
        if path:
            self.ffmpeg_path = path
            self.ffmpeg_path_edit.setText(path)
            self.settings.setValue("ffmpeg_path", path)
            self.log_message(f"FFmpeg 路径已更新为: {path}")
            self.check_ffmpeg()

    def log_message(self, message: str):
        self.log_box.append(message)
        self.log_box.verticalScrollBar().setValue(self.log_box.verticalScrollBar().maximum())

    def save_settings(self):
        self.settings.setValue("ffmpeg_path", self.ffmpeg_path)
        self.settings.setValue("background_anim", self.bg_anim_combo.currentText())
        self.settings.setValue("text_anim", self.text_anim_combo.currentText())
        self.settings.setValue("cover_anim", self.cover_anim_combo.currentText())
        self.settings.setValue("hw_accel", self.hw_accel_combo.currentText())
        
        self.settings.setValue("font_primary", self.font_combo_primary.currentText())
        self.settings.setValue("font_size_primary", self.font_size_spin_primary.value())
        self.settings.setValue("font_secondary", self.font_combo_secondary.currentText())
        self.settings.setValue("font_size_secondary", self.font_size_spin_secondary.value())
        self.settings.setValue("outline_width", self.outline_width_spin.value())

        self.settings.setValue("width", self.width_spin.value())
        self.settings.setValue("height", self.height_spin.value())
        self.settings.setValue("fps", self.fps_spin.value())
        # [新增] 保存偏好
        self.settings.setValue("layout_split", self.layout_split_spin.value())

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
        self.font_size_spin_secondary.setValue(int(self.settings.value("font_size_secondary", 42)))

        self.width_spin.setValue(int(self.settings.value("width", 1920)))
        self.height_spin.setValue(int(self.settings.value("height", 1080)))
        self.fps_spin.setValue(int(self.settings.value("fps", 60)))
        
        # [新增] 加载布局偏好
        if split_val := self.settings.value("layout_split"):
            self.layout_split_spin.setValue(float(split_val))

        self._update_color_button_style("color_primary")
        self._update_color_button_style("color_secondary")
        self._update_color_button_style("outline_color")
        self.log_message("已加载用户设置。")

    def closeEvent(self, event):
        self.save_settings()
        try:
            if self.temp_dir.exists():
                shutil.rmtree(self.temp_dir)
        except OSError: pass
        super().closeEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_preview_display()