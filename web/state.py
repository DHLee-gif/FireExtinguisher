import threading
from collections import deque

COMMANDS = ("start", "stop", "return", "resume")

_lock = threading.Lock()
_commands = deque()
_live = {
    "action": "idle",
    "water_level": None,
    "sortie": False,
}


def push_command(cmd):
    with _lock:
        if cmd == "stop":
            _commands.clear()
        _commands.append(cmd)


def pop_command():
    with _lock:
        return _commands.popleft() if _commands else None


def start_sortie():
    with _lock:
        _live["sortie"] = True
    push_command("start")


def update_from_heartbeat(action, water_level):
    with _lock:
        prev = _live["action"]
        if action:
            _live["action"] = action
            if prev == "idle" and action != "idle":
                _live["sortie"] = True
            elif prev != "idle" and action == "idle":
                _live["sortie"] = False
        if water_level is not None:
            _live["water_level"] = water_level


def update_water(water_level):
    if water_level is None:
        return
    with _lock:
        _live["water_level"] = water_level


def snapshot():
    with _lock:
        return dict(_live, pending=list(_commands))
