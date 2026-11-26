"""Check the project rules and run every test, without any device.

usage: .venv/bin/python tools/check.py [AREA ...]     (no AREA: everything)

Rules (see docs/README.md "원칙"):
  - an area never imports another area (only common/)
  - only camera/ opens the camera (picamera2), only lidar/ and stm32/ open serial ports
  - no bare `except:` and no broad exception that is silently ignored
Exit code 0 = all passed, 1 = something failed.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "bin" / "python"
AREAS = ("camera", "line", "lidar", "stm32", "fire", "stream", "common")
SERIAL_AREAS = ("lidar", "stm32")
TIMEOUT_S = 120


def check_rules(path: Path, area: str) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as error:
        return [f"{path}:{error.lineno}: syntax error: {error.msg}"]

    # Modules of other areas, by package name and by bare file name (areas run with their
    # own folder on PYTHONPATH, so `import detector` would also reach into line/).
    forbidden = {}
    for other in AREAS:
        if other in (area, "common"):
            continue
        forbidden[other] = other
        for module in (ROOT / other).glob("*.py"):
            forbidden[module.stem] = other
    for module in (ROOT / area).glob("*.py"):
        forbidden.pop(module.stem, None)

    problems = []
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names = [node.module]
        for name in names:
            top = name.split(".")[0]
            if top in forbidden:
                problems.append(f"{path}:{node.lineno}: {area}/ must not import {forbidden[top]}/ ({name})")
            if top == "picamera2" and area != "camera":
                problems.append(f"{path}:{node.lineno}: only camera/ may open the camera")
            if top == "serial" and area not in SERIAL_AREAS:
                problems.append(f"{path}:{node.lineno}: only {'/, '.join(SERIAL_AREAS)}/ may use serial ports")
        if isinstance(node, ast.ExceptHandler):
            broad = node.type is None or (
                isinstance(node.type, ast.Name) and node.type.id in ("Exception", "BaseException"))
            if node.type is None:
                problems.append(f"{path}:{node.lineno}: bare except; name the exception")
            elif broad and all(isinstance(item, (ast.Pass, ast.Continue)) for item in node.body):
                problems.append(f"{path}:{node.lineno}: broad exception silently ignored")
    return problems


def run_tests(folder: Path, pythonpath: str) -> tuple[bool, str]:
    if not list((folder / "tests").glob("test_*.py")):
        return True, "테스트 없음"
    env = dict(os.environ, PYTHONPATH=pythonpath, PYTHONDONTWRITEBYTECODE="1")
    try:
        result = subprocess.run([str(PYTHON), "-m", "unittest", "discover", "-s", "tests"],
                                cwd=folder, env=env, capture_output=True, text=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return False, f"{TIMEOUT_S}초 초과"
    output = result.stdout + result.stderr
    summary = next((line for line in reversed(output.splitlines()) if line.startswith("Ran ")), "")
    if result.returncode:
        return False, output[-4000:]
    return True, summary


def main() -> int:
    selected = sys.argv[1:] or [*AREAS, "main"]
    unknown = [name for name in selected if name not in (*AREAS, "main")]
    if unknown:
        print(f"unknown area: {', '.join(unknown)}", file=sys.stderr)
        return 2
    failed = False
    for area in [a for a in AREAS if a in selected]:
        folder = ROOT / area
        if not folder.is_dir():
            print(f"== {area}: 폴더 없음 (아직 시작 안 함)")
            continue
        problems = [p for path in sorted(folder.rglob("*.py")) if "__pycache__" not in path.parts
                    for p in check_rules(path, area)]
        ok, detail = run_tests(folder, f"{folder}{os.pathsep}{ROOT}")
        print(f"== {area}: {'통과' if ok and not problems else '실패'}  {detail if ok else ''}")
        for problem in problems:
            print(f"   규칙 위반 {problem}")
        if not ok:
            print(detail)
        failed |= bool(problems) or not ok
    if "main" in selected:
        ok, detail = run_tests(ROOT, str(ROOT))
        print(f"== main.py: {'통과' if ok else '실패'}  {detail if ok else ''}")
        if not ok:
            print(detail)
        failed |= not ok
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
