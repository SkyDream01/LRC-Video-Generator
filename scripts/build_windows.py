"""使用当前 Python 构建 Windows 绿色版并记录版本与文件摘要。"""

from __future__ import annotations

import argparse
import hashlib
from importlib.metadata import version
import json
import os
import platform
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    """分块读取文件，返回 SHA-256 摘要。"""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def resolve_sfx_tools(seven_zip: str | None, module: Path | None) -> tuple[Path, Path]:
    """检查 SFX 工具，普通解压模块和安装模块不混用配置。"""
    executable = seven_zip or shutil.which("7z")
    if not executable or not Path(executable).is_file():
        raise SystemExit("找不到 7z.exe；请安装 7-Zip 或使用 --seven-zip 指定完整路径。")
    executable = Path(executable).resolve()
    module = (module or executable.parent / "7z.sfx").resolve()
    if not module.is_file() or module.name.lower() not in {"7z.sfx", "7zs.sfx", "7zsd.sfx"}:
        raise SystemExit("请提供 7z.sfx（绿色解压）或 7zS.sfx/7zSD.sfx（临时解压并运行）。")
    return executable, module


def create_sfx(bundle: Path, seven_zip: Path, module: Path) -> Path:
    """在临时目录生成全新归档，检查后原子替换自解压包。"""
    output = bundle.parent / f"{bundle.name}-Portable.exe"
    with tempfile.TemporaryDirectory(prefix="lvm-sfx-", dir=bundle.parent) as temporary:
        work = Path(temporary)
        archive = work / "payload.7z"
        subprocess.run([str(seven_zip), "a", "-t7z", "-mx=5", "-y", str(archive), bundle.name],
                       cwd=bundle.parent, check=True)
        subprocess.run([str(seven_zip), "t", str(archive)], check=True)
        result = work / output.name
        with result.open("wb") as target:
            with module.open("rb") as source:
                shutil.copyfileobj(source, target)
            if module.name.lower() != "7z.sfx":
                config = (';!@Install@!UTF-8!\nTitle="LRC Video Maker"\n'
                          'BeginPrompt="解压并运行 LRC Video Maker？"\n'
                          f'RunProgram="{bundle.name}\\\\LRCVideoMaker.exe"\n'
                          ';!@InstallEnd@!\n')
                target.write(config.encode("utf-8"))
            with archive.open("rb") as source:
                shutil.copyfileobj(source, target)
        result.replace(output)
    return output


def main(argv: list[str] | None = None) -> int:
    """检查固定构建环境，执行 onedir 构建，保存可追溯清单。"""
    parser = argparse.ArgumentParser(description="构建 LRC Video Maker 绿色版、ZIP 与可选 SFX")
    parser.add_argument("--sfx", action="store_true", help="额外生成 7-Zip 自解压包")
    parser.add_argument("--seven-zip", help="7z.exe 的完整路径，默认搜索 PATH")
    parser.add_argument("--sfx-module", type=Path, help="SFX 模块路径，默认 7z.exe 旁的 7z.sfx")
    args = parser.parse_args(argv)
    if not args.sfx and (args.seven_zip or args.sfx_module):
        parser.error("--seven-zip/--sfx-module 需要与 --sfx 一起使用")
    sfx_tools = resolve_sfx_tools(args.seven_zip, args.sfx_module) if args.sfx else None
    if sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64"):
        raise SystemExit("请使用 Windows x64 构建。")
    if platform.python_version() != "3.13.15" or sys.maxsize <= 2**32:
        raise SystemExit("构建基线需要 CPython 3.13.15 x64。")
    packages = {}
    for line in (ROOT / "requirements-build.txt").read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        name, expected = line.split("==")
        installed = version(name)
        if installed != expected:
            raise SystemExit(f"{name}: 需要 {expected}，当前 {installed}；请安装 requirements-build.txt")
        packages[name] = installed
    # 防止开发机 PATH 中其他工具的旧 CRT/Qt DLL 被依赖扫描误收集。
    env = os.environ.copy()
    windows = Path(os.environ["SystemRoot"])
    env["PATH"] = os.pathsep.join(map(str, (
        Path(sys.executable).parent, Path(sys.base_prefix), windows / "System32", windows,
    )))
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm",
         "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build"),
         str(ROOT / "LRCVideoMaker.spec")],
        cwd=ROOT, env=env, check=True,
    )
    bundle = ROOT / "dist" / "LRCVideoMaker"
    hashes = {
        path.relative_to(bundle).as_posix(): sha256(path)
        for path in sorted(bundle.rglob("*")) if path.is_file()
    }
    manifest = {"python": platform.python_version(), "platform": platform.platform(),
                "packages": packages, "sha256": hashes}
    (bundle / "build-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(f"绿色版已生成：{bundle}")
    archive = shutil.make_archive(str(bundle.parent / f"{bundle.name}-Portable"),
                                  "zip", root_dir=bundle.parent, base_dir=bundle.name)
    print(f"ZIP 已生成：{archive}")
    if sfx_tools:
        print(f"自解压包已生成：{create_sfx(bundle, *sfx_tools)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
