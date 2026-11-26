"""Turn a downloaded ultralytics .pt fire model into the Pi's ONNX file, safely.

A .pt file is a Python pickle: opening it normally can run any code inside it. This script
1) lists the classes the pickle refers to WITHOUT loading it, 2) loads it with PyTorch's
weights_only=True and an allowlist of exactly the expected PyTorch/ultralytics classes (anything
else stops the load), 3) copies the weights into a freshly built model and exports ONNX.

usage (training venv): python convert_pretrained.py MODEL.pt OUT_DIR [--sizes 320 640]
Used for rabahdev/fire-smoke-yolov8n (docs/fire.md).
"""

from __future__ import annotations

import argparse
import collections
import pickletools
import shutil
import sys
import zipfile
from pathlib import Path

EXPECTED = {
    "__builtin__ set", "builtins set", "collections OrderedDict", "torch Size", "torch FloatStorage",
    "torch HalfStorage", "torch LongStorage", "torch._utils _rebuild_parameter",
    "torch._utils _rebuild_tensor_v2",
}
EXPECTED_PREFIXES = ("torch.nn.modules.", "ultralytics.nn.modules.", "ultralytics.nn.tasks ")


def pickle_globals(path: Path) -> set[str]:
    """Classes and functions the pickle would import, found by reading opcodes only."""
    found = set()
    with zipfile.ZipFile(path) as archive:
        for name in (n for n in archive.namelist() if n.endswith(".pkl")):
            strings = []
            for op, arg, _ in pickletools.genops(archive.read(name)):
                if op.name in ("SHORT_BINUNICODE", "BINUNICODE", "UNICODE"):
                    strings.append(arg)
                elif op.name == "GLOBAL":
                    found.add(arg)
                elif op.name == "STACK_GLOBAL":
                    found.add(f"{strings[-2]} {strings[-1]}")
    return found


def resolve(name: str):
    module, attribute = name.split(" ")
    module = "builtins" if module == "__builtin__" else module
    return getattr(__import__(module, fromlist=[attribute]), attribute)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("model", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--sizes", type=int, nargs="+", default=[320])
    args = parser.parse_args()

    names = pickle_globals(args.model)
    unexpected = sorted(n for n in names if n not in EXPECTED and not n.startswith(EXPECTED_PREFIXES))
    if unexpected:
        print(f"refusing: unexpected globals in pickle: {unexpected}", file=sys.stderr)
        return 1

    import torch
    from ultralytics import YOLO
    from ultralytics.nn.tasks import DetectionModel

    with torch.serialization.safe_globals([resolve(n) for n in sorted(names)]):
        checkpoint = torch.load(args.model, map_location="cpu", weights_only=True)
    source = checkpoint["model"].float()
    model = DetectionModel(source.yaml, nc=source.yaml["nc"], verbose=False)
    model.load_state_dict(source.state_dict(), strict=True)
    model.names = source.names
    print(f"classes: {model.names}")
    args.out.mkdir(parents=True, exist_ok=True)
    clean = args.out / "clean.pt"
    torch.save({"model": model, "train_args": {}}, clean)  # Our own objects only.
    for size in args.sizes:
        exported = YOLO(str(clean)).export(format="onnx", imgsz=size, opset=12, simplify=True, dynamic=False)
        shutil.move(exported, args.out / f"fire_{size}.onnx")
        print(f"wrote {args.out / f'fire_{size}.onnx'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
