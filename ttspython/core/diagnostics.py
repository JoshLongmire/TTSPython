"""A small log of errors, on this computer only, for when something goes wrong in the packaged app.

A packaged Windows app has nowhere to print to, so without this an error in a button's code just
makes the button do nothing. Only errors are written, never what the person reads or dictates.
"""
from __future__ import annotations

import faulthandler
import logging
import logging.handlers
import os
import sys
import threading

LOG_NAME = "ttspython.log"
CRASH_NAME = "crash.log"
_MAX_BYTES = 1_000_000

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
        _crash_file = open(os.path.join(folder, CRASH_NAME), "a", encoding="utf-8")  # noqa: SIM115 (open while the app runs)
        faulthandler.enable(_crash_file)
    return _handler


def stop():
    global _handler, _crash_file, _before
    if _crash_file is not None:
        faulthandler.disable()
        _crash_file.close()
        _crash_file = None
    if _before is not None:
        sys.excepthook, threading.excepthook = _before
        _before = None
    if _handler is not None:
        _log.removeHandler(_handler)
        _handler.close()
        _handler = None
