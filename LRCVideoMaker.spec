"""Windows onedir；路径以 spec 所在目录为准，不依赖调用者工作目录。"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH)
datas = [(str(root / name), ".") for name in ("README.md", "LICENSE")]
for name in ("font", "assets", "resources", "docs", "examples", "ffmpeg"):
    folder = root / name
    if folder.is_dir():
        for path in sorted(folder.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                # 外部工具原样复制，不让 PyInstaller 改写或扫描其依赖。
                datas.append((str(path), str(path.parent.relative_to(root))))

a = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    binaries=[],
    datas=datas,
    hiddenimports=collect_submodules("app"),
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
gui = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="LRCVideoMaker",
    console=False,
    icon=str(root / "assets" / "logo.ico"),
    contents_directory=".",
    strip=False,
    upx=False,
)
cli = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="LRCVideoMaker-CLI",
    console=True,
    icon=str(root / "assets" / "logo.ico"),
    contents_directory=".",
    strip=False,
    upx=False,
)
coll = COLLECT(
    gui, cli, a.binaries, a.datas,
    strip=False,
    upx=False,
    name="LRCVideoMaker",
)
