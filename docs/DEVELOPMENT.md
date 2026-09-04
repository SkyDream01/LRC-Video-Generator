# 开发指南

本页面向维护 LRC Video Generator 的贡献者。工程设计的唯一来源是 [`DESIGN.md`](../DESIGN.md)；这里提供可以直接执行的开发入口和当前代码结构。

## 本地环境

Python 3.10 或更高版本。建议使用虚拟环境：

```bash
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
# macOS / Linux
# source .venv/bin/activate
python -m pip install -r requirements.txt
```

依赖分为运行时和开发工具：

- 运行时：PySide6、Pillow、NumPy、mutagen。
- 开发/测试：pytest、PyInstaller。
- 外部程序：FFmpeg；`ffprobe` 建议一并安装。

项目根目录中的 `font/` 和 `ffmpeg/` 是运行时查找目录。它们只保留 `.gitkeep` 或说明，不应把用户字体和二进制提交进仓库。

## 入口与命令

```bash
python main.py gui
python main.py demo --dir output/demo --frames 60
python main.py export --kproj path/to/project.kproj --output out.mp4
```

查看完整 CLI 参数：

```bash
python main.py --help
python main.py export --help
python main.py demo --help
```

## 测试

```bash
pytest
pytest tests/test_lrc.py
pytest -m qt
```

当前测试约定：

- core 测试不依赖 PySide6。
- `tests/test_composite.py`、`tests/test_export.py`、`tests/test_gui_m2.py`、Qt 相关用例标记为 `qt`；没有 Qt 时通过 `importorskip` 跳过。
- 导出冒烟测试需要 FFmpeg；找不到时跳过，不应把缺失外部程序误判为 core 回归。
- 合成测试使用离屏 `QImage`；字体、Qt 和 FreeType 差异应使用合理的像素容差。

测试覆盖 LRC 容错、时间轴边界、固定种子取色、工程往返/迁移、动画 schema、SceneState 确定性、紧 bbox 文字位图、QPainter 合成、FFmpeg 命令和导出取消。

## 分层与依赖方向

```text
GUI (PySide6)
  └─ controllers / workers / panels / preview / composite
       └─ core
            ├─ context / project / lrc / timeline / color
            ├─ prepare / scene / anims
            └─ encoder（FFmpeg、mutagen 边界）
```

依赖只能从上层指向下层：

- `app/core/` 禁止导入 PySide6，可直接被 pytest 导入。
- `app/gui/composite.py` 是预览与导出的共同像素合成入口。
- 控制器负责把 UI 改动写入 `KProj`，并调度后台 worker。
- worker 只能把可跨线程的数据带回主线程；不得在 worker 中创建 `QPixmap`。

## 渲染生命周期

```text
工程 + 媒体
    │
    ▼
build_context()
    │  读取媒体、LRC、元数据、布局和颜色
    ▼
Scene.prepare()
    │  Pillow/NumPy 光栅化并缓存紧 bbox 位图
    ▼
Scene.eval(t)
    │  输出透明度、位移、旋转角度和当前行
    ▼
composite(painter, state, assets)
    ├─ PreviewSurface：缩放到窗口
    └─ render_video：1920×1080 QImage → FFmpeg rawvideo
```

核心约束：

1. `prepare` 只在资源或参数变化时运行，不能放到播放逐帧路径。
2. `eval(t)` 是无副作用的纯状态计算，不能读文件或修改像素。
3. `composite` 使用逻辑坐标绘制；预览只设置缩放，导出使用目标画布。
4. 歌词位图必须是紧 bbox 并携带 origin 偏移；不要把一整幅 1920×1080 图缓存到每行。
5. 唱片只在 `composite` 中旋转小贴图，不做整帧旋转或手写 NumPy warp。

## GUI 线程与时钟

- 参数/素材变化经过 80 ms debounce；请求带 generation，过期的 prepare 结果会丢弃。
- `paintEvent` 只做 `eval(t)` 与 `composite`，不运行 Pillow 光栅化。
- 播放主时钟来自单调时钟；主窗口约每 500 ms 用音频 PTS 纠漂，偏差超过 80 ms 才重锚。
- scrub 拖动时先只重锚预览时钟，松开后再把 seek 同步给音频引擎。
- Qt Multimedia 是音频播放首选；Qt 解码失败时切换到 FFmpeg 解 PCM + `QAudioSink`。

## 新增动画

动画采用策略类和注册表。新增一个内置动画时：

1. 在 `app/core/anims/` 合适的模块中创建 `BaseLayer` 子类。
2. 设置 `kind`、`anim_type` 和用户可见的 `label`。
3. 实现 `prepare(ctx)` 和纯 `eval(t, ctx)`。
4. 有参数时实现 `params_schema()`，通过 `ParamSpec` 声明类型、默认值、范围或选项。
5. 用 `@register(KIND_...)` 注册，并在 `app/core/anims/__init__.py` 导入模块/类，使注册表在启动时填充。
6. 为注册表、参数收敛、`eval` 确定性和关键帧行为补 pytest；如果 schema 变化，同步工程示例和格式文档。

GUI 的动画下拉框和参数控件会读取 `ANIM_REGISTRY` 与 `params_schema`，不要在 GUI 中为某一种动画硬编码参数。

## 工程模型变更

用户参数应归入 `app/core/project.py` 的 dataclass，并通过 `kproj_from_dict` 做外部 JSON 的类型收敛。修改字段时检查：

- 缺失值的默认行为；
- 非法类型、未知字段和越界值；
- 保存/加载往返；
- 旧版本迁移；
- GUI 控件绑定和 `restore_defaults` 的范围。

工程文件的公开说明见 [`PROJECT_FORMAT.md`](PROJECT_FORMAT.md)。

## 编码与导出

`app/core/encoder.py` 负责二进制查找、时长、编码器探测和命令构建；`app/gui/exporter.py` 负责创建离屏 Qt、逐帧合成和临时输出文件。

导出约定：

- 帧数 `N = round(duration × fps)`，命令必须带 `-frames:v N`。
- rawvideo 输入为 `rgb24`；FFmpeg 负责 BT.709 full → tv 的 `yuv420p` 转换。
- 编码器顺序为 NVENC → AMF → QSV → `libx264`。
- `Popen` 的 pipe buffer 至少 8 MiB，并持续读取 stderr，避免子进程背压。
- 每次编码尝试先写同目录临时文件，成功后才替换最终输出；取消或失败时不损坏已有成品。

修改命令参数时应同步 `tests/test_encoder.py` 和 `tests/test_export.py`，至少检查像素格式、色彩标签、帧数、音频映射和 `+faststart`。

## 文档与发布

面向用户的说明从 [`README.md`](../README.md) 开始，按主题拆分到 `docs/`。`AGENTS.md` 是代理和贡献约束，不要把它当作最终用户教程。

PyInstaller 的发布方向写在 [`DESIGN.md`](../DESIGN.md) 第 9.2 节。仓库当前未提交专用 `.spec` 文件；打包前要确认 `font/`、需要的资源目录以及可选 FFmpeg 的分发策略。

提交前建议运行：

```bash
pytest
python main.py demo --dir output/doc-check --frames 60
```

## 相关文件

- [`AGENTS.md`](../AGENTS.md)：工程约束和贡献规则。
- [`DESIGN.md`](../DESIGN.md)：设计方案唯一来源。
- [`PROJECT_FORMAT.md`](PROJECT_FORMAT.md)：`.kproj` 格式。
- [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md)：常见问题。
