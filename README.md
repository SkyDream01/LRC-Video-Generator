# LRC Video Generator — LRC Video Maker

LRC Video Generator 把音频、LRC 歌词和封面合成为动态歌词视频。默认输出为 1920×1080、60 fps 的 MP4，预览和导出使用同一套场景状态与 QPainter 合成逻辑。

LRC Video Generator 面向两类使用方式：

- GUI：选择素材、调整歌词/动画/色彩/输出参数，实时预览后导出。
- CLI：用 `.kproj` 工程或命令行素材直接出片，也可生成自带素材的演示工程。

完整设计约束仍以 [`DESIGN.md`](DESIGN.md) 为准；本页和 `docs/` 只说明当前代码可执行的使用方式。

## 文档导航

- [用户指南](docs/USER_GUIDE.md)：安装、GUI 操作、LRC 写法、CLI 出片。
- [工程文件格式](docs/PROJECT_FORMAT.md)：`.kproj` v1.1 字段、路径和迁移规则。
- [开发指南](docs/DEVELOPMENT.md)：架构、测试、动画扩展和打包入口。
- [故障排查](docs/TROUBLESHOOTING.md)：FFmpeg、音频、字体、歌词和导出问题。
- [`DESIGN.md`](DESIGN.md)：项目设计方案与不可违反的工程约定。

## 快速开始

### 1. 安装 Python 依赖

Python 3.10 或更新版本：

```bash
python -m pip install -r requirements.txt
```

Windows 也可以直接双击 `start.bat` 启动 GUI。脚本会优先使用 `py -3`，找不到时再使用 `python`。

### 2. 准备 FFmpeg

导出需要 `ffmpeg`；时长探测优先使用 `ffprobe`。在 Windows 中可把以下文件放进项目的 `ffmpeg/` 目录：

```text
ffmpeg/ffmpeg.exe
ffmpeg/ffprobe.exe       # 可选；缺少时回退到 mutagen 读取时长
```

也可以把它们加入系统 `PATH`。程序查找 `ffmpeg.exe` 时优先使用项目目录版本，再查找 `PATH`。FFmpeg 二进制和用户字体不会随 Git 仓库提交。

没有 FFmpeg 时，GUI 仍可打开工程和准备预览，但无法导出；音频解码失败时的 PCM 回退也不可用。

### 3. 运行演示

下面的命令会生成 8 秒演示素材、`.kproj` 工程并导出视频：

```bash
python main.py demo --dir output/demo
```

生成目录包含 `demo.wav`、`demo_cover.png`、`demo.lrc`、`demo.kproj` 和 `demo.mp4`。想先做快速冒烟检查，可限制帧数：

```bash
python main.py demo --dir output/demo --frames 60 --output output/demo/smoke.mp4
```

`--frames` 是调试选项，会让视频只编码指定帧数，不适合正式出片。

### 4. 启动 GUI

```bash
python main.py gui
```

在“素材”面板选择音频和 LRC；封面、背景图均可选。资源准备完成后，使用“参数”面板调整效果，按 `Ctrl+E` 导出 MP4。

## 支持范围

| 输入/功能 | 当前支持 |
| --- | --- |
| 音频 | `.mp3`、`.wav`、`.flac`、`.m4a` |
| 封面/背景 | `.jpg`、`.jpeg`、`.png`、`.webp` |
| 歌词 | 标准 LRC、多时间标签、双语配对、`[offset:]`、Enhanced LRC 词级标签解析 |
| 背景动画 | 静态模糊、渐变波浪、波浪模糊 |
| 歌词动画 | 淡入淡出、滚动列表 |
| 封面动画 | 静态展示、黑胶唱片旋转 |
| 工程 | UTF-8 JSON `.kproj`，当前版本 v1.1 |
| 视频 | H.264 / AAC / MP4，默认 1920×1080 @ 60 fps |

Enhanced LRC 的词级时间会被解析并保存在歌词数据中；当前画面动画仍按“行”切换，不提供逐词高亮。

## CLI 出片

### 使用工程文件

```bash
python main.py export --kproj path/to/project.kproj --output path/to/result.mp4
```

### 直接使用素材

```bash
python main.py export --audio path/to/music.flac --lrc path/to/lyrics.lrc --cover path/to/cover.jpg --background path/to/background.jpg --output path/to/result.mp4
```

直接出片至少需要 `--audio` 和 `--lrc`；封面和背景可省略。常用覆盖参数：

| 参数 | 取值/说明 |
| --- | --- |
| `--fps` | `30` 或 `60`，默认 60 |
| `--encoder` | `auto`、`h264_nvenc`、`h264_amf`、`h264_qsv`、`libx264` |
| `--duration` | 用秒数覆盖自动探测的时长 |
| `--frames` | 限制编码帧数，仅建议调试使用 |
| `--output` | 输出 MP4 路径；省略时按音频文件名生成 |

`auto` 会按 NVENC → AMF → QSV → libx264 顺序进行可用性探测；硬件编码启动或写帧失败时会重跑 `libx264`。编码过程写入输出目录下的临时 MP4，成功后才替换目标文件。

## GUI 操作要点

1. 在“素材”面板选择音频、封面和 LRC；背景图片不是必需项。
2. 等待资源准备完成。连续修改参数会合并为一次后台准备，播放路径不会重新光栅化文字。
3. 在“歌词样式”设置字体、字号、颜色和描边，在“动画”选择三层动画，在“色彩”选择自动或手动取色，在“输出”选择帧率、编码器和码率。
4. 用时间轴拖动预览，或使用“设置 → 精确预览当前帧”生成 1920×1080 离屏帧。
5. 保存 `.kproj` 以便下次继续编辑，按 `Ctrl+E` 选择输出文件并导出。

快捷键：`Ctrl+O` 打开工程，`Ctrl+S` 保存，`Ctrl+E` 导出，`Ctrl+Q` 退出，空格播放/暂停，`Home` 跳到开头，`End` 跳到结尾，`F5` 精确预览当前帧。

## 输出默认值

| 项目 | 默认值 |
| --- | --- |
| 画布 | 1920×1080，`landscape_mv`（封面左、歌词右） |
| 帧率 | 60 fps |
| 视频 | H.264 High Profile；硬件编码自动回退到 `libx264` |
| 颜色 | `yuv420p`、BT.709、tv range |
| 音频 | AAC-LC，320 kbps，48 kHz，立体声 |
| 封装 | MP4，`+faststart` |

GUI 当前只提供 `landscape_mv` 布局；宽高字段保存在工程格式中，但不在参数面板单独编辑。手动修改工程宽高时必须使用偶数，否则 YUV420P 导出会被拒绝。

## 项目结构

```text
LRC Video Generator/
├── main.py                  # CLI 与 GUI 入口
├── app/core/                # 无 PySide6 依赖的渲染核心
│   ├── project.py           # KProj 模型、JSON 读写、版本迁移
│   ├── lrc.py               # LRC 解析与双语配对
│   ├── timeline.py          # 歌词区间与当前行定位
│   ├── context.py           # 媒体、布局、元数据和取色快照
│   ├── prepare.py           # Pillow/NumPy 资源光栅化
│   ├── scene.py             # prepare 缓存与 eval(t) 状态
│   ├── color.py             # K-Means 取色与对比度选色
│   ├── encoder.py           # FFmpeg 探测和编码管道
│   └── anims/               # 背景、歌词、封面策略层
├── app/gui/                 # PySide6 界面、预览、控制器和导出
├── docs/                    # 面向用户和贡献者的使用文档
├── tests/                   # core、GUI、合成和导出测试
├── font/                    # 用户字体目录（.ttf/.otf）
├── ffmpeg/                  # 可选的本地 FFmpeg 目录
├── requirements.txt
├── pytest.ini
├── start.bat
├── DESIGN.md
└── AGENTS.md
```

## 开发检查

```bash
pytest                    # 全部测试
pytest tests/test_lrc.py  # 单模块
pytest -m qt              # Qt/离屏用例
```

核心代码禁止导入 PySide6；预览和导出必须继续共享 `prepare → eval(t) → composite`。详细工程约束、测试要求和发布方案见 [`DESIGN.md`](DESIGN.md) 与 [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md)。
