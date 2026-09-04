"""LVM 入口。

子命令：
- export：从 .kproj 或媒体文件渲染 MP4（离屏 Qt + ffmpeg 管道）
- demo：生成演示工程并出片（M1 验收冒烟）
- gui：启动图形界面（M2/M4 交付）
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.core.project import KProj, default_output_name, load_kproj


def _print_progress(done: int, total: int) -> None:
    percent = round(done * 100.0 / max(1, total))
    sys.stdout.write(f"\r导出中 ▓{percent:3d}% ({done}/{total} 帧)")
    sys.stdout.flush()


def _apply_overrides(project: KProj, args: argparse.Namespace) -> None:
    if args.fps is not None:
        project.output.fps = args.fps
    if args.encoder is not None:
        project.output.encoder = args.encoder


def cmd_export(args: argparse.Namespace) -> int:
    from app.gui.exporter import render_video

    if args.kproj:
        kproj_path = Path(args.kproj)
        project = load_kproj(kproj_path)
        base_dir = kproj_path.parent
    else:
        if not args.audio or not args.lrc:
            print(
                "错误：export 需要 --kproj 或同时提供 --audio 与 --lrc", file=sys.stderr
            )
            return 2
        project = KProj()
        project.files.audio = str(Path(args.audio).resolve())
        project.files.lrc = str(Path(args.lrc).resolve())
        if args.cover:
            project.files.cover = str(Path(args.cover).resolve())
        if args.background:
            project.files.background = str(Path(args.background).resolve())
        base_dir = Path.cwd()

    _apply_overrides(project, args)
    output = (
        Path(args.output)
        if args.output
        else Path(default_output_name(project.files.audio))
    )
    output.parent.mkdir(parents=True, exist_ok=True)

    result = render_video(
        project,
        base_dir,
        output,
        duration_override=args.duration,
        max_frames=args.frames,
        progress=_print_progress,
    )
    print(f"\n完成: {result.output}")
    print(
        f"  编码器 {result.encoder} · {result.frames} 帧 · {result.fps} fps · 时长 {result.duration:.2f}s"
    )
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    from app.core.demo import make_demo_project
    from app.gui.exporter import render_video

    work_dir = Path(args.dir)
    project, kproj_path = make_demo_project(work_dir)
    _apply_overrides(project, args)
    output = Path(args.output) if args.output else work_dir / "demo.mp4"
    output.parent.mkdir(parents=True, exist_ok=True)

    print(f"演示工程: {kproj_path}")
    result = render_video(
        project,
        work_dir,
        output,
        max_frames=args.frames,
        duration_override=args.duration,
        progress=_print_progress,
    )
    print(f"\n完成: {result.output}")
    print(
        f"  编码器 {result.encoder} · {result.frames} 帧 · {result.fps} fps · 时长 {result.duration:.2f}s"
    )
    return 0


def cmd_gui(_args: argparse.Namespace) -> int:
    """启动图形界面（M2：实时预览 + 纠漂时钟 + 参数面板）。"""
    from app.gui.main_window import run_gui

    return run_gui()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="LVM", description="LRC Video Maker")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--fps", type=int, choices=(30, 60), help="帧率（默认 60）")
        p.add_argument("--encoder", help="编码器（默认 auto：NVENC→AMF→QSV→libx264）")
        p.add_argument("--duration", type=float, help="覆盖时长（秒）")
        p.add_argument("--frames", type=int, help="限制导出帧数（调试用）")
        p.add_argument("--output", help="输出 MP4 路径")

    p_export = sub.add_parser("export", help="渲染工程/媒体到 MP4")
    p_export.add_argument("--kproj", help="工程文件路径")
    p_export.add_argument("--audio", help="音频文件 (.mp3/.wav/.flac/.m4a)")
    p_export.add_argument("--lrc", help="LRC 歌词文件")
    p_export.add_argument("--cover", help="封面图（可选）")
    p_export.add_argument("--background", help="背景图（可选）")
    common(p_export)
    p_export.set_defaults(func=cmd_export)

    p_demo = sub.add_parser("demo", help="生成演示工程并出片")
    p_demo.add_argument("--dir", default="output/demo", help="演示工作目录")
    common(p_demo)
    p_demo.set_defaults(func=cmd_demo)

    p_gui = sub.add_parser("gui", help="启动 GUI（M2）")
    p_gui.set_defaults(func=cmd_gui)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
