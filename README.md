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
| 歌词 | 标准 LRC、多时间标签、双语配对、`[offset:]`、Enhanced LRC 逐字解析与高亮 |
| 背景动画 | 静态模糊、渐变波浪、波浪模糊、呼吸缩放 |
| 歌词动画 | 淡入淡出、滚动列表、滑入滑出、横向揭幕 |
| 封面动画 | 静态展示、黑胶唱片旋转、呼吸缩放、悬浮 |
| 工程 | UTF-8 JSON `.kproj`，当前版本 v1.1 |
| 视频 | H.264 / AAC / MP4，默认 1920×1080 @ 60 fps |

Enhanced LRC 自动按 `<时间戳>文字` 逐字/逐词提亮，可与所有歌词动画叠加，预览与导出效果一致。例如：

```lrc
[00:24.870]<00:24.870>聪<00:26.360>明<00:26.670>的<00:26.810>你　<00:28.210>告<00:28.510>诉<00:29.210>我<00:29.670>什<00:29.870>么<00:29.970>是<00:30.270>真<00:30.820>理<00:32.550>
```

每个时间戳标记后续文字的起唱时间，下一个时间戳标记其结束时间。末尾没有文字的标签（如 `<00:32.550>`）作为最后一个字的结束时间；若省略，则持续到下一行开始或音频结束。原文空格（含全角空格）保留，`[offset:]` 同步调整行与字的时间。未唱部分降低亮度，已唱部分恢复设定颜色；译文仍按整行显示。

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

## Windows 绿色版构建与验证

### 构建环境和外部文件

在 Windows x64 上安装 **CPython 3.13.15 x64**，使用专用虚拟环境。源码运行仍支持 Python ≥ 3.10；发布构建另用 `requirements-build.txt` 固定运行库、Qt、PyInstaller 和传递依赖版本，脚本会检查版本是否一致。

构建前按需放入以下文件（不会自动下载）：

- `ffmpeg/ffmpeg.exe`：完整离线导出需要，须支持 H.264/libx264 和 AAC。
- `ffmpeg/ffprobe.exe`：建议与 FFmpeg 来自同一发行版本；缺省时应用回退到 mutagen。
- `font/*.ttf`、`font/*.otf`：建议提供覆盖中文的字体。未提供时使用系统字体，跨机器的文字外观可能不同。
- `resources/`：目前仓库没有此目录；以后加入的资源会按原有相对路径自动包含。

建议提供自包含的 Windows x64 FFmpeg 工具；若使用依赖 DLL 的发行包，需要把它所需的 DLL 一起放进 `ffmpeg/`。该目录会原样分发，可同时放入发行包的许可证说明；发布者需确认 FFmpeg 和字体的再分发许可。Qt 的多媒体 DLL/插件由 PyInstaller 官方 hooks 收集，它们不能替代导出所用的外部 `ffmpeg.exe`。

在项目根目录运行 PowerShell：

```powershell
py -3.13 -m venv .venv-build
.\.venv-build\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv-build\Scripts\python.exe build.py
```

`py -3.13` 必须指向上述补丁版本；版本不符时脚本会停止。脚本从自身路径定位项目，故也可在其他工作目录通过绝对路径调用。打包子进程会收窄 PATH 到 Python 和 Windows 系统目录，避免误收集其他软件的同名 DLL。重新构建会替换 `dist/LRCVideoMaker/`，不要把个人工程或媒体放在此构建输出目录。

产物为 `dist/LRCVideoMaker/`，应复制或压缩**整个目录**，不能只取 EXE：

```text
LRCVideoMaker/
├── LRCVideoMaker.exe
├── LRCVideoMaker-CLI.exe    # 控制台版，支持 demo/export/--help
├── assets/                 # logo.png 和多尺寸 logo.ico
├── font/
├── ffmpeg/                 # 有提供时包含外部工具；否则为空占位目录
├── resources/              # 有提供时包含
├── docs/、examples/、README.md、LICENSE
├── build-manifest.json     # Python、依赖版本和所有产物的 SHA-256（不含清单自身）
└── Python/Qt/扩展模块和依赖 DLL 等运行文件
```

`app` 作为 Python 模块归档收集，不需要旁置源码。使用 `contents_directory="."` 的平铺 onedir 布局，让现有基于 `__file__` 的资源路径仍指向 EXE 所在目录，避免依赖当前工作目录；此选项见 [PyInstaller 官方说明](https://www.pyinstaller.org/en/stable/usage.html)。禁用 UPX，不生成单文件自解压程序。

双击 `LRCVideoMaker.exe` 打开 GUI，无控制台窗口；`LRCVideoMaker-CLI.exe` 提供 `demo`、`export` 和诊断输出。两个入口共享同一份依赖和资源。程序及窗口使用 `assets/logo.ico`；logo 设计与来源见 [assets/README.md](assets/README.md)。用户不需要安装 Python。没有随包 FFmpeg 时仍可打开 GUI；导出会继续尝试系统 PATH。

构建还会生成 `dist/LRCVideoMaker-Portable.zip`，可直接分发。保留 PyInstaller onedir 实现（符合 DESIGN.md），没有引入参考脚本中本项目不使用的 Nuitka、pykakasi 或 styles.qss。

需要参考方案中的自解压 EXE 时，安装 [7-Zip](https://www.7-zip.org/) 并运行：

```powershell
.\.venv-build\Scripts\python.exe build.py --sfx --seven-zip 'C:\Program Files\7-Zip\7z.exe'
```

默认使用同目录的 `7z.sfx`，生成 `dist/LRCVideoMaker-Portable.exe`，让用户选择解压目录后手动启动程序。若明确需要临时解压并自动运行，可追加 `--sfx-module 'C:\Tools\7zSD.sfx'`（或 `7zS.sfx`）；该模式退出后临时文件会被清理，工程和导出应存到其他目录。普通 `7z.sfx` 不拼接 `RunProgram` 配置。7-Zip 工具及 SFX 模块须由构建者自行提供，不入库；缺失时在构建前报错。SFX 使用独立临时归档并验证完整性，失败返回非零退出码，不会把旧归档内容混入新包。

这里的“可复现”指固定环境、相同源码与外部资源可重复构建相同功能的目录包，不承诺 EXE 逐字节相同。请保存源码提交号、`requirements-build.txt`、外部工具/字体及 `build-manifest.json`；更换外部文件或 Windows 系统字体会影响结果。仓库只提交配置、脚本和说明，`build/`、`dist/`、虚拟环境、日志、用户字体和 `ffmpeg/` 下的外部文件均已忽略。

### 验证绿色版

1. 把整个产物复制到另一个含中文和空格的可写路径，例如 `C:\Temp\歌词 视频\LRCVideoMaker`；最好在未安装 Python、PATH 中没有 FFmpeg 的 Windows x64 测试机验证。
2. 从不同工作目录运行以下命令，确认 CLI 模块及离屏 Qt 渲染正常。短片强制软件编码，避免依赖显卡：

```powershell
$bundle = 'C:\Temp\歌词 视频\LRCVideoMaker'
Set-Location $env:TEMP
& "$bundle\LRCVideoMaker-CLI.exe" --help
& "$bundle\ffmpeg\ffmpeg.exe" -version
& "$bundle\ffmpeg\ffprobe.exe" -version
& "$bundle\LRCVideoMaker-CLI.exe" demo --dir "$env:TEMP\lvm-smoke" --frames 60 --encoder libx264
if ($LASTEXITCODE -ne 0) { throw '绿色版导出失败' }
& "$bundle\ffmpeg\ffprobe.exe" -v error -select_streams v:0 -show_entries stream=width,height,r_frame_rate,nb_frames,color_space,color_transfer,color_primaries,color_range -of json "$env:TEMP\lvm-smoke\demo.mp4"
```

预期视频为 1920×1080、60/1 fps、60 帧，颜色为 BT.709 / tv。FFmpeg 未随包时跳过版本和导出检查，或先人工补齐工具；不要把只能通过 `--help` 当作完整导出验收。

3. 双击 EXE，确认 GUI、字体选择、中文歌词、播放声音、预览、打开/保存工程、导出正常；检查字体目录能识别随包字体。搬移已有 `.kproj` 时，其引用的媒体也必须按工程相对路径一起搬移。
4. 在 PATH 不含 FFmpeg 的环境临时移走随包 `ffmpeg/` 后重新启动，确认界面仍可用并提示缺少 FFmpeg、不能导出；验证后恢复目录。

源码检查可在开发环境运行 `python -m pytest -q`；构建日志中的缺失模块警告需结合实际导入及上述运行验证判断。`build-manifest.json` 的 SHA-256 可用于检查复制后的文件是否完整。

## 开发检查

```bash
pytest                    # 全部测试
pytest tests/test_lrc.py  # 单模块
pytest -m qt              # Qt/离屏用例
```

核心代码禁止导入 PySide6；预览和导出必须继续共享 `prepare → eval(t) → composite`。详细工程约束、测试要求和发布方案见 [`DESIGN.md`](DESIGN.md) 与 [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md)。
