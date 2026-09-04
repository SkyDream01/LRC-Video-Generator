# AGENTS.md — LVM (LRC Video Maker)

面向 AI 编码代理与贡献者的工程约定。设计方案唯一来源：[DESIGN.md](DESIGN.md)，README 面向使用者。

## 项目定位

音频 + LRC 双语歌词 + 封面 → 1920×1080@60fps MP4 歌词视频。GUI 用 PySide6，导出走 FFmpeg 外部进程。

## 命令

```bash
git init
pip install -r requirements.txt   # 安装依赖
pytest                            # 全部测试（core 不依赖 Qt）
pytest tests/test_lrc.py          # 单模块
pytest -m qt                      # 仅 Qt 相关用例（无 Qt 自动 skip）
python main.py demo               # M1 验收：命令行出片 1920×1080@60
pyinstaller --onedir ...          # 打包（见 DESIGN.md §9.2）
```

## 目录约定

- `app/core/` — 渲染核心。**禁止 import PySide6**（lrc/timeline/color/project/scene/prepare 必须可被 pytest 直接测）。
- `app/gui/` — PySide6。`composite.py` 是预览与导出共用的 QPainter 合成；worker 里禁止创建 QPixmap。
- `font/` — 用户字体（.ttf/.otf，启动扫描）；`ffmpeg/` — 可选随包 ffmpeg.exe；`tests/` — pytest。
- 依赖方向：GUI → controllers → core → 基础设施，单向，禁止反向 import。

## 五条不可违反的核心原则

1. **所见即所得**：预览与导出共用同一份 `prepare` 资源、`eval(t) → SceneState`、`composite(painter, state, assets)`，仅绘制目标不同。禁止为导出另写一条渲染路径。
2. **状态与像素分离**：`eval(t)` 是无副作用纯函数，不碰像素；`prepare` 仅在资源/参数变化时运行（80ms debounce + prep_gen 去重）。
3. **策略模式动画**：动画层实现 `BaseLayer`（prepare/eval/params_schema）并注册进 `ANIM_REGISTRY`；新增动画 = 1 个类 + 1 行注册，GUI 控件按 schema 自动生成，不得在 GUI 写死动画参数。
4. **参数对象化**：用户参数收敛为 dataclass 配置对象，JSON 序列化即 `.kproj`；UI 控件与配置字段一一映射。
5. **硬件自适应**：编码器 NVENC → AMF → QSV → libx264 逐级回退；启动只探测 ffmpeg 二进制存在，实编码探测放后台/首次导出，不阻塞启动。

## 关键实现红线

- 逻辑分辨率一律 1920×1080；歌词位图必须**紧 bbox** + origin 偏移，禁止按全幅画布缓存。
- 唱片旋转只在 composite 内 `QPainter.rotate` 小贴图；禁止全帧旋转、禁止手写 NumPy warp。
- 预览时钟必须纠漂（单调时钟 + 每 500ms 用音频 PTS 重锚）；禁止每帧读 raw `QMediaPlayer.position()` 或拿 QTimer 当时钟。
- `paintEvent` 内只做 eval + composite，禁止 Pillow 光栅化。
- 导出帧数 `N = round(duration*fps)`，命令带 `-frames:v N`；颜色标签写 BT.709/tv；`Popen(bufsize≥8MB)`。
- duration 优先 ffprobe，失败回退 mutagen。
- `.kproj` 读取按 version 迁移（v1.0 字符串动画 → `{type, params}`），未知字段忽略不报错。

## 测试要求

- core 层新增功能必须带 pytest 用例（lrc 解析容错、timeline bisect、color 固定种子确定性、kproj 往返与迁移、encoder mock 探测、scene/prepare 确定性）。
- composite 金帧测试用离屏 QImage，标记 `qt`，允许像素容差。
- 动画参数/schema 改动需同步 kproj 示例（DESIGN.md §7）与测试。

## 代码风格

- Python ≥ 3.10，类型注解，dataclass 优先。
- 不写无意义注释；公开模块/函数配简洁 docstring。
- 中文 UI 文案与文档，代码标识符英文。
