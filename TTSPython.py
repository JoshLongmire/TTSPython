"""TTSPython launcher: python TTSPython.py [--mini] [--toggle-dictation] ...

The application lives in the ttspython package next to this file.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _missing_dependency_hint(exc):
    name = getattr(exc, "name", "") or str(exc)
    sys.stderr.write(
        f"TTSPython could not start because a dependency is missing: {name}\n"
        "Install the requirements first:\n"
        "  Windows: dependencies.bat\n"
        "  Linux:   ./dependencies.sh\n"
        "  or:      python -m pip install -r requirements.txt\n"
    )


if __name__ == "__main__":
    try:
        from ttspython.app import main
        import PySide6  # noqa: F401
    except ImportError as exc:
        _missing_dependency_hint(exc)
        sys.exit(1)
    sys.exit(main())
