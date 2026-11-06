"""A small log of errors, on this computer only, for when something goes wrong in the packaged app.

A packaged Windows app has nowhere to print to, so without this an error in a button's code just
makes the button do nothing. Only errors are written, never what the person reads or dictates.
"""
from __future__ import annotations

import atexit
import faulthandler
import logging
import logging.handlers
import os
import re
import sys
import threading

LOG_NAME = "ttspython.log"
CRASH_NAME = "crash.log"
_MAX_BYTES = 1_000_000
_MAX_CRASH_BYTES = 256_000
# Python's crash handler also writes down errors that Windows raises and something then handles: a COM call
# made at a bad moment, each time a screen reader or other UI Automation client asks the window something
# (0x8001010d). Real crashes have the error severity (0xC...) and are named. These are not crashes.
_REPORT_START = re.compile(r"^(?=Windows fatal exception:|Fatal Python error:)", re.M)
_NOT_A_CRASH = re.compile(r"^Windows fatal exception: code 0x[89ab]", re.I)

_log = logging.getLogger("ttspython")
_handler = None
_crash_file = None
_before = None


def _uncaught(kind, value, trace):
    _log.error("Uncaught error", exc_info=(kind, value, trace))
    if _before and _before[0] is not None:
        _before[0](kind, value, trace)


def _uncaught_in_thread(args):
    if args.exc_type is SystemExit:
        return
    _log.error("Uncaught error on thread %s", getattr(args.thread, "name", "?"),
               exc_info=(args.exc_type, args.exc_value, args.exc_traceback))


def tidy_crash_log(path):
    """Keep only real crashes, the newest ones, and no file at all if there are none."""
    try:
        with open(path, encoding="utf-8", errors="replace", newline="") as f:
            text = f.read()
        reports = [r for r in _REPORT_START.split(text) if r.strip() and not _NOT_A_CRASH.match(r)]
        kept = "".join(reports)[-_MAX_CRASH_BYTES:]
        if not kept:
            os.remove(path)
        elif kept != text:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(kept)
    except OSError:
        pass  # only tidying


def start(folder, crashes=True):
    """Start writing errors to folder. Returns the log handler. crashes: also where a crash of
    Python itself happened."""
    global _handler, _crash_file, _before
    os.makedirs(folder, mode=0o700, exist_ok=True)
    _handler = logging.handlers.RotatingFileHandler(os.path.join(folder, LOG_NAME), maxBytes=_MAX_BYTES,
                                                    backupCount=1, encoding="utf-8")
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    _handler.setLevel(logging.WARNING)
    _log.addHandler(_handler)
    _before = (sys.excepthook, threading.excepthook)
    sys.excepthook = _uncaught
    threading.excepthook = _uncaught_in_thread
    if crashes:
        path = os.path.join(folder, CRASH_NAME)
        tidy_crash_log(path)
        _crash_file = open(path, "a", encoding="utf-8")  # noqa: SIM115 (open while the app runs)
        faulthandler.enable(_crash_file)
        atexit.register(stop)
    return _handler


def stop():
    global _handler, _crash_file, _before
    if _crash_file is not None:
        faulthandler.disable()
        path = _crash_file.name
        _crash_file.close()
        _crash_file = None
        tidy_crash_log(path)
    if _before is not None:
        sys.excepthook, threading.excepthook = _before
        _before = None
    if _handler is not None:
        _log.removeHandler(_handler)
        _handler.close()
        _handler = None
