# workers.py
# 包含所有 QThread 工作线程的模块，用于在后台执行耗时任务，避免UI冻结。

import sys
import subprocess
import traceback
import time
from pathlib import Path
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QPixmap
from video_processor import create_karaoke_video, create_preview_frame, VideoGenParams
import os

class QtProglogLogger:
    """
    一个简单的日志记录器，将消息和进度通过Qt信号发送出去，
    用于连接后台任务和UI界面。
    """
    def __init__(self, qt_emitter, start_time):
        self.qt_emitter = qt_emitter
        self._last_percent = -1
        self.start_time = start_time

    def status_update(self, message: str):
        """发送状态更新消息。"""
        self.qt_emitter.status.emit(message)

    def progress_update(self, percent: int):
        """计算并发送进度更新，包括预估的剩余时间。"""
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
    """
    在后台线程中获取音频文件时长的 Worker。
    """
    finished = Signal(float, str)  # 完成信号，发送 (时长, 错误信息)
    status = Signal(str)           # 状态信号，发送日志消息

    def __init__(self, ffmpeg_path: str, audio_path: str):
        super().__init__()
        self.ffmpeg_path_str = ffmpeg_path
        self.audio_path_str = audio_path

    def run(self):
        """
        线程执行体。调用 ffprobe 获取音频时长。
        """
        try:
            from video_processor import get_ffmpeg_probe_path
            ffprobe_path = get_ffmpeg_probe_path(self.ffmpeg_path_str)

            cmd = [
                ffprobe_path, '-v', 'error', '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1', self.audio_path_str
            ]
            result = subprocess.run(
                cmd, check=True, capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            duration = float(result.stdout.strip())
            self.finished.emit(duration, "")
        # [优化] 捕获更具体的异常
        except FileNotFoundError as e:
            error_msg = f"无法找到 ffprobe: {e}"
            self.status.emit(error_msg)
            self.finished.emit(0, error_msg)
        except subprocess.CalledProcessError as e:
            error_msg = f"ffprobe 执行失败: {e.stderr or e.stdout or e}"
            self.status.emit(error_msg)
            self.finished.emit(0, error_msg)
        except Exception as e:
            error_msg = f"获取音频时长时发生未知错误: {e}"
            self.status.emit(error_msg)
            self.finished.emit(0, error_msg)


class VideoWorker(QThread):
    """
    在后台线程中生成最终视频的 Worker。
    """
    progress = Signal(int, str)    # 进度信号，发送 (百分比, 剩余时间字符串)
    status = Signal(str)           # 状态信号
    finished = Signal(str)         # 完成信号，发送成功或失败的消息

    def __init__(self, params: VideoGenParams):
        super().__init__()
        self.params = params

    def run(self):
        """
        线程执行体。调用 create_karaoke_video 函数生成视频。
        """
        try:
            start_time = time.time()
            logger = QtProglogLogger(self, start_time)
            self.params.logger = logger
            create_karaoke_video(params=self.params)
            self.finished.emit("成功！视频已生成。")
        # [优化] 捕获更具体的异常
        except (subprocess.CalledProcessError, ValueError, FileNotFoundError) as e:
            traceback.print_exc()
            self.finished.emit(f"发生错误: {e}")
        except Exception as e:
            traceback.print_exc()
            self.finished.emit(f"发生未知错误: {e}")


class PreviewWorker(QThread):
    """
    在后台线程中生成预览帧的 Worker。
    """
    finished = Signal(QPixmap, str) # 完成信号，发送 (预览图, 错误信息)
    status = Signal(str)            # 状态信号

    def __init__(self, params: VideoGenParams):
        super().__init__()
        self.params = params

    def run(self):
        """
        线程执行体。调用 create_preview_frame 函数生成预览。
        """
        try:
            logger = QtProglogLogger(self, time.time())
            self.params.logger = logger
            
            create_preview_frame(params=self.params)
            
            output_path = str(self.params.output_image_path)
            if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
                raise FileNotFoundError("FFmpeg未能成功创建预览图片。")

            pixmap = QPixmap(output_path)
            if pixmap.isNull():
                 self.finished.emit(QPixmap(), "生成的预览图片无效或无法加载。")
            else:
                self.finished.emit(pixmap, "")
        # [优化] 捕获更具体的异常
        except (subprocess.CalledProcessError, ValueError, FileNotFoundError) as e:
            traceback.print_exc()
            self.finished.emit(QPixmap(), f"生成预览时发生错误: {e}")
        except Exception as e:
            traceback.print_exc()
            self.finished.emit(QPixmap(), f"生成预览时发生未知错误: {e}")