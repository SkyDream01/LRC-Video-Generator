"""GUI 层：PySide6 界面、共用合成（composite）、控制器与工作线程。

依赖方向：GUI → controllers → core，单向。worker 线程内禁止创建 QPixmap。
"""
