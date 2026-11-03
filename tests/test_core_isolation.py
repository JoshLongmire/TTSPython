import os
import pkgutil
import subprocess
import sys

import ttspython.core

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_core_imports_without_qt():
    modules = ["ttspython.core." + m.name for m in pkgutil.walk_packages(ttspython.core.__path__, "")]
    code = (
        "import sys, importlib\n"
        f"for name in {modules!r}:\n"
        "    importlib.import_module(name)\n"
        "bad = [m for m in sys.modules if m.startswith(('PySide6', 'shiboken6'))]\n"
        "print('QT' if bad else 'CLEAN')\n"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "CLEAN"
