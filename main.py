"""Start camera, line, lidar, fire, and stream as separate processes; restart any that dies.
If a driving process (camera, line, lidar) exits 5 times within 60 s, stop all of them and
exit with code 1 so systemd restarts everything. An optional process (stream) never stops
the others: it is only restarted more slowly. Fire and stream are optional.

usage: main.py [--lidar-replay FILE.hex] [--no-stream] [--no-fire]
"""

import argparse
import os
import signal
import subprocess
import sys
import time
import tomllib
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESTART_S = 2.0
MAX_DEATHS = 5      # This many exits of one process ...
DEATH_WINDOW_S = 60.0  # ... within this time stop everything.
OPTIONAL = {"fire", "stream"}  # Their failures must not stop driving data.
OPTIONAL_BACKOFF_S = 30.0  # Restart delay for an optional process that keeps dying.
CORES_PATH = ROOT / "main.toml"


def load_cores(path=CORES_PATH, names=None) -> dict:
    """name -> set of CPU cores the process may use (docs/timing.md). Missing name = all cores."""
    cores = tomllib.loads(path.read_text(encoding="utf-8"))["cores"]
    available = os.sched_getaffinity(0)
    result = {}
    for name, listed in cores.items():
        if names is not None and name not in names:
            raise ValueError(f"main.toml: unknown process {name!r}")
        if not listed or not set(listed) <= available:
            raise ValueError(f"main.toml: {name} cores {listed} not within {sorted(available)}")
        result[name] = set(listed)
    return result


def build_commands(lidar_replay=None, stream=True, fire=True):
    commands = {"camera": ["camera/capture.py"], "line": ["line/run.py"], "lidar": ["lidar/run.py"],
                "fire": ["fire/run.py"], "stream": ["stream/run.py"]}
    if lidar_replay:
        commands["lidar"] += ["--replay", str(Path(lidar_replay).resolve())]
    if not stream:
        del commands["stream"]
    if not fire:
        del commands["fire"]
    return {name: [sys.executable, str(ROOT / c[0]), *c[1:]] for name, c in commands.items()}


def supervise(commands, should_stop, restart_s=RESTART_S, max_deaths=MAX_DEATHS,
              window_s=DEATH_WINDOW_S, optional=OPTIONAL, optional_backoff_s=OPTIONAL_BACKOFF_S,
              cores=None) -> int:
    """Run each command as its own process. Return 0 when asked to stop, 1 when one keeps dying."""
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1")
    processes, restart_at = {}, dict.fromkeys(commands, 0.0)
    deaths = {name: deque() for name in commands}
    result = 0
    try:
        while not should_stop():
            for name, command in commands.items():
                process = processes.get(name)
                if process is not None and process.poll() is not None:
                    now = time.monotonic()
                    deaths[name].append(now)
                    while deaths[name] and now - deaths[name][0] > window_s:
                        deaths[name].popleft()
                    if len(deaths[name]) >= max_deaths and name in optional:
                        print(f"[main] {name} keeps exiting (last code {process.returncode}); "
                              f"retry in {optional_backoff_s:.0f}s, others keep running", file=sys.stderr)
                        deaths[name].clear()
                        restart_at[name] = now + optional_backoff_s
                        processes[name] = None
                        continue
                    if len(deaths[name]) >= max_deaths:
                        print(f"[main] {name} exited {len(deaths[name])} times in {window_s:.0f}s "
                              f"(last code {process.returncode}); stopping everything", file=sys.stderr)
                        return 1
                    print(f"[main] {name} exited ({process.returncode}); restart "
                          f"{len(deaths[name])}/{max_deaths - 1}", file=sys.stderr)
                    restart_at[name] = now + restart_s
                    processes[name] = process = None
                if process is None and time.monotonic() >= restart_at[name]:
                    # Own session: Ctrl+C reaches only main, which then stops each child.
                    allowed = (cores or {}).get(name)
                    processes[name] = subprocess.Popen(
                        command, cwd=ROOT, env=env, start_new_session=True,
                        preexec_fn=(lambda a=allowed: os.sched_setaffinity(0, a)) if allowed else None)
                    print(f"[main] {name} pid={processes[name].pid}", file=sys.stderr)
            time.sleep(0.1)
        return result
    finally:
        running = [p for p in processes.values() if p is not None and p.poll() is None]
        for process in running:
            process.terminate()
        for process in running:
            try:
                process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lidar-replay", type=Path)
    parser.add_argument("--no-stream", action="store_true", help="do not start Wi-Fi streaming")
    parser.add_argument("--no-fire", action="store_true", help="do not start fire detection")
    args = parser.parse_args()
    stopping = False

    def request_stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    commands = build_commands(args.lidar_replay, stream=not args.no_stream, fire=not args.no_fire)
    cores = load_cores(names=build_commands().keys())
    return supervise(commands, lambda: stopping, cores=cores)


if __name__ == "__main__":
    sys.exit(main())
