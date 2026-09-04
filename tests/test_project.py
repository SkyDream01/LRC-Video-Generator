"""kproj 测试：往返序列化、v1.0 字符串动画迁移、未知字段容错、媒体路径相对化解析。"""

import json

import pytest

from app.core.project import (
    KProj,
    kproj_from_dict,
    load_kproj,
    resolve_media,
    save_kproj,
)


def test_round_trip(tmp_path):
    project = KProj()
    project.files.audio = "music.flac"
    project.files.cover = "cover.jpg"
    project.lyric_style.main_size = 80
    project.animations.background.type = "gradient_wave"
    project.animations.background.params = {"speed": 1.5, "amp": 0.4}
    project.output.fps = 30
    path = save_kproj(project, tmp_path / "a.kproj")

    loaded = load_kproj(path)
    assert loaded == project
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == "1.1"


def test_v10_string_anim_migration():
    data = {
        "version": "1.0",
        "files": {"audio": "a.flac"},
        "animations": {
            "background": "gradient_wave",
            "lyrics": "fade",
            "cover": "disc_rotate",
        },
    }
    project = kproj_from_dict(data)
    assert project.animations.background.type == "gradient_wave"
    assert project.animations.background.params == {}
    assert project.animations.cover.type == "disc_rotate"
    assert project.version == "1.1"  # 内存中始终最新模型


def test_unknown_fields_ignored():
    data = {
        "unknown_top": 1,
        "files": {"audio": "a.flac", "hologram": "x"},
        "output": {"fps": 60, "bit_depth": 10},
    }
    project = kproj_from_dict(data)
    assert project.files.audio == "a.flac"
    assert not hasattr(project.files, "hologram")
    assert project.output.fps == 60
    assert not hasattr(project.output, "bit_depth")


def test_missing_fields_default():
    project = kproj_from_dict({"version": "1.1"})
    assert project.output.fps == 60
    assert project.output.width == 1920
    assert project.lyric_style.main_font == ""
    assert project.lyric_style.main_size == 64
    assert project.lyric_style.main_color == "#FFFFFF"
    assert project.lyric_style.sub_font == ""
    assert project.lyric_style.sub_size == 48
    assert project.lyric_style.sub_color == "#C8C8C8"
    assert project.lyric_style.stroke_color == "#101014"
    assert project.lyric_style.stroke_width == 4


def test_invalid_json_raises(tmp_path):
    path = tmp_path / "bad.kproj"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        load_kproj(path)


def test_media_path_relativize_and_resolve(tmp_path):
    (tmp_path / "music.flac").write_bytes(b"x")
    project = KProj()
    project.files.audio = str(tmp_path / "music.flac")  # 绝对路径
    out = save_kproj(project, tmp_path / "sub" / "p.kproj")
    data = json.loads(out.read_text(encoding="utf-8"))
    # 工程在 tmp_path/sub 下，跨目录相对化失败 → 保留绝对路径
    assert data["files"]["audio"] == str(tmp_path / "music.flac")
    resolved = resolve_media(project, tmp_path / "sub", "audio")
    assert resolved is not None and resolved.name == "music.flac"


def test_resolve_media_relative_then_absolute(tmp_path):
    (tmp_path / "a.flac").write_bytes(b"x")
    project = KProj()
    project.files.audio = "a.flac"
    assert resolve_media(project, tmp_path, "audio") == (tmp_path / "a.flac").resolve()
    project.files.audio = str(tmp_path / "a.flac")
    assert resolve_media(project, tmp_path / "elsewhere", "audio") is not None
    project.files.audio = "missing.flac"
    assert resolve_media(project, tmp_path, "audio") is None
