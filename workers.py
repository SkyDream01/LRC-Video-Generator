# workers.py
import sys
import subprocess
import traceback
import time
from pathlib import Path
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QPixmap
from video_processor import create_karaoke_video, create_preview_frame
import os

class QtProglogLogger:
    def __init__(self, qt_emitter, start_time):
        self.qt_emitter = qt_emitter
        self._last_percent = -1
        self.start_time = start_time

    def status_update(self, message):
        self.qt_emitter.status.emit(message)

    def progress_update(self, percent):
        if percent > self._last_percent:
            self._last_percent = percent
            elapsed_time = time.time() - self.start_time
            if percent > 0:
                total_time = (elapsed_time / percent) * 100
                remaining_time = total_time - elapsed_time
                remaining_time_str = time.strftime('%H:%M:%S', time.gmtime(remaining_time))
                self.qt_emitter.progress.emit(percent, f"剩余时间: {remaining_time_str}")
            else:
                self.qt_emitter.progress.emit(percent, "")

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
    progress = Signal(int, str)
    status = Signal(str)
    finished = Signal(str)
    def __init__(self, params):
        super().__init__()
        self.params = params

    def run(self):
        try:
            start_time = time.time()
            logger = QtProglogLogger(self, start_time)
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
            logger = QtProglogLogger(self, time.time()) # Pass a start time, though it won't be used for progress
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