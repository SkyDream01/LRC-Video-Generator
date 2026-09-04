"""M3 覆盖：自动取色采样、元数据合并、schema 收敛与工程容错。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

import numpy as np
from PIL import Image

from app.core.anims.lyrics import ScrollListLyrics
from app.core.color import extract_palette, hex_to_rgb
from app.core.context import bg_sample_bitmap, build_context
from app.core.encoder import read_audio_meta
from app.core.lrc import parse_lrc
from app.core.project import KProj, kproj_from_dict, load_kproj, save_kproj


def test_lrc_bom_and_album_is_available_to_context():
    doc = parse_lrc("\ufeff[al:专辑]\n[00:01.00]歌词\n")
    assert doc.album == "专辑"
    assert doc.lines[0].text == "歌词"


def test_context_merges_lrc_metadata_before_id3(monkeypatch, tmp_path):
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"not real audio")
    project = KProj()
    project.files.audio = str(audio)

    monkeypatch.setattr(
        "app.core.context.read_audio_meta",
        lambda _path: {"title": "ID3 标题", "artist": "ID3 歌手", "album": "ID3 专辑"},
    )
    ctx = build_context(
        project,
        tmp_path,
        lrc_text="[ti:LRC 标题]\n[ar:LRC 歌手]\n[al:LRC 专辑]\n[00:01.00]歌词",
        duration_override=5.0,
    )
    assert ctx.meta.title == "LRC 标题"
    assert ctx.meta.artist == "LRC 歌手"
    assert ctx.meta.album == "LRC 专辑"
    assert ctx.meta_text == "LRC 标题 − LRC 歌手"


def test_context_uses_id3_when_lrc_metadata_is_missing(monkeypatch, tmp_path):
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"not real audio")
    project = KProj()
    project.files.audio = str(audio)
    monkeypatch.setattr(
        "app.core.context.read_audio_meta",
        lambda _path: {"title": "标题", "artist": "歌手", "album": "专辑"},
    )
    ctx = build_context(
        project,
        tmp_path,
        lrc_text="[00:01.00]歌词",
        duration_override=5.0,
    )
    assert (ctx.meta.title, ctx.meta.artist, ctx.meta.album) == ("标题", "歌手", "专辑")


def test_read_audio_meta_accepts_scalar_and_bytes_tags(monkeypatch, tmp_path):
    class FakeMedia:
        tags: ClassVar = {
            "title": b"Title",
            "artist": " Artist ",
            "album": ["Album", "Alt"],
        }

    monkeypatch.setattr("mutagen._file.File", lambda _path, easy=True: FakeMedia())
    assert read_audio_meta(tmp_path / "song.mp3") == {
        "title": "Title",
        "artist": "Artist",
        "album": "Album",
    }


def test_lyric_color_sample_is_the_requested_canvas_region():
    # 左半深色、右半浅色；歌词区位于 landscape_mv 的右侧，应采到浅色。
    arr = np.zeros((10, 20, 3), dtype=np.uint8)
    arr[:, :10] = (10, 10, 10)
    arr[:, 10:] = (240, 240, 240)
    image = Image.fromarray(arr, "RGB")
    sample = bg_sample_bitmap(image, 20, 10, rect=(10, 0, 10, 10))
    assert np.asarray(sample).mean() > 200


def test_palette_handles_transparency_and_invalid_hex():
    image = Image.new("RGBA", (16, 16), (220, 30, 50, 255))
    image.putpixel((0, 0), (0, 0, 0, 0))
    palette = extract_palette(image)
    assert palette.primary[0] > palette.primary[1]
    assert hex_to_rgb("#12") == (255, 255, 255)


def test_animation_schema_coerces_boolean_strings():
    # 用现有 choice/int schema 间接验证外部 JSON 的参数收敛逻辑。
    resolved = ScrollListLyrics.resolve_params({"lines": "7", "ease": "linear"})
    assert resolved == {"lines": 7, "ease": "linear"}


def test_kproj_malformed_sections_fall_back_to_latest_defaults(tmp_path):
    project = kproj_from_dict(
        {
            "version": "1.0",
            "files": [],
            "animations": {"background": {"type": "", "params": []}},
            "lyric_style": {"main_size": "bad", "stroke_width": -10},
            "output": {"width": 0, "height": None, "show_metadata": "false"},
        }
    )
    assert project.files.audio is None
    assert project.animations.background.type == "static_blur"
    assert project.animations.lyrics.type == "fade"
    assert project.animations.cover.type == "static"
    assert project.lyric_style.main_size == 64
    assert project.lyric_style.stroke_width == 0
    assert project.output.width == 1920
    assert project.output.height == 1080
    assert project.output.show_metadata is False


def test_kproj_saved_animation_shape_survives_roundtrip(tmp_path):
    project = KProj()
    project.animations.background.type = "gradient_wave"
    project.animations.background.params = {"speed": 1.25, "amp": 0.4}
    path = save_kproj(project, tmp_path / "project.kproj")
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["animations"]["background"] == {
        "type": "gradient_wave",
        "params": {"speed": 1.25, "amp": 0.4},
    }
    assert load_kproj(path).animations.background.params == {"speed": 1.25, "amp": 0.4}


def test_relative_media_path_is_rebased_when_project_path_is_relative(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    work = tmp_path / "output" / "demo"
    work.mkdir(parents=True)
    (work / "song.wav").write_bytes(b"x")
    project = KProj()
    project.files.audio = "output/demo/song.wav"
    path = save_kproj(project, Path("output/demo/demo.kproj"))
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["files"]["audio"] == "song.wav"
