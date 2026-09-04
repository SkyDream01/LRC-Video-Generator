# LRC Video Maker — 设计方案

## 1. 项目概述

**定位**: 将音频、LRC 双语歌词、专辑封面三要素合成为专业水准的卡拉OK/动态歌词视频（MP4，默认 1920×1080@60fps）。GUI 采用 PySide6。

**目标用户**: 音乐爱好者、翻唱创作者、内容制作者——无需专业视频编辑技能即可一键生成歌词视频。

---

## 2. 功能模块

| 功能 | 描述 |
| ------ | ------ |
| 文件输入 | 加载音频 (.mp3/.wav/.flac/.m4a)、封面图 (.jpg/.png/.webp)、LRC 歌词、可选独立背景图 |
| 元数据 | mutagen 读 ID3 标题/艺术家/专辑，输入面板展示；可选叠到画面（开场或角标） |
| 工程管理 | `.kproj` JSON 工程文件的保存/加载，版本号兼容 (v1.1) |
| 实时预览 | 预光栅化图层 + 共用 QPainter 合成；单调时钟跟音频纠漂，时间轴可 scrub |
| 智能色彩提取 | K-Means 从封面提取主色/辅色（动画用）；歌词色按歌词区域局部对比度选取 |
| 背景动画 | 静态模糊、渐变波浪（生成式）、波浪模糊（基于图片） |
| 歌词动画 | 淡入淡出（单行高亮）、滚动列表（多行高亮+缓动滚动） |
| 封面动画 | 静态展示（含倒影）、黑胶唱片旋转（含纹理+高光） |
| 硬件加速 | NVIDIA NVENC / AMD AMF / Intel QSV，回退到软件编码 libx264 |

---

## 3. 技术栈

### 3.1 选型总览

| 层次 | 技术 | 版本要求 | 用途 |
| ------ | ------ | ---------- | ------ |
| 语言 | Python | ≥ 3.10（推荐 3.11/3.12） | 主开发语言 |
| GUI 框架 | PySide6 (Qt 6) | ≥ 6.6 | 主窗口、参数面板、预览/导出合成、多线程调度 |
| 合成 | QPainter + QImage | Qt 6 | 预览与导出共用同一套叠画；预览可转 QPixmap |
| 音频预览 | Qt Multimedia | 随 PySide6 | QMediaPlayer 解码；时钟见 4.9，不直接当逐帧 PTS |
| 预光栅化 | Pillow + NumPy | ≥ 10.0 | prepare：字体/描边/模糊/唱片贴图；不参与逐帧合成 |
| 数值计算 | NumPy | ≥ 1.26 | 像素矩阵、渐变波浪、K-Means 取色；导出颜色转换由 FFmpeg 原生路径完成 |
| 音频元数据 | Mutagen + ffprobe | mutagen ≥ 1.47 | ID3 标签；时长以 ffprobe 为准，mutagen 回退 |
| 音频转码/封装 | FFmpeg（外部进程） | ≥ 5.0 | AAC 编码、rawvideo 编码、MP4 封装（含 ffprobe） |
| 字体渲染 | Pillow ImageFont（FreeType 后端） | — | 加载 font/ 目录下的 TTF/OTF；仅在 prepare 阶段光栅化 |
| 视频编码器 | libx264 / h264_nvenc / h264_amf / h264_qsv | — | 软件编码兜底 + 三家硬件编码 |
| 工程文件 | JSON（标准库） | — | `.kproj` 工程序列化 |
| 单元测试 | pytest | ≥ 8.0 | LRC 解析、时间轴、取色、kproj 读写、eval 确定性 |
| 桌面打包 | PyInstaller | ≥ 6.0 | 发布 Windows 单目录绿色版 |

### 3.2 关键选型理由

**为什么 prepare 用 Pillow，composite 预览和导出都用 QPainter？**

- 昂贵的是**光栅化**（字体描边、模糊、唱片贴图），不是叠图。拆成 `prepare`（慢、按需）→ `eval(t)`（纯状态）→ `composite(painter, …)`（快、每帧）。
- 预览与导出必须调用**同一份** `composite(painter, state, assets)`。QPainter vs Pillow 在旋转抗锯齿、straight/premultiplied alpha、缩放滤波上会系统性漂移，不能把「同一套 eval」当成所见即所得。
- 预览：`painter.scale(widget/1920, widget/1080)` 后调用 composite，目标 60fps。暂停或「精确预览」：离屏 1920×1080 QImage 合成再缩小，与导出像素一致。
- 导出：离屏 `QImage(1920, 1080)` + QPainter 调同一函数 → `bits()` 喂 ffmpeg。QImage+QPainter 可在 QThread 使用；禁止在 worker 里创建 QPixmap。
- CLI 出片需要 offscreen `QGuiApplication`（`QT_QPA_PLATFORM=offscreen`）。core 的 prepare/eval 仍零 Qt 依赖，pytest 测这两层；像素金帧用离屏 Qt 或跳过。
- 唱片旋转在 composite 里 `QPainter.rotate`，只转 cover 小贴图。禁止全帧旋转，也禁止手写 NumPy warp。

**为什么用 FFmpeg 子进程，而不是 OpenCV / moviepy / av(PyAV)？**

- 硬件编码器支持最全最稳定（NVENC/AMF/QSV 一套命令行通吃），这是本项目硬性需求。
- 通过 `stdin` 管道喂 rawvideo 帧：无需落盘中间帧、无命令行转义问题、内存占用恒定。
- moviepy 帧回调封装死板、性能差且自带 ffmpeg 版本旧；OpenCV 的 VideoWriter 对编码器控制粒度不足；PyAV 引入编译依赖，打包体积大。

**为什么取色用手写 NumPy K-Means，而不是 scikit-learn？**

- 取色只需在 ≤64×64 的小图上跑 k=5 的聚类，几十行 NumPy 即可，确定性好（固定随机种子）。
- 避免 sklearn 约 40MB 的打包体积与启动开销。

**为什么预览不先导出再播、也不每帧跑全量光栅化？**

- 先导出再播等于没有预览，改个字号要等整首歌编码。
- 每帧重跑字体/模糊，拖动时间轴会卡，更无法 60fps 跟音频。
- 正确做法：参数变化才 `prepare`；播放时只 `eval(t)` + 廉价 QPainter 合成。

### 3.3 依赖清单

```text
# requirements.txt
PySide6>=6.6          # 含 QtMultimedia（部分发行版需 PySide6-Addons）
Pillow>=10.0
numpy>=1.26
mutagen>=1.47

# dev
pytest>=8.0
pyinstaller>=6.0
```

**外部依赖**: FFmpeg 可执行文件（含 ffprobe）。查找顺序：① 应用目录下的 `ffmpeg/ffmpeg.exe`（随包分发）→ ② 系统 `PATH`。启动时只探测**二进制是否存在**，找不到则禁用导出与 FLAC PCM 回退，预览（可解码格式）/工程管理仍可用。编码器实编码探测见 4.8，不放在启动路径。

---

## 4. 设计思路

### 4.1 总体架构（分层）

```text
┌─────────────────────────────────────────────────────┐
│                  GUI 层 (PySide6)                    │
│   MainWindow · 输入面板 · 参数面板 · 时间轴            │
│   composite.py（QPainter，预览与导出共用）             │
│   PreviewSurface · ExportWorker 都调用它              │
├─────────────────────────────────────────────────────┤
│                应用控制层 (controllers)               │
│   ProjectController · PreviewController · ExportController │
├─────────────────────────────────────────────────────┤
│             渲染核心 core（纯 Python，无 GUI 依赖）    │
│   lrc · timeline · scene(eval) · prepare · anims · color │
├─────────────────────────────────────────────────────┤
│         基础设施：ffmpeg/ffprobe 封装 · mutagen · 缓存  │
└─────────────────────────────────────────────────────┘
依赖方向：上层 → 下层，单向。
core 禁止 import PySide6（prepare/eval/lrc/color/project 可被 pytest 直接测）。
composite 与导出依赖 Qt；CLI 使用 offscreen QGuiApplication。
```

**五条核心原则：**

1. **所见即所得**——预览与导出共用 `prepare()` 图层资源、`eval(t) → SceneState`、以及同一份 `composite(painter, state, assets)`。仅绘制目标不同（缩放后的控件 vs 离屏 1920×1080 QImage）。导出默认锁定 1920×1080@60。
2. **状态与像素分离**——`eval(t)` 是无副作用纯函数（角度/透明度/位移），不碰像素；`prepare` 只在资源或参数变化时运行。天然可缓存、可测。
3. **策略模式动画**——每类动画实现统一接口，并声明 `params_schema`；通过注册表接入。新增动画 = 写 1 个类 + 注册 1 行，GUI 下拉框与参数控件按 schema 生成。
4. **参数对象化**——所有用户参数收敛为 `dataclass` 配置对象，序列化为 JSON 即 `.kproj`，UI 控件与配置字段一一映射。
5. **硬件自适应**——首次导出或后台探测可用编码器，NVENC → AMF → QSV → libx264 逐级回退，探测失败不阻塞启动。

### 4.2 目录结构

```text
LVM/
├── main.py                  # 入口：QApplication + MainWindow
├── app/
│   ├── core/                # —— 渲染核心（无 GUI 依赖）——
│   │   ├── project.py       #   KProj 工程模型：dataclass + JSON 读写 + 版本迁移
│   │   ├── lrc.py           #   LRC 解析 → LyricLine 列表（含双语配对、元数据）
│   │   ├── timeline.py      #   时间轴：bisect 定位当前行、行区间计算
│   │   ├── color.py         #   K-Means 取色 + 歌词区域对比度选色
│   │   ├── scene.py         #   eval(t) → SceneState（纯动画状态，无像素）
│   │   ├── prepare.py       #   prepare 图层资源（Pillow/NumPy，紧 bbox）
│   │   ├── encoder.py       #   ffmpeg 编码器探测 + rawvideo 管道封装
│   │   └── anims/
│   │       ├── base.py      #   BaseLayer：prepare / eval / params_schema / 注册表
│   │       ├── background.py#   静态模糊 / 渐变波浪 / 波浪模糊
│   │       ├── lyrics.py    #   淡入淡出 / 滚动列表
│   │       └── cover.py     #   静态展示+倒影 / 黑胶唱片旋转
│   ├── gui/                 # —— PySide6 界面 ——
│   │   ├── main_window.py   #   主窗口与菜单
│   │   ├── composite.py     #   共用 QPainter 合成（预览 + 导出）
│   │   ├── panels/input_panel.py    # 左侧文件输入
│   │   ├── panels/params_panel.py   # 右侧参数 Tab（按 schema 生成动画参数）
│   │   ├── preview.py       #   PreviewSurface：调用 composite + 16:9 显示
│   │   ├── audio_player.py  #   QMediaPlayer / ffmpeg PCM 回退 + 纠漂时钟
│   │   ├── timeline_bar.py  #   底部时间轴（含歌词刻度、播放头）
│   │   └── workers.py       #   AssetPrepWorker / ExportWorker (QThread)
│   └── resources/           # 图标、默认配置
├── font/                    # 用户字体目录（自动扫描 .ttf/.otf）
├── ffmpeg/                  # 可选：随包分发的 ffmpeg.exe
├── tests/                   # pytest 用例
└── requirements.txt
```

### 4.3 核心数据流

```text
[音频/LRC/封面/字体/KProj]
        │
        ▼  资源或参数变化（80ms debounce，带 prep_gen）
    prepare(ctx) ──► LayerAssets（紧 bbox RGBA、布局矩形、相位图）
        │
        ├─► GUI 主线程：numpy → QImage →（预览）QPixmap
        │       PreviewSurface: eval(t) + composite(painter, …)   60fps
        │                         ▲
        │                         └── 时钟：单调时间 + 音频 PTS 纠漂 / scrub
        │
        └─► 导出 QThread：numpy → QImage（禁止 QPixmap）
                for i in 0..N-1:
                  t = i / fps
                  离屏 QImage + composite(painter, eval(t), assets)
                  QImage 紧凑 RGB buffer → FFmpeg 原生 BT.709/yuv420p → stdin
                N = round(duration * fps)，并传 -frames:v N
                      ▼
                 output.mp4
```

### 4.4 渲染管线（prepare / eval / composite）

导出 1920×1080@60 是底线。预览不再每帧全量光栅化，三阶段如下：

```text
prepare(ctx)     慢，仅资源/参数变化时
  · 布局矩形（cover_rect / lyrics_rect / safe_area）
  · 背景静态层；波浪则生成可平铺的相位贴图（1/4 分辨率）
  · 唱片：封面+纹理+高光合成一张贴图（仅 cover_rect 大小，可 2× 抗锯齿）
  · 每行歌词（主词+译文+描边）各一张 **紧 bbox RGBA** + origin 偏移
    禁止按 1920 宽全幅画布缓存（200 行会到数百 MB）
  · 超宽策略：优先缩小字号适配 lyrics_rect 宽度；仍溢出则换行（最多 2 行）

eval(t) → SceneState    纯函数，微秒级
  · disc_angle、wave_phase
  · 当前行、每行 x / y / opacity / highlight
  · 倒影 alpha、元数据条 alpha 等

composite(painter, state, assets)    预览与导出同一函数
  · 调用方负责设置 painter 变换与渲染目标
  · 背景 blit 或按 wave_phase 平移源矩形
  · 唱片：translate(cover_center); rotate(disc_angle); draw 贴图
  · 歌词：按 origin+(x,y) draw 紧 bbox 位图，设 opacity
  · 可选元数据条
```

**逻辑分辨率一律 1920×1080**：`prepare` 的位图和矩形只按导出分辨率生成一份。

#### 预览合成器（PreviewSurface）

```text
paintEvent:
  t = clock.now()                          # 见 4.9，不是 raw position()
  state = eval(t)                          # core，无像素
  p.scale(widget_w / 1920, widget_h / 1080)
  composite(p, state, assets)              # 与导出同一函数
```

- 驱动：播放中 `QTimer(16ms, PreciseTimer)` 只调 `update()`，**不当时钟**。暂停只在 scrub / prepare 完成时 `update()`。
- 暂停或点「精确预览」：离屏 1920×1080 `QImage` 调同一 `composite`，再缩小画到控件（与导出一致）。
- 无音频文件时仍可 scrub 静帧（时钟退回滑块）。
- 不把预览区做成 QLabel 贴 QImage：那会每帧上传整帧，打回全量 `render_frame` 老路。
- 普通 QWidget 没有 `frameSwapped`（那是 OpenGL Widget），不要用它驱动刷新。

### 4.5 动画系统（策略模式 + 注册表）

```python
class BaseLayer(ABC):
    """动画层：光栅化与逐帧状态分离。"""
    id: str
    label: str

    @classmethod
    def params_schema(cls) -> list[ParamSpec]:
        """供 GUI 生成控件、kproj 存 params。默认无额外参数。"""
        return []

    @abstractmethod
    def prepare(self, ctx: RenderContext) -> LayerAssets: ...

    @abstractmethod
    def eval(self, t: float, ctx: RenderContext) -> LayerState: ...

# 注册表：GUI 下拉框选项与 key 自动同步
ANIM_REGISTRY: dict[str, dict[str, type[BaseLayer]]] = {
    "background": {"static_blur": StaticBlurBG, "gradient_wave": GradientWaveBG, "wave_blur": WaveBlurBG},
    "lyrics":     {"fade": FadeLyrics, "scroll_list": ScrollListLyrics},
    "cover":      {"static": StaticCover, "disc_rotate": DiscRotate},
}
```

`.kproj` 中动画不是纯字符串，而是 `{type, params}`（见第 7 节）。切换 type 时 params 按新 schema 填默认值，未知 key 忽略。

内置 params 示例：

| 层 | type | params |
| ---- | ------ | -------- |
| background / gradient_wave | `speed`, `amp` | 相位速度、振幅 |
| lyrics / scroll_list | `lines`, `ease` | 可见行数、缓动名 |
| lyrics / fade | `fade_ms` | 淡入淡出毫秒 |
| cover / disc_rotate | `rpm` | 转速，默认 33.3 |

`RenderContext` 携带：工程参数、取色结果、字体缓存、媒体资产、总时长、元数据。动画类不直接读文件。

Scene 拥有 prepare 缓存；层上不提供「内部再 prepare 再 composite」的便捷 `render()`，避免漏缓存。

### 4.6 时间轴与 LRC 解析

- 解析 `[mm:ss.xx]` / `[mm:ss.xxx]` / `[mm:ss]` 标签（兼容多标签行），得到条目 `(time, text)` 并按时间排序。
- 元数据标签：`[ti:]` `[ar:]` `[al:]` `[offset:]`。`offset` 加到所有时间戳；标题/艺术家缺省时回退 ID3。
- **双语配对规则**：相邻两条目**时间戳相同**或差值 `< 0.05s` 时，第二条视为第一条的译文，合并为一行。
- `LyricLine.words: list[WordTiming] | None` 预留 Enhanced LRC（`<mm:ss.xx>词`）。v1 解析器可忽略词级标签，但数据模型必须留字段，避免 v1.2 破格式。
- 每行区间 `end = 下一行.start`，最后一行 `end = 音频总时长`。
- 当前行定位用 `bisect`，O(log n)。
- 视频帧数 `N = round(duration * fps)`，`duration` 优先 ffprobe，失败再用 mutagen。

### 4.7 色彩提取算法（color.py）

```text
1. 封面缩放至 ≤64×64，转 RGB 展平为 N×3
2. 丢弃近黑/近白/低饱和像素：S < 0.1 或 L < 0.08 或 L > 0.92
   （去掉边框、letterbox；若过滤后采样过少则回退全量像素）
3. NumPy 手写 K-Means（k=5，迭代 ≤20，固定种子）→ 5 个簇心 + 权重
4. 评分: score = 0.5·饱和度 + 0.3·亮度适中 + 0.2·簇面积
    ├─ 主色/辅色: 给波浪、光效、唱片氛围用（不再把主色 clamp 到 0.55~0.75）
    │    辅色: 与主色色相差 ≥ 30° 的次高分簇
    └─ 歌词色/描边色: 在 lyrics_rect 对应封面对应区域采样背景，
         选对比度更大的浅字+深描边（目标对比接近 WCAG AA 思路）
5. 手动模式下用户可覆盖任一颜色；勾选「自动」时每次换封面重新提取
```

歌词默认仍是白字深描边；自动模式优先保证**可读性**，主色用来驱动背景动画而不是强行给字体上色。

### 4.8 编码与硬件加速探测（encoder.py）

```python
def detect_encoder() -> str:
    for name in ["h264_nvenc", "h264_amf", "h264_qsv"]:
        if probe(name):        # 渲染 1 帧黑图, ffmpeg -frames:v 1 -f null - 试编码
            return name
    return "libx264"           # 兜底
```

- `-encoders` 列表里存在 ≠ 可用（驱动/会话问题），所以必须**实编码探测**。
- **启动只检查 ffmpeg/ffprobe 文件存在**。实编码探测在 UI 显示后的后台线程，或第一次点导出时进行；结果缓存到会话（可写入用户设置以免每次冷启动都探）。
- 导出时若硬编码中途失败，自动改用 libx264 重试并提示用户。
- 颜色标签一律写 BT.709，GOP 按 fps 设 2 秒（60fps → `-g 120`），便于平台播放与 seek。

### 4.9 线程模型与预览时钟

```text
GUI 主线程
  · 交互、QPainter 预览合成、音频播放
  · paintEvent 里只 eval(t)+composite，禁止 Pillow 光栅化
  · t 来源见下方时钟，禁止每帧读 raw QMediaPlayer.position()
  ├─ AssetPrepWorker (QThread)
  │    文件加载 / 参数变更（80ms debounce）→ prepare(ctx)
  │    产出 LayerAssets（numpy/bytes 或 QImage，禁止在 worker 里建 QPixmap）
  │    请求带单调递增 prep_gen；完成时若 gen 已过期则丢弃
  │    主线程收到信号后转 QPixmap，替换 PreviewSurface 资源
  └─ ExportWorker (QThread)
       先 prepare（或复用已有 assets → QImage）
       循环 t=i/fps：离屏 QImage composite → 紧凑 RGB pipe.write → signal(i/N)
       FFmpeg 内部执行 RGB full-range → BT.709 limited-range yuv420p
       取消即关 stdin / 杀进程；ffmpeg 失败回退 libx264
```

预览播放不占用 worker：合成在 GUI 线程。prepare 与导出才进后台。参数拖动只重新 prepare，不打断正在播放的时钟。v1 导出用 QThread（QImage 可跨线程绘制）；进程隔离留 v1.2。

**预览时钟（必须纠漂）：**

`QMediaPlayer.position()` 常见 50–100ms 才更新一次，16ms 轮询会得到一串重复 PTS 再跳变。

```text
播放开始 / seek 完成:
  t_media0 = player.position_s（或 PCM 已播字节/采样率）
  t_mono0  = time.monotonic()

每帧:
  t = t_media0 + (monotonic() - t_mono0)

每 ~500ms 用播放器 PTS（或 PCM 字节时钟）纠漂：
  若 |t - pts| > 阈值（如 80ms）则重锚 t_media0 / t_mono0

暂停 / scrub: t = 滑块值，并 seek 音频
PCM 回退路径: 主时钟用已写入 QAudioSink 的帧数，不用 QMediaPlayer
```

### 4.10 性能优化策略

| 优化点 | 手段 |
| -------- | ------ |
| 光栅化与合成分离 | 字体/描边/模糊/唱片贴图只在 prepare；每帧只 blit/rotate |
| 文本渲染缓存 | 每行紧 bbox RGBA + origin；淡入淡出/滚动只改 alpha 与位移 |
| 背景缓存 | 静态模糊只算一次；波浪用 1/4 分辨率相位图 + 平移 UV |
| 模糊降采样 | 高斯模糊先缩小 4 倍再放大，约 16× |
| 唱片旋转 | composite 内 QPainter.rotate 小贴图，禁止全帧 rotate / 手写 warp |
| 预览分辨率 | 资源按 1920×1080 一份；播放中 painter.scale；暂停可离屏满分辨率 |
| 导出管道 | **默认** QImage 紧凑 RGB buffer 直写 stdin，由 FFmpeg 原生转 BT.709 limited-range yuv420p；`bufsize ≥ 8MB` |
| 帧数对齐 | `-frames:v N` 且 `N = round(duration * fps)`，不只靠 `-shortest` |
| prepare 去重 | 参数 debounce 80ms + prep_gen，只接受最新一次 |
| 预留并行 | `eval` 无副作用；v1.2 可多进程分块后再按序写管道 |

---

## 5. 布局策略

### 5.1 主窗口布局

```text
┌──────────────────────────────────────────────────────────────┐
│ 菜单栏:  文件(F)   设置(O)   帮助(H)                           │
├────────────┬────────────────────────────────┬────────────────┤
│ ① 输入面板  │  ② 预览区 (16:9)                │ ③ 参数面板      │
│ ┌────────┐ │                                │ ┌────────────┐ │
│ │音频文件…│ │                                │ │Tab 歌词样式 │ │
│ │封面图片…│ │    PreviewSurface 实时合成      │ │Tab 动画选择 │ │
│ │LRC 歌词…│ │    (控件尺寸，最大 1080p@60)    │ │Tab 色彩    │ │
│ │背景图片…│ │                                │ │Tab 输出    │ │
│ └────────┘ │                                │ └────────────┘ │
│ 媒体信息     │                                │ [恢复默认参数]   │
├────────────┴────────────────────────────────┴────────────────┤
│ ④ 时间轴: ▶/❚❚ |——●————————歌词刻度————————————| 00:42.3/04:05.0 │
│ ⑤ 状态栏: [导出视频]  ▓▓▓▓░░░░░░ 38%   编码器: h264_nvenc      │
└──────────────────────────────────────────────────────────────┘
```

### 5.2 各区域职责与控件映射

| 区域 | 职责 | 主要控件 |
| ------ | ------ | ---------- |
| ① 输入面板 | 四类文件的选择与状态展示 | 每行 = 标签 + 路径 QLineEdit(只读) + 浏览 QPushButton；下方显示音频时长/标题艺术家/封面尺寸/LRC 行数 |
| ② 预览区 | 实时合成当前 t 的画面 | PreviewSurface（QWidget+QPainter）：16:9 居中、深色底；资源未就绪时占位；播放时跟纠漂时钟 |
| ③ 参数面板 | 全部自定义参数 | QTabWidget 四个 Tab；控件：QComboBox(字体/动画)、QSpinBox(字号/描边)、色块 QPushButton + QColorDialog、QCheckBox(自动取色)。动画 Tab 按当前 type 的 `params_schema` 动态生成 |
| ④ 时间轴 | 播放/定位 | 播放按钮 + QSlider + 自绘歌词刻度；播放中滑块跟随时钟，scrub 时 seek 音频并重锚时钟 |
| ⑤ 状态栏 | 导出与编码器状态 | 导出按钮、QProgressBar、编码器标签、菜单动作 |

固定宽度：左面板 260px、右面板 300px，中间预览区随窗口伸缩（`QSplitter` 允许用户拖动微调）。

### 5.3 交互细节

- 任一文件加载成功 → 提交 prepare；完成后刷新 QImage/QPixmap 并重绘当前 t。LRC 变化时同步重建时间轴刻度。
- 播放：空格切换播放/暂停；时钟见 4.9；`paintEvent` 由 PreciseTimer 触发。不走 Pillow。
- 拖动滑块：seek 音频 + 重锚时钟 + 立即 `eval` 重绘（不 prepare）。参数变更：80ms 防抖后 prepare，播放不中断。
- 快捷键：Ctrl+O 打开工程 / Ctrl+S 保存 / Ctrl+E 导出 / Space 播放 / Home·End 跳到首末。
- 未就绪防护：音频或 LRC 未加载时，导出与播放按钮置灰并提示缺失项。
- FLAC 等 QMediaPlayer 无法解码时，用 ffmpeg 解 PCM 喂 `QAudioSink`，时钟改用已写入采样数。
- prepare 期间预览保留上一份 assets，可叠半透明「更新中…」；过期 prep_gen 结果不得覆盖新资源。

---

## 6. 视频输出规格

| 项 | 规格 |
| ---- | ------ |
| 分辨率 | 默认 1920×1080（16:9）。schema 预留 `width`/`height`/`layout_preset`，v1 只实现横屏 1080p |
| 帧率 | **60 fps（导出底线）**；设置中可另选 30 fps 仅作低配导出 |
| 像素格式 | yuv420p（保证播放器/平台兼容）；Python 侧传紧凑 RGB，FFmpeg 原生转换 |
| 颜色 | BT.709 / tv range（写进码流元数据，避免上架发灰） |
| 视频编码 | H.264 High Profile；硬件 NVENC/AMF/QSV，回退 libx264 |
| GOP | 2 秒（60fps → `-g 120`） |
| 质量控制 | 软件编码 `-crf 17`；硬件编码 VBR 目标 12 Mbps、上限 24 Mbps |
| 音频 | AAC-LC，320 kbps，48 kHz，立体声（源采样率不同于 48k 时重采样） |
| 封装 | MP4，`+faststart`（moov 前置，利于网络播放） |
| 时长 | `N = round(duration * fps)` 帧 + `-frames:v N` + `-shortest` 双保险 |

**编码命令示例（软件兜底）：**

```bash
ffmpeg -y -hide_banner -loglevel error \
  -f rawvideo -video_size 1920x1080 -framerate 60 -pix_fmt rgb24 \
  -colorspace bt709 -color_primaries bt709 -color_trc bt709 -color_range pc -i pipe:0 \
  -i "<audio>" -map 0:v -map 1:a \
  -vf "scale=in_range=full:out_range=tv:in_color_matrix=bt709:out_color_matrix=bt709,format=yuv420p" \
  -c:v libx264 -preset medium -crf 17 -pix_fmt yuv420p \
  -colorspace bt709 -color_primaries bt709 -color_trc bt709 -color_range tv \
  -g 120 \
  -c:a aac -b:a 320k -ar 48000 \
  -frames:v <N> -shortest -movflags +faststart "<output.mp4>"
```

Python 侧不再为每帧分配 NumPy 浮点数组；统一传递紧凑 RGB，由 FFmpeg 的原生
scale/filter 路径完成 BT.709 limited-range 转换。非 4 字节对齐行距的 QImage
使用可复用的紧凑打包缓冲，默认 1920×1080 路径零拷贝。

**硬件编码视频段参数替换：**

```bash
# NVIDIA:   -c:v h264_nvenc -preset p5  -rc vbr      -cq 19 -b:v 0    -maxrate 24M -bufsize 24M
# AMD:      -c:v h264_amf   -quality quality -rc vbr_peak -b:v 12M -maxrate 24M
# Intel:    -c:v h264_qsv   -preset medium -global_quality 20
```

音频文件路径含中文/空格由 `subprocess` 列表参数传递，无转义问题；视频帧全部走 stdin 管道，不产生中间文件。`Popen(..., bufsize=8*1024*1024)`。

---

## 7. 工程文件格式（.kproj）

`.kproj` 为 UTF-8 JSON，媒体路径相对于工程文件目录保存（相对化失败则保留绝对路径，加载时依次尝试：相对 → 绝对 → 弹窗重选）。

```json
{
  "version": "1.1",
  "files": {
    "audio": "music.flac",
    "cover": "cover.jpg",
    "lrc": "lyrics.lrc",
    "background": null
  },
  "lyric_style": {
    "main_font": "",
    "main_size": 64,
    "main_color": "#FFFFFF",
    "sub_font": "",
    "sub_size": 48,
    "sub_color": "#C8C8C8",
    "stroke_color": "#101014",
    "stroke_width": 4
  },
  "animations": {
    "background": {"type": "gradient_wave", "params": {"speed": 1.0, "amp": 0.3}},
    "lyrics": {"type": "scroll_list", "params": {"lines": 5, "ease": "cubic"}},
    "cover": {"type": "disc_rotate", "params": {"rpm": 33.3}}
  },
  "colors": {
    "auto_extract": true,
    "primary": "#7FD1F5",
    "secondary": "#F5C87F",
    "stroke": "#0B0E12"
  },
  "output": {
    "fps": 60,
    "width": 1920,
    "height": 1080,
    "layout_preset": "landscape_mv",
    "encoder": "auto",
    "video_bitrate": "12M",
    "audio_bitrate": "320k",
    "show_metadata": true
  }
}
```

v1 `layout_preset` 仅实现 `landscape_mv`（封面左 / 歌词右）。schema 预留以便后续 `portrait_9_16` 等，避免再破格式。

**版本兼容策略**：读取时按 `version` 字段逐级迁移。v1.0 若 `animations` 为字符串（如 `"cover": "disc_rotate"`），升为 `{type, params:{}}`。内存中始终表示为最新模型；保存一律写当前版本号。未知字段忽略不报错（向前兼容）。

---

## 8. 自定义参数说明

### 8.1 文件输入参数

| 参数 | 类型 | 说明 |
| ------ | ------ | ------ |
| 音频文件 | 文件路径 | 支持 .mp3 / .wav / .flac / .m4a |
| 封面图片 | 文件路径 | 支持 .jpg / .jpeg / .png / .webp |
| LRC 歌词 | 文件路径 | 支持标准 LRC 格式（含双语）；词级标签预留 |
| 背景图片 | 文件路径（可选） | 未设置时自动使用封面作为背景 |

### 8.2 歌词样式参数

| 参数 | 类型 | 说明 |
| ------ | ------ | ------ |
| 主歌词字体 | 字体文件名 | 从 font/ 文件夹自动扫描 |
| 主歌词字号 | 整数 (10-300) | 像素单位；超出 lyrics_rect 时自动缩小 |
| 主歌词颜色 | 十六进制颜色 | 色块按钮 + QColorDialog |
| 次要歌词字体 | 字体文件名 | 从 font/ 文件夹自动扫描 |
| 次要歌词字号 | 整数 (10-300) | 像素单位 |
| 次要歌词颜色 | 十六进制颜色 | — |
| 描边颜色 | 十六进制颜色 | — |
| 描边宽度 | 整数 (0-20) | 像素单位，设为 0 则无描边 |

建议使用覆盖 CJK 的字体（如思源黑体）放入 `font/`。v1 不做逐字 font-fallback。

### 8.3 动画选择参数

| 参数 | 可选值 | 说明 |
| ------ | -------- | ------ |
| 背景动画 | 静态模糊 / 渐变波浪 / 波浪模糊 | 渐变波浪为纯数学生成，不依赖图片输入 |
| 歌词动画 | 淡入淡出 / 滚动列表 | 淡入淡出为单行居中，滚动列表为多行滚动高亮 |
| 封面动画 | 静态展示 / 唱片旋转 | 静态展示带柔和倒影，唱片旋转模拟黑胶唱片 |

各 type 的数值参数由 `params_schema` 生成，写入 `animations.*.params`，不在 GUI 里写死。

### 8.4 输出参数

| 参数 | 类型 | 说明 |
| ------ | ------ | ------ |
| fps | 30 / 60 | 默认 60 |
| 编码器 | auto / 具体名称 | auto 走探测链 |
| 显示元数据 | bool | 标题 − 艺术家叠到画面，默认开 |

---

## 9. 测试与发布

### 9.1 测试策略（pytest）

| 模块 | 用例 |
| ------ | ------ |
| lrc.py | 标准/多标签/双语配对（含相同时间戳）/乱序/非法行容错/`[offset:]` |
| timeline.py | bisect 当前行定位、行区间边界（首行前、最后一行后） |
| color.py | 固定种子下取色确定性、纯色封面退化、近白边框被过滤 |
| project.py | kproj 往返序列化、字符串动画 → `{type,params}` 迁移、未知字段容错 |
| encoder.py | 编码器探测（mock ffmpeg 输出）、回退链、命令含 bt709/`-frames:v` |
| scene.py | 给定 t 的 SceneState（当前行、角度、opacity）确定性 |
| prepare.py | 歌词位图为紧 bbox（宽远小于 1920）、超宽缩小/换行 |
| gui/composite.py | 离屏 QImage 关键帧金对比（允许像素容差）；无 Qt 的 CI 可 skip |

core 测试不依赖 Qt。composite 金帧单独标记，FreeType/Qt 版本差异用容差，测试字体打进仓库。

### 9.2 打包发布

- PyInstaller `--onedir` 模式（启动比 onefile 快），捆绑 font/ 与 resources/；ffmpeg 可选随包分发。
- 启动自检：PySide6 可用 → Qt Multimedia 可播放 → ffmpeg/ffprobe **存在**。硬编码列表在后台探测完成后更新状态栏。缺 ffmpeg 时预览/工程仍可用（FLAC PCM 回退除外），仅禁止导出。
- CLI：`QGuiApplication([])` + offscreen platform，走与 GUI 导出相同的 composite。

### 9.3 里程碑

| 阶段 | 内容 | 验收标准 |
| ------ | ------ | ---------- |
| M1✅ | 渲染核心 + 离屏 Qt 出片 | 命令行产出 1920×1080@60 MP4；prepare/eval 不碰 Qt；composite 只走 QPainter |
| M2✅ | GUI + 实时预览 + 纠漂时钟 | 播放时预览稳定 60fps（prepare 不在播放路径上）；scrub 即时、无 PTS 阶跃卡顿 |
| M3✅ | 参数 schema + 取色 + kproj | `{type,params}` 可往返；防抖 prepare 后即见；ID3/LRC 元数据可显示 |
| M4 | 硬件编码 + yuv 管道 + 进度/取消 + 打包 | 三家硬件编码可用，Windows 导出不因 rgb24 管道卡住，发布绿色版 |
