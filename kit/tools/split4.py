#!/usr/bin/env python
"""Split the generated 2x2 sheet back into four views and align them.

The sheet comes back with a pure white background, so each figure can be found
exactly. Fixed halves are the wrong cut: the model regularly paints a base past
the midline, and a 50/50 slice then lops it off. This finds the four figures as
connected blobs, crops each to its own bounding box, and pastes them onto one
shared canvas at the same content height and the same baseline — which is also
what Tripo wants from a multiview set.

Layout is fixed:

    front | back
    left  | right

Usage:
  python tools/split4.py --sheet 手办-四视图_00001_.png --out-dir figures/hovey1/shots
  python tools/split4.py --sheet sheet.png --out-dir out --mode fixed
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")

VIEWS = ("正面", "背面", "左侧", "右侧")
INK = 245          # darker than this is figure, not background
MIN_AREA = 0.01    # a figure is at least 1% of the sheet


def ink_mask(image: Image.Image) -> np.ndarray:
    gray = np.asarray(image.convert("L"), dtype=np.uint8)
    return gray < INK


def components(mask: np.ndarray):
    """8-connected blobs, largest first: [(area, bbox), ...]."""
    from scipy import ndimage

    labels, count = ndimage.label(mask, structure=np.ones((3, 3), dtype=int))
    if not count:
        return []
    slices = ndimage.find_objects(labels)
    areas = ndimage.sum(mask, labels, range(1, count + 1))
    blobs = []
    for index, area in enumerate(areas, start=1):
        if area < mask.size * MIN_AREA:
            continue
        box = slices[index - 1]
        blobs.append((float(area), (box[1].start, box[0].start, box[1].stop, box[0].stop)))
    blobs.sort(key=lambda item: item[0], reverse=True)
    return blobs


def quadrant_of(box, width, height) -> int:
    left, top, right, bottom = box
    cx, cy = (left + right) / 2, (top + bottom) / 2
    return (0 if cy < height / 2 else 2) + (0 if cx < width / 2 else 1)


def main() -> None:
    parser = argparse.ArgumentParser(description="四宫格切成四张视图并对齐")
    parser.add_argument("--sheet", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--mode", choices=("auto", "fixed"), default="auto",
                        help="auto 按人物轮廓裁切（推荐），fixed 按正中间硬切")
    parser.add_argument("--margin", type=int, default=12, help="auto 模式四周留白")
    parser.add_argument("--trim", type=int, default=8, help="fixed 模式内侧收掉的像素")
    parser.add_argument("--width", type=int, default=512)
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument("--names", default=",".join(VIEWS))
    parser.add_argument("--check", default=None)
    args = parser.parse_args()

    sheet = Image.open(args.sheet).convert("RGB")
    width, height = sheet.size
    names = [n.strip() for n in args.names.split(",")]
    if len(names) != 4:
        raise SystemExit("--names 需要 4 个名字")

    crops: dict[int, Image.Image] = {}
    draw_boxes = []

    if args.mode == "auto":
        blobs = components(ink_mask(sheet))
        if len(blobs) >= 4:
            for area, box in blobs:
                quadrant = quadrant_of(box, width, height)
                if quadrant in crops:
                    continue
                crops[quadrant] = sheet.crop(box)
                draw_boxes.append((quadrant, box))
                if len(crops) == 4:
                    break
        if len(crops) < 4:
            print(f"[warn] 只认出 {len(crops)} 个人物，退回硬切")
            crops = {}
            draw_boxes = []
            args.mode = "fixed"

    if args.mode == "fixed":
        half_w, half_h = width // 2, height // 2
        boxes = [
            (0, 0, half_w - args.trim, half_h - args.trim),
            (half_w + args.trim, 0, width, half_h - args.trim),
            (0, half_h + args.trim, half_w - args.trim, height),
            (half_w + args.trim, half_h + args.trim, width, height),
        ]
        for quadrant, box in enumerate(boxes):
            crops[quadrant] = sheet.crop(box)
            draw_boxes.append((quadrant, box))

    # each figure is scaled to the same content height so the four views line up
    canvas_w, canvas_h = args.width, args.height
    inner_h = canvas_h - 2 * args.margin

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"sheet {width}x{height}  mode {args.mode}  canvas {canvas_w}x{canvas_h}")

    for quadrant in range(4):
        crop = crops[quadrant]
        scale = inner_h / max(crop.height, 1)
        size = (max(1, round(crop.width * scale)), max(1, round(crop.height * scale)))
        scaled = crop.resize(size, Image.LANCZOS)
        canvas = Image.new("RGB", (canvas_w, canvas_h), (255, 255, 255))
        canvas.paste(scaled, ((canvas_w - size[0]) // 2, canvas_h - args.margin - size[1]))
        target = out_dir / f"{names[quadrant]}.png"
        canvas.save(target)

        edge = min(size[0] / canvas_w, size[1] / canvas_h)
        note = "  [warn] 人物几乎贴满画布" if edge > 0.99 else ""
        print(f"  {names[quadrant]:2}  {size[0]}x{size[1]} -> {canvas_w}x{canvas_h}{note}")

    if args.check:
        check = sheet.copy()
        draw = ImageDraw.Draw(check)
        colors = [(0, 120, 255), (255, 80, 0), (0, 160, 90), (200, 0, 160)]
        for quadrant, box in draw_boxes:
            draw.rectangle(box, outline=colors[quadrant], width=3)
            draw.text((box[0] + 6, box[1] + 4), names[quadrant], fill=colors[quadrant])
        draw.line((width // 2, 0, width // 2, height), fill=(220, 220, 220), width=1)
        draw.line((0, height // 2, width, height // 2), fill=(220, 220, 220), width=1)
        Path(args.check).parent.mkdir(parents=True, exist_ok=True)
        check.save(args.check)
        print("check:", args.check)

    print("saved:", out_dir)


if __name__ == "__main__":
    main()
