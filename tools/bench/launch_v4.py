"""Benchmark launcher for the v4.x tkinter app.

Usage: python launch_v4.py --src <extracted v4 folder> --mode startup|ttfa

Prints READY once the main window is mapped and painted. In ttfa mode it then
waits for a line on stdin, prints SPEAK <time_ns> and calls the Speak All handler.
"""
import argparse
import importlib.util
import os
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", required=True)
    parser.add_argument("--mode", default="startup", choices=["startup", "ttfa"])
    parser.add_argument("--text", default="Hello there. This is a quick speech test.")
    args = parser.parse_args()

    sys.path.insert(0, args.src)
    os.chdir(args.src)
    import tkinter as tk

    spec = importlib.util.spec_from_file_location("v4app", os.path.join(args.src, "TTSPython.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    root = tk.Tk()
    app = mod.ReaderApp(root)
    root.minsize(700, 400)
    # wait_visibility() can hang on Windows if the window is already mapped.
    while not root.winfo_viewable():
        root.update()
        time.sleep(0.005)
    root.update()
    print("READY", flush=True)

    if args.mode == "ttfa":
        sys.stdin.readline()
        app.txt.delete("1.0", "end")
        app.txt.insert("1.0", args.text)
        print("SPEAK", time.time_ns(), flush=True)
        app.on_speak()
        root.after(5000, root.destroy)
    root.mainloop()


if __name__ == "__main__":
    main()
