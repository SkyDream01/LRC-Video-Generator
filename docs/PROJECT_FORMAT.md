# `.kproj` 工程文件格式

`.kproj` 是 UTF-8 编码的 JSON 文件。当前模型版本为 `1.1`，内存中的工程始终按最新模型表示，保存时写回当前版本号。

## 完整示例

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
    "background": {
      "type": "gradient_wave",
      "params": {"speed": 1.0, "amp": 0.3}
    },
    "lyrics": {
      "type": "scroll_list",
      "params": {"lines": 5, "ease": "cubic"}
    },
    "cover": {
      "type": "disc_rotate",
      "params": {"rpm": 33.3}
    }
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

## 顶层字段

| 字段 | 类型 | 默认/当前值 | 用途 |
| --- | --- | --- | --- |
| `version` | string | `"1.1"` | 工程格式版本；保存时强制写当前版本 |
| `files` | object | 见下表 | 媒体路径 |
| `lyric_style` | object | 见下表 | 歌词字体和绘制样式 |
| `animations` | object | 三层默认动画 | 背景、歌词、封面策略 |
| `colors` | object | 自动取色开启 | 动画主色/辅色和颜色设置 |
| `output` | object | 1920×1080 @ 60 | 输出与编码设置 |

### `files`

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `audio` | string 或 null | `null` | `.mp3`、`.wav`、`.flac`、`.m4a` |
| `cover` | string 或 null | `null` | 封面图片；缺失时不绘制封面 |
| `lrc` | string 或 null | `null` | LRC 文件；GUI 导出需要有效歌词 |
| `background` | string 或 null | `null` | 背景图片；为空时图片型背景通常使用封面 |

路径解析顺序为：先以 `.kproj` 所在目录为基准尝试相对路径，再尝试原始值作为绝对路径。建议工程和媒体一起移动；如果路径失效，可在 GUI 中重新选择媒体。

保存时程序会尝试把路径相对化到工程目录。跨磁盘或无法相对化时保留原始路径，不会强行改写。

### `lyric_style`

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `main_font` | string | `""` | `font/` 中的字体文件名；空值使用默认字体 |
| `main_size` | int | `64` | 10–300 |
| `main_color` | string | `#FFFFFF` | 主歌词颜色 |
| `sub_font` | string | `""` | 译文字体 |
| `sub_size` | int | `48` | 10–300 |
| `sub_color` | string | `#C8C8C8` | 译文颜色 |
| `stroke_color` | string | `#101014` | 文字描边颜色 |
| `stroke_width` | int | `4` | 0–20；0 表示无描边 |

超宽歌词会自动缩小字号、最多换成两行，仍超出时截断并加省略号。当前不提供逐行字体回退配置，CJK 歌词建议把覆盖中文的 `.ttf` 或 `.otf` 放入 `font/`。

### `animations`

每一层都使用统一形状：`{"type": "动画键", "params": {}}`。当前注册项和参数如下：

| 层 | `type` | 参数 |
| --- | --- | --- |
| background | `static_blur` | 无 |
| background | `gradient_wave` | `speed` 0.05–5.0；`amp` 0–1 |
| background | `wave_blur` | `speed` 0.05–5.0；`amp` 0–1 |
| lyrics | `fade` | `fade_ms` 0–2000 |
| lyrics | `scroll_list` | `lines` 1–11；`ease` 为 `linear`/`cubic` |
| cover | `static` | 无 |
| cover | `disc_rotate` | `rpm` 5–78 |

参数会按动画的 `params_schema` 收敛：未知 key 被忽略，非法值回退默认值，越界数值被钳制。切换动画类型时，GUI 会用新类型的默认参数重新填充该层。

### `colors`

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `auto_extract` | bool | `true` | 有封面时用固定种子 K-Means 提取主色/辅色 |
| `primary` | string | `#7FD1F5` | 手动模式的动画主色 |
| `secondary` | string | `#F5C87F` | 手动模式的动画辅色 |
| `stroke` | string | `#0B0E12` | 色彩设置中保存的描边备用值 |

歌词文字真正绘制时使用 `lyric_style.stroke_color`；自动取色会在该字段仍为默认值时按歌词区域对比度计算描边色。颜色字符串支持 `#RRGGBB`，解析失败时回退到白色。

### `output`

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `fps` | int | `60` | 当前 GUI/CLI 选项为 30 或 60 |
| `width` | int | `1920` | 逻辑画布宽度；导出需为偶数 |
| `height` | int | `1080` | 逻辑画布高度；导出需为偶数 |
| `layout_preset` | string | `landscape_mv` | 当前只实现封面左、歌词右的布局 |
| `encoder` | string | `auto` | `auto` 或具体编码器名 |
| `video_bitrate` | string | `12M` | AMF 硬件路径使用的目标视频码率 |
| `audio_bitrate` | string | `320k` | FFmpeg AAC 音频码率参数 |
| `show_metadata` | bool | `true` | 叠加 `标题 − 艺术家` 元数据条 |

工程中的宽高字段可手动编辑，但 GUI 当前没有对应控件，布局预设也只有 `landscape_mv`。奇数宽高会在导出时因 `yuv420p` 要求被拒绝。

## 版本与容错

读取工程时遵循以下规则：

1. v1.0 中动画层可以直接写字符串，例如 `"cover": "disc_rotate"`；读取时会迁移成 `{"type": "disc_rotate", "params": {}}`。
2. 读取后的内存模型总是 v1.1；再次保存会写 `"version": "1.1"`。
3. 缺失字段使用 dataclass 默认值；未知顶层字段和未知子字段会忽略。
4. `params` 不是对象、参数类型错误或超出 schema 范围时，按对应动画默认值处理。
5. JSON 语法损坏会抛出“kproj 文件损坏”错误，GUI 会在打开工程时提示。

这套策略允许旧工程继续打开，也避免手动添加未知字段导致整个工程无法加载。

## 手动编辑建议

- 使用 UTF-8 保存，保留合法 JSON 逗号和引号。
- 动画参数应放在对应的 `animations.<layer>.params` 中，不要把参数平铺到层对象。
- 修改媒体路径后，优先在 GUI 打开工程并重新保存，让路径重新相对化。
- 修改后先用 `python main.py export --kproj ... --frames 1` 做快速检查；正式导出前删除 `--frames`。
