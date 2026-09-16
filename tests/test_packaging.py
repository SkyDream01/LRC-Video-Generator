"""绿色版入口的参数分派回归检查，不启动 Qt。"""

from pathlib import Path
import runpy
from types import ModuleType, SimpleNamespace

import pytest

import main as entry
from scripts import build_windows


def test_frozen_no_args_opens_gui(monkeypatch):
    monkeypatch.setattr(entry.sys, "frozen", True, raising=False)
    monkeypatch.setattr(entry, "cmd_gui", lambda args: 17)
    assert entry.main([]) == 17


def test_frozen_preserves_cli(monkeypatch):
    monkeypatch.setattr(entry.sys, "frozen", True, raising=False)
    monkeypatch.setattr(entry, "cmd_demo", lambda args: args.frames)
    assert entry.main(["demo", "--frames", "3"]) == 3


def test_windowed_entry_does_not_use_missing_stdout(monkeypatch):
    monkeypatch.setattr(entry.sys, "frozen", True, raising=False)
    monkeypatch.setattr(entry.sys, "stdout", None)
    monkeypatch.setattr(entry, "cmd_gui", lambda args: 17)
    assert entry.main(["demo"]) == 17


@pytest.mark.parametrize("with_external_tools", [False, True])
def test_spec_collects_portable_resources(tmp_path, monkeypatch, with_external_tools):
    files = ["README.md", "LICENSE", "font/.gitkeep", "font/中文.ttf",
             "resources/image.png", "docs/guide.md", "examples/demo.kproj",
             "assets/logo.png", "assets/logo.ico"]
    if with_external_tools:
        files += ["ffmpeg/ffmpeg.exe", "ffmpeg/ffprobe.exe", "ffmpeg/avcodec.dll"]
    for name in files:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    hooks = ModuleType("PyInstaller.utils.hooks")
    hooks.collect_submodules = lambda package: [package + ".core", package + ".gui"]
    monkeypatch.setitem(entry.sys.modules, "PyInstaller.utils.hooks", hooks)
    captured = {}

    def analysis(scripts, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(pure=[], scripts=scripts, binaries=[], datas=kwargs["datas"])

    def executable(*args, **kwargs):
        captured.setdefault("exes", []).append(kwargs)
        return object()

    spec = Path(entry.__file__).parent / "LRCVideoMaker.spec"
    monkeypatch.chdir(tmp_path.parent)
    runpy.run_path(str(spec), init_globals={
        "SPECPATH": str(tmp_path), "Analysis": analysis,
        "PYZ": lambda *args: None, "EXE": executable, "COLLECT": lambda *args, **kwargs: None,
    })
    collected = {Path(source).relative_to(tmp_path).as_posix(): destination
                 for source, destination in captured["datas"]}
    assert set(collected) == set(files)
    for name in files:
        assert Path(collected[name]) == Path(name).parent
    assert captured["hiddenimports"] == ["app.core", "app.gui"]
    assert [exe["console"] for exe in captured["exes"]] == [False, True]
    for exe in captured["exes"]:
        assert exe["contents_directory"] == "."
        assert exe["exclude_binaries"] is True
        assert exe["icon"] == str(tmp_path / "assets" / "logo.ico")


def test_build_sanitizes_dll_search_path(tmp_path, monkeypatch):
    (tmp_path / "requirements-build.txt").write_text("PyInstaller==6.22.2\n")
    monkeypatch.setattr(build_windows, "ROOT", tmp_path)
    monkeypatch.setattr(build_windows.sys, "platform", "win32")
    monkeypatch.setattr(build_windows.sys, "maxsize", 2**63 - 1)
    monkeypatch.setattr(build_windows.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(build_windows.platform, "python_version", lambda: "3.13.15")
    monkeypatch.setattr(build_windows, "version", lambda name: "6.22.2")
    monkeypatch.setenv("SystemRoot", str(tmp_path / "Windows"))
    monkeypatch.setenv("PATH", "unrelated-tools-with-old-dlls")
    monkeypatch.setenv("PYTHONPATH", "unrelated-python")

    def stop_before_build(command, **kwargs):
        assert "unrelated-tools" not in kwargs["env"]["PATH"]
        assert "PYTHONPATH" not in kwargs["env"]
        assert str(tmp_path / "Windows" / "System32") in kwargs["env"]["PATH"]
        assert kwargs["cwd"] == tmp_path
        assert command[-1] == str(tmp_path / "LRCVideoMaker.spec")
        raise RuntimeError("checked")

    monkeypatch.setattr(build_windows.subprocess, "run", stop_before_build)
    with pytest.raises(RuntimeError, match="checked"):
        build_windows.main([])


@pytest.mark.parametrize("module_name,has_config", [("7z.sfx", False), ("7zS.sfx", True)])
def test_sfx_composition(tmp_path, monkeypatch, module_name, has_config):
    bundle = tmp_path / "LRCVideoMaker"
    bundle.mkdir()
    module = tmp_path / module_name
    module.write_bytes(b"MZ-STUB")
    calls = []

    def archive_command(command, **kwargs):
        calls.append(command)
        if command[1] == "a":
            assert kwargs["cwd"] == tmp_path
            Path(command[-2]).write_bytes(b"7Z-ARCHIVE")

    monkeypatch.setattr(build_windows.subprocess, "run", archive_command)
    result = build_windows.create_sfx(bundle, tmp_path / "7z.exe", module)
    data = result.read_bytes()
    assert data.startswith(b"MZ-STUB") and data.endswith(b"7Z-ARCHIVE")
    assert (b"RunProgram" in data) is has_config
    assert [command[1] for command in calls] == ["a", "t"]
    assert not list(tmp_path.glob("lvm-sfx-*"))


def test_sfx_failure_preserves_previous_package(tmp_path, monkeypatch):
    bundle = tmp_path / "LRCVideoMaker"
    bundle.mkdir()
    module = tmp_path / "7z.sfx"
    module.write_bytes(b"MZ")
    previous = tmp_path / "LRCVideoMaker-Portable.exe"
    previous.write_bytes(b"previous")

    def fail(command, **kwargs):
        raise build_windows.subprocess.CalledProcessError(2, command)

    monkeypatch.setattr(build_windows.subprocess, "run", fail)
    with pytest.raises(build_windows.subprocess.CalledProcessError):
        build_windows.create_sfx(bundle, tmp_path / "7z.exe", module)
    assert previous.read_bytes() == b"previous"
    assert not list(tmp_path.glob("lvm-sfx-*"))
