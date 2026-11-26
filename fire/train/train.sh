#!/usr/bin/env bash
# Train the fire model and put it where fire/run.py looks for it. Details: docs/fire.md
#
# usage: fire/train/train.sh [EPOCHS]        (default 40)
#   TRAIN_DIR  folder for the training venv, dataset and runs (default ~/fire-train)
#
# Runs on the Pi CPU (hours) or on a PC (faster; with a GPU add DEVICE=0).
# Stop the car processes first on the Pi (sudo systemctl stop firecar): training uses every core.
set -euo pipefail

EPOCHS="${1:-40}"
TRAIN_DIR="${TRAIN_DIR:-$HOME/fire-train}"
DEVICE="${DEVICE:-cpu}"
PROJ="$(cd "$(dirname "$0")/../.." && pwd)"
PY="$TRAIN_DIR/.venv/bin/python"
IMGSZ=320   # Must match input_size in fire/config.toml.
# Without this PyTorch used only 1 of the Pi's 4 cores.
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-$(nproc)}"

if [ ! -x "$PY" ]; then
  echo "training venv missing: create it first (docs/fire.md, 'Pi에서 학습')" >&2
  exit 1
fi
if [ ! -f "$TRAIN_DIR/dfire/data.yaml" ]; then
  "$PY" "$PROJ/fire/train/download_dfire.py" "$TRAIN_DIR/dfire"
fi

cd "$TRAIN_DIR"
"$PY" - "$EPOCHS" "$DEVICE" "$IMGSZ" <<'EOF'
import sys
from ultralytics import YOLO

epochs, device, imgsz = int(sys.argv[1]), sys.argv[2], int(sys.argv[3])
model = YOLO("yolov8n.pt")  # COCO-pretrained, smallest. Fine-tuned to one class: fire.
model.train(data="dfire/data.yaml", imgsz=imgsz, epochs=epochs, batch=16, device=device,
            workers=2, patience=10, project="runs", name="fire", exist_ok=True,
            plots=True, verbose=False)
best = YOLO("runs/fire/weights/best.pt")
print(best.val(data="dfire/data.yaml", split="test", imgsz=imgsz, device=device, plots=False).results_dict)
best.export(format="onnx", imgsz=imgsz, opset=12, simplify=True, dynamic=False)
EOF

mkdir -p "$PROJ/fire/models"
cp "$TRAIN_DIR/runs/fire/weights/best.onnx" "$PROJ/fire/models/fire.onnx"
echo "model installed: $PROJ/fire/models/fire.onnx"
