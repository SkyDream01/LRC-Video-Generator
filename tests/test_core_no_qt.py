"""core 层零 Qt 依赖守护：导入全部 core 模块后 sys.modules 不得出现 PySide6。"""

import subprocess
import sys


def test_core_imports_clean_without_pyside6():
    code = (
        "import importlib, pkgutil, sys\n"
        "import app.core\n"
        "for m in pkgutil.walk_packages(app.core.__path__, 'app.core.'):\n"
        "    importlib.import_module(m.name)\n"
        "leaked = sorted(x for x in sys.modules if x == 'PySide6' or x.startswith('PySide6.'))\n"
        "assert not leaked, leaked\n"
        "print('core-clean')\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "core-clean" in proc.stdout


def test_core_sources_do_not_import_pyside6():
    """AST 级扫描：core 源码不得出现 PySide6 的 import 语句（文档字符串提及不算）。"""
    import ast
    from pathlib import Path

    core_dir = Path(__file__).resolve().parents[1] / "app" / "core"
    offenders = []
    for path in core_dir.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(name == "PySide6" or name.startswith("PySide6.") for name in names):
                offenders.append(str(path.relative_to(core_dir)))
    assert offenders == []
