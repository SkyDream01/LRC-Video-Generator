"""KProj 工程模型：dataclass 配置对象 + JSON 读写 + 版本迁移。

`.kproj` 为 UTF-8 JSON；内存中始终表示为最新模型（v1.1），保存一律写当前版本号。
未知字段忽略不报错（向前兼容）；缺失字段取默认值。
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

KPROJ_VERSION = "1.1"
CURRENT_VERSION = KPROJ_VERSION

# 歌词默认色（context 检测「用户未改过」时用于自动对比度选色）
DEFAULT_MAIN_COLOR = "#FFFFFF"
DEFAULT_STROKE_COLOR = "#101014"

# 支持的媒体扩展名
AUDIO_EXTS = (".mp3", ".wav", ".flac", ".m4a")
COVER_EXTS = (".jpg", ".jpeg", ".png", ".webp")
FONT_EXTS = (".ttf", ".otf")


@dataclass
class FilesSpec:
    """媒体文件路径（保存时相对化到工程目录，加载时依次尝试：相对 → 绝对）。"""

    audio: str | None = None
    cover: str | None = None
    lrc: str | None = None
    background: str | None = None


@dataclass
class LyricStyle:
    """歌词样式参数。"""

    main_font: str = ""
    main_size: int = 64
    main_color: str = DEFAULT_MAIN_COLOR
    sub_font: str = ""
    sub_size: int = 48
    sub_color: str = "#C8C8C8"
    stroke_color: str = DEFAULT_STROKE_COLOR
    stroke_width: int = 4


@dataclass
class AnimSpec:
    """动画规格：type + params（GUI 按 params_schema 生成控件）。"""

    type: str
    params: dict = field(default_factory=dict)


@dataclass
class Animations:
    """三层动画配置。"""

    background: AnimSpec = field(default_factory=lambda: AnimSpec(type="static_blur"))
    lyrics: AnimSpec = field(default_factory=lambda: AnimSpec(type="fade"))
    cover: AnimSpec = field(default_factory=lambda: AnimSpec(type="static"))


@dataclass
class ColorsSpec:
    """取色配置。"""

    auto_extract: bool = True
    primary: str = "#7FD1F5"
    secondary: str = "#F5C87F"
    stroke: str = "#0B0E12"


@dataclass
class OutputSpec:
    """输出参数。"""

    fps: int = 60
    width: int = 1920
    height: int = 1080
    layout_preset: str = "landscape_mv"
    encoder: str = "auto"
    video_bitrate: str = "12M"
    audio_bitrate: str = "320k"
    show_metadata: bool = True


@dataclass
class KProj:
    """工程根对象。"""

    files: FilesSpec = field(default_factory=FilesSpec)
    lyric_style: LyricStyle = field(default_factory=LyricStyle)
    animations: Animations = field(default_factory=Animations)
    colors: ColorsSpec = field(default_factory=ColorsSpec)
    output: OutputSpec = field(default_factory=OutputSpec)
    version: str = CURRENT_VERSION


# ---------------------------------------------------------------- 序列化


def _build_dataclass(cls, data: dict):
    """按 dataclass 字段从 dict 构建实例：缺失取默认，未知忽略。"""
    if not isinstance(data, dict):
        data = {}
    kwargs = {}
    for f in fields(cls):
        if f.name in data:
            kwargs[f.name] = data[f.name]
    return cls(**kwargs)


def _mapping(value) -> dict:
    return value if isinstance(value, dict) else {}


def _string(value, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _optional_path(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and math.isfinite(value):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return default


def _int(value, default: int, minimum: int | None = None) -> int:
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    result = round(number)
    return max(minimum, result) if minimum is not None else result


def _int_or_default(value, default: int, minimum: int) -> int:
    """整数参数低于结构要求时回退默认值（用于画布/帧率）。"""
    result = _int(value, default)
    return result if result >= minimum else default


def _parse_anim_spec(data, default_type: str) -> AnimSpec:
    """动画规格解析：兼容 v1.0 纯字符串（迁移为 {type, params:{}}）。"""
    if isinstance(data, str):
        return AnimSpec(type=data.strip() or default_type, params={})
    if isinstance(data, dict):
        raw_type = data.get("type", default_type)
        type_name = raw_type.strip() if isinstance(raw_type, str) else default_type
        type_name = type_name or default_type
        params = data.get("params")
        return AnimSpec(
            type=type_name, params=dict(params) if isinstance(params, dict) else {}
        )
    return AnimSpec(type=default_type, params={})


def kproj_from_dict(data: dict) -> KProj:
    """dict → KProj。执行 v1.0 → v1.1 迁移；未知字段忽略；非法结构回退默认值。"""
    if not isinstance(data, dict):
        return KProj()

    files_raw = _mapping(data.get("files"))
    files = FilesSpec(
        audio=_optional_path(files_raw.get("audio")),
        cover=_optional_path(files_raw.get("cover")),
        lrc=_optional_path(files_raw.get("lrc")),
        background=_optional_path(files_raw.get("background")),
    )

    style_raw = _mapping(data.get("lyric_style"))
    style_default = LyricStyle()
    lyric_style = LyricStyle(
        main_font=_string(style_raw.get("main_font"), style_default.main_font),
        main_size=_int(style_raw.get("main_size"), style_default.main_size, 10),
        main_color=_string(style_raw.get("main_color"), style_default.main_color),
        sub_font=_string(style_raw.get("sub_font"), style_default.sub_font),
        sub_size=_int(style_raw.get("sub_size"), style_default.sub_size, 10),
        sub_color=_string(style_raw.get("sub_color"), style_default.sub_color),
        stroke_color=_string(
            style_raw.get("stroke_color"), style_default.stroke_color
        ),
        stroke_width=_int(
            style_raw.get("stroke_width"), style_default.stroke_width, 0
        ),
    )

    colors_raw = _mapping(data.get("colors"))
    colors_default = ColorsSpec()
    colors = ColorsSpec(
        auto_extract=_bool(
            colors_raw.get("auto_extract"), colors_default.auto_extract
        ),
        primary=_string(colors_raw.get("primary"), colors_default.primary),
        secondary=_string(colors_raw.get("secondary"), colors_default.secondary),
        stroke=_string(colors_raw.get("stroke"), colors_default.stroke),
    )

    output_raw = _mapping(data.get("output"))
    output_default = OutputSpec()
    output = OutputSpec(
        fps=_int_or_default(output_raw.get("fps"), output_default.fps, 1),
        width=_int_or_default(output_raw.get("width"), output_default.width, 2),
        height=_int_or_default(output_raw.get("height"), output_default.height, 2),
        layout_preset=_string(
            output_raw.get("layout_preset"), output_default.layout_preset
        ),
        encoder=_string(output_raw.get("encoder"), output_default.encoder),
        video_bitrate=_string(
            output_raw.get("video_bitrate"), output_default.video_bitrate
        ),
        audio_bitrate=_string(
            output_raw.get("audio_bitrate"), output_default.audio_bitrate
        ),
        show_metadata=_bool(
            output_raw.get("show_metadata"), output_default.show_metadata
        ),
    )

    anims_raw = _mapping(data.get("animations"))
    animations = Animations(
        background=_parse_anim_spec(anims_raw.get("background"), "static_blur"),
        lyrics=_parse_anim_spec(anims_raw.get("lyrics"), "fade"),
        cover=_parse_anim_spec(anims_raw.get("cover"), "static"),
    )

    return KProj(
        files=files,
        lyric_style=lyric_style,
        animations=animations,
        colors=colors,
        output=output,
        version=CURRENT_VERSION,  # 内存中始终是最新模型
    )


def kproj_to_dict(proj: KProj) -> dict:
    """KProj → 可 JSON 序列化的 dict（写当前版本号）。"""
    d = asdict(proj)
    d["version"] = CURRENT_VERSION
    return d


# ---------------------------------------------------------------- 文件读写


def save_kproj(proj: KProj, path: str | Path) -> Path:
    """保存 .kproj：媒体路径相对化到工程目录（失败保留原样）。"""
    out = Path(path)
    data = kproj_to_dict(proj)
    base = out.parent
    files = data.get("files") or {}
    for key, value in list(files.items()):
        if value:
            files[key] = _relativize(value, base)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def load_kproj(path: str | Path) -> KProj:
    """加载 .kproj：JSON 解析失败抛 ValueError；版本迁移在 kproj_from_dict 内完成。"""
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"kproj 文件损坏（JSON 解析失败）: {p}") from exc
    return kproj_from_dict(data)


def resolve_media(proj: KProj, base_dir: str | Path, key: str) -> Path | None:
    """按「相对 → 绝对」顺序解析媒体路径，找不到返回 None。"""
    rel = getattr(proj.files, key, None)
    if not rel:
        return None
    base = Path(base_dir)
    candidate = (base / rel).resolve()
    if candidate.exists():
        return candidate
    absolute = Path(rel)
    if absolute.exists():
        return absolute
    return None


# ---------------------------------------------------------------- 工具


def _relativize(path_str: str, base: Path) -> str:
    """尝试把路径相对化到 base；跨盘/失败保留原样。"""
    try:
        p = Path(path_str)
        # 相对输入也要处理：CLI demo 使用相对工作目录生成媒体路径时，
        # 否则会把 ``output/demo/demo.wav`` 原样写进同目录工程，加载后
        # 变成 ``output/demo/output/demo/demo.wav``。
        return str(p.relative_to(base))
    except ValueError:
        return path_str


def scan_fonts(font_dir: str | Path) -> list[str]:
    """扫描 font/ 目录下的 .ttf/.otf 文件名（排序保证确定性）。"""
    d = Path(font_dir)
    if not d.is_dir():
        return []
    return sorted(
        p.name for p in d.iterdir() if p.suffix.lower() in FONT_EXTS and p.is_file()
    )


def guess_stream_title(title: str | None, artist: str | None) -> str:
    """合成「标题 − 艺术家」元数据条文本。"""
    parts = [p for p in (title, artist) if p]
    return " − ".join(parts) if parts else ""


def is_audio(path: Path) -> bool:
    return path.suffix.lower() in AUDIO_EXTS


def is_cover(path: Path) -> bool:
    return path.suffix.lower() in COVER_EXTS


def ensure_dir(path: str | Path) -> Path:
    d = Path(path)
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_output_name(audio_path: str | Path | None, suffix: str = ".mp4") -> str:
    """根据音频文件名生成默认输出名。"""
    if audio_path:
        stem = Path(audio_path).stem or "output"
    else:
        stem = "output"
    return os.fspath(Path(f"{stem}{suffix}"))
