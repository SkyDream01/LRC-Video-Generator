# LRC Video Maker Logo

深紫色圆角底板与现有 Material 深色界面一致；唱片环与播放三角表示音频转视频，下方两条歌词线表示双语字幕。无文字标识，适合窗口、任务栏和资源管理器图标。

- `logo.png`：内置 imagegen 生成的原始 RGBA 图稿。
- `logo.ico`：由同一图稿转换为 16、24、32、48、64、128、256 像素 ICO，保留透明度；用于两个 EXE 和 Qt 应用窗口。

这些是项目设计资源；外部运行二进制（FFmpeg、7-Zip）及生成的分发包仍不入库。

生成方式：内置 imagegen，未调用 API/CLI。原始提示词：

```text
Use case: logo-brand. Create a finished Windows desktop application icon for LRC Video Maker, an audio + bilingual lyrics to video creation tool. Single centered icon only, square 1024x1024. A beautifully simple, bold geometric record ring merging with a right-pointing play triangle and two short rounded horizontal lyric strokes below, composed as one coherent memorable mark. Existing app palette: near-black plum #141218 rounded-square tile, luminous lavender #D0BCFF mark with warm white accents. Flat vector-like precision, excellent silhouette at 32 pixels, generous internal spacing, no tiny details, no letters, no words, no mockup, no shadows outside the tile. Rounded-square tile fills most of canvas, actual transparent background outside rounded corners. Save a polished production logo suitable for conversion into ICO.
```

仅进行格式与尺寸转换（需要 Pillow）：

```powershell
python -c "from PIL import Image; Image.open('assets/logo.png').save('assets/logo.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])"
```
