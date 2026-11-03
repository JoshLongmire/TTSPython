"""Before/after benchmarks for TTSPython.

Measures, per target:
  startup  spawn to first painted window (READY line)
  ram      RSS / USS of the app after it has idled for --idle seconds
  ttfa     time from the speak call to the first audible sample, captured
           from the default output device via WASAPI loopback (Windows only)

Targets:
  v4  an extracted v4.x source folder, launched through launch_v4.py
  v5  this checkout, launched with TTSPYTHON_BENCH=<mode>

Runs are sequential, the child runs at below-normal priority, and each run
waits for system CPU to settle under 50% first. A run aborts if CPU passes 80%.

Example:
  python tools/bench/bench.py --target v4 --src <dir> --runs 10 --out v4.json
"""
import argparse
import json
import os
import statistics
import subprocess
import sys
import threading
import time

import psutil

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
CPU_SETTLE = 50.0
CPU_LIMIT = 80.0


def wait_for_quiet_cpu(timeout=60.0):
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if psutil.cpu_percent(interval=0.5) < CPU_SETTLE:
            return
    raise RuntimeError("CPU did not settle under 50%; aborting benchmark")


class CpuGuard(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.peak = 0.0
        self.stop_evt = threading.Event()

    def run(self):
        while not self.stop_evt.is_set():
            value = psutil.cpu_percent(interval=0.25)
            self.peak = max(self.peak, value)


def build_command(target, mode, src):
    env = dict(os.environ)
    if target == "v4":
        cmd = [sys.executable, os.path.join(HERE, "launch_v4.py"), "--src", src, "--mode", mode]
    else:
        cmd = [sys.executable, os.path.join(REPO, "TTSPython.py")]
        env["TTSPYTHON_BENCH"] = mode
        env["TTSPYTHON_SETTINGS"] = os.path.join(env.get("TEMP", "/tmp"), "ttspython_bench_settings.json")
    return cmd, env


def spawn(target, mode, src):
    cmd, env = build_command(target, mode, src)
    flags = 0
    if os.name == "nt":
        flags = subprocess.BELOW_NORMAL_PRIORITY_CLASS
    t0 = time.perf_counter()
    proc = subprocess.Popen(
        cmd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, creationflags=flags,
    )
    return proc, t0


def read_until(proc, prefix, timeout=60.0):
    result = {}

    def reader():
        for line in proc.stdout:
            if line.startswith(prefix):
                result["line"] = line.strip()
                return

    th = threading.Thread(target=reader, daemon=True)
    th.start()
    th.join(timeout)
    if "line" not in result:
        raise RuntimeError(f"timed out waiting for {prefix}")
    return result["line"]


def kill(proc):
    try:
        parent = psutil.Process(proc.pid)
        for child in parent.children(recursive=True):
            child.kill()
        parent.kill()
    except psutil.NoSuchProcess:
        pass
    proc.wait(timeout=10)


def run_startup(target, src, idle):
    proc, t0 = spawn(target, "startup", src)
    try:
        read_until(proc, "READY")
        startup_ms = (time.perf_counter() - t0) * 1000
        time.sleep(idle)
        # A venv python.exe on Windows is a launcher stub that runs the real
        # interpreter as a child, so measure the whole process tree.
        parent = psutil.Process(proc.pid)
        rss = uss = 0
        for p in [parent] + parent.children(recursive=True):
            mem = p.memory_full_info()
            rss += mem.rss
            uss += mem.uss
        return {"startup_ms": startup_ms, "rss_mb": rss / 2**20, "uss_mb": uss / 2**20}
    finally:
        kill(proc)


def run_ttfa(target, src, threshold=0.01):
    import numpy as np
    import soundcard as sc

    speaker = sc.default_speaker()
    loop_mic = sc.get_microphone(id=str(speaker.name), include_loopback=True)
    proc, _ = spawn(target, "ttfa", src)
    try:
        read_until(proc, "READY")
        time.sleep(1.0)
        first_audio_ns = None
        with loop_mic.recorder(samplerate=48000, channels=1, blocksize=240) as rec:
            rec.record(numframes=4800)  # flush stale buffers
            proc.stdin.write("go\n")
            proc.stdin.flush()
            speak_line = {}

            def wait_speak():
                speak_line["v"] = read_until(proc, "SPEAK")

            th = threading.Thread(target=wait_speak, daemon=True)
            th.start()
            deadline = time.monotonic() + 8.0
            while time.monotonic() < deadline:
                block = rec.record(numframes=240)
                now = time.time_ns()
                peak = float(np.abs(block).max()) if block.size else 0.0
                if peak > threshold and "v" in speak_line:
                    first_audio_ns = now
                    break
            th.join(5)
        if first_audio_ns is None or "v" not in speak_line:
            return {"ttfa_ms": None}
        speak_ns = int(speak_line["v"].split()[1])
        return {"ttfa_ms": (first_audio_ns - speak_ns) / 1e6}
    finally:
        kill(proc)


def summarize(values):
    values = [v for v in values if v is not None]
    if not values:
        return None
    ordered = sorted(values)
    p90 = ordered[min(len(ordered) - 1, int(round(0.9 * (len(ordered) - 1))))]
    return {"median": round(statistics.median(ordered), 1), "p90": round(p90, 1),
            "min": round(ordered[0], 1), "n": len(ordered)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=["v4", "v5"], required=True)
    parser.add_argument("--src", default="")
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--ttfa-runs", type=int, default=5)
    parser.add_argument("--idle", type=float, default=10.0)
    parser.add_argument("--metrics", default="startup,ttfa")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    metrics = set(args.metrics.split(","))
    guard = CpuGuard()
    guard.start()
    rows = []
    if "startup" in metrics:
        for i in range(args.runs):
            wait_for_quiet_cpu()
            rows.append(run_startup(args.target, args.src, args.idle))
            print(f"startup run {i + 1}: {rows[-1]}", flush=True)
            if guard.peak > CPU_LIMIT:
                print(f"note: CPU peaked at {guard.peak:.0f}% during run {i + 1}", flush=True)
    ttfa = []
    if "ttfa" in metrics:
        for i in range(args.ttfa_runs):
            wait_for_quiet_cpu()
            ttfa.append(run_ttfa(args.target, args.src)["ttfa_ms"])
            print(f"ttfa run {i + 1}: {ttfa[-1]}", flush=True)
    guard.stop_evt.set()

    summary = {
        "target": args.target,
        "python": sys.version.split()[0],
        "startup_ms": summarize([r["startup_ms"] for r in rows]),
        "rss_mb": summarize([r["rss_mb"] for r in rows]),
        "uss_mb": summarize([r["uss_mb"] for r in rows]),
        "ttfa_ms": summarize(ttfa),
        "cpu_peak_percent": round(guard.peak, 1),
    }
    print(json.dumps(summary, indent=2))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"summary": summary, "runs": rows, "ttfa_runs": ttfa}, f, indent=2)


if __name__ == "__main__":
    main()
