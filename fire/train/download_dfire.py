"""Download the D-Fire dataset and turn it into a fire-only YOLO dataset.

D-Fire (https://github.com/gaiasd/DFireDataset, CC0 1.0): 21,527 pictures of fire and smoke,
YOLO labels, class 0 = smoke, 1 = fire. Fetched from the Hugging Face mirror badsaarow/d-fire as
a few large parquet files (fetching thousands of single files hits the rate limit). Each parquet
file is deleted after the chosen pictures are taken out of it.

Output (fire is class 0, smoke boxes dropped; smoke-only and empty pictures are "no fire",
which teaches the model what is NOT fire). Pictures are shrunk to at most 640 px.
  OUT/images/{train,val,test}/*.jpg   OUT/labels/{train,val,test}/*.txt   OUT/data.yaml

usage: python download_dfire.py OUT [--fire 3000] [--no-fire 1500] [--test 600] [--seed 1]
Needs pyarrow and pillow (the training venv has them: see docs/fire.md).
"""

from __future__ import annotations

import argparse
import io
import json
import random
import shutil
import sys
import urllib.request
from pathlib import Path

import pyarrow.parquet as pq
from PIL import Image

REPO = "https://huggingface.co/datasets/badsaarow/d-fire"
API = "https://huggingface.co/api/datasets/badsaarow/d-fire/tree/main/data"
DFIRE_FIRE = 1
VAL_SHARE = 0.15
MAX_SIDE = 640


def fire_lines(label: str) -> list[str]:
    """Keep fire boxes only, renumbered to class 0."""
    kept = []
    for line in label.splitlines():
        parts = line.split()
        if len(parts) == 5 and int(float(parts[0])) == DFIRE_FIRE:
            kept.append(" ".join(["0", *parts[1:]]))
    return kept


def shards(split: str) -> list[str]:
    with urllib.request.urlopen(API, timeout=60) as response:
        files = json.loads(response.read())
    return sorted(f["path"] for f in files if Path(f["path"]).name.startswith(f"{split}-"))


def download(path: str, target: Path) -> None:
    with urllib.request.urlopen(f"{REPO}/resolve/main/{path}", timeout=120) as response, \
            open(target, "wb") as output:
        shutil.copyfileobj(response, output, 1 << 20)


def extract(split: str, out: Path, keep_no_fire: float, rng: random.Random) -> dict[str, list[str]]:
    """Save every fire picture and a random share of the others into OUT/pool/SPLIT.
    Return name -> fire label lines. Already processed shards are skipped (resumable)."""
    pool = out / "pool" / split
    pool.mkdir(parents=True, exist_ok=True)
    index_file = out / "pool" / f"{split}.json"
    index = json.loads(index_file.read_text()) if index_file.exists() else {"done": [], "labels": {}}
    for path in shards(split):
        if path in index["done"]:
            continue
        temporary = out / "pool" / "shard.parquet"
        print(f"downloading {path}", file=sys.stderr)
        download(path, temporary)
        table = pq.ParquetFile(temporary)
        for batch in table.iter_batches(batch_size=64, columns=["image", "label", "filename"]):
            for row in batch.to_pylist():
                lines = fire_lines(row["label"] or "")
                if not lines and rng.random() > keep_no_fire:
                    continue
                name = Path(row["filename"]).stem
                image = Image.open(io.BytesIO(row["image"]["bytes"])).convert("RGB")
                image.thumbnail((MAX_SIDE, MAX_SIDE))
                image.save(pool / f"{name}.jpg", quality=90)
                index["labels"][name] = lines
        temporary.unlink()
        index["done"].append(path)
        index_file.write_text(json.dumps(index))
        fire = sum(1 for v in index["labels"].values() if v)
        print(f"  {split}: {fire} with fire, {len(index['labels']) - fire} without so far", file=sys.stderr)
    return index["labels"]


def choose(labels: dict, fire: int, no_fire: int, rng: random.Random) -> list[str]:
    with_fire = sorted(n for n, v in labels.items() if v)
    without = sorted(n for n, v in labels.items() if not v)
    return rng.sample(with_fire, min(fire, len(with_fire))) + rng.sample(without, min(no_fire, len(without)))


def place(names: list[str], labels: dict, source: Path, out: Path, split: str) -> None:
    (out / "images" / split).mkdir(parents=True, exist_ok=True)
    (out / "labels" / split).mkdir(parents=True, exist_ok=True)
    for name in names:
        shutil.copyfile(source / f"{name}.jpg", out / "images" / split / f"{name}.jpg")
        lines = labels[name]
        (out / "labels" / split / f"{name}.txt").write_text("\n".join(lines) + ("\n" if lines else ""))
    fire = sum(1 for n in names if labels[n])
    print(f"{split}: {len(names)} pictures ({fire} with fire)", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out", type=Path)
    parser.add_argument("--fire", type=int, default=3000, help="pictures with fire (train+val)")
    parser.add_argument("--no-fire", type=int, default=1500, help="pictures without fire (train+val)")
    parser.add_argument("--test", type=int, default=600, help="pictures from the D-Fire test split")
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    rng = random.Random(args.seed)
    out = args.out.resolve()

    train = extract("train", out, keep_no_fire=0.3, rng=rng)
    test = extract("test", out, keep_no_fire=0.3, rng=rng) if args.test else {}
    for split in ("train", "val", "test"):
        shutil.rmtree(out / "images" / split, ignore_errors=True)
        shutil.rmtree(out / "labels" / split, ignore_errors=True)
    chosen = choose(train, args.fire, args.no_fire, rng)
    rng.shuffle(chosen)
    n_val = round(len(chosen) * VAL_SHARE)
    place(chosen[:n_val], train, out / "pool" / "train", out, "val")
    place(chosen[n_val:], train, out / "pool" / "train", out, "train")
    if args.test:
        place(choose(test, args.test * 2 // 3, args.test - args.test * 2 // 3, rng), test,
              out / "pool" / "test", out, "test")
    (out / "data.yaml").write_text(
        f"# D-Fire subset (CC0 1.0, github.com/gaiasd/DFireDataset), fire only\n"
        f"path: {out}\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n  0: fire\n")
    print(f"done: {out / 'data.yaml'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
