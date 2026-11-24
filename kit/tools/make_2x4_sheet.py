#!/usr/bin/env python
"""Build the 2x4 character/spirit view sheet and the base prompt.

Layout (4 columns x 2 rows, 1024 px cells, no labels):
    character front | left | back | right
    spirit    front | left | back | right

The figures are cut out with the BiRefNet masks from output/roco-mask, composited
on white, and their clear acrylic display disc is trimmed off the bottom.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")

CELL = 1024
ROWS = (
    ("character", (("char-front", 0.010), ("char-left", 0.010),
                   ("char-back", 0.010), ("char-right", 0.010))),
    ("spirit", (("spirit-front", 0.030), ("spirit-left", 0.030),
                ("spirit-back", 0.120), ("spirit-right", 0.120))),
)

BASE_PROMPT_EN = (
    "A round collectible figurine display base, 30 cm in diameter and 1.5 cm thick, "
    "with a sculpted moss-green grass top, irregular grass tufts, a dark brown soil "
    "cross-section with small pebbles along the side, a sculpted grey rock on the top "
    "surface, and a thin clear acrylic rim at the bottom edge. Hand-painted resin, matte "
    "finish, soft studio lighting from the upper left, product photograph, seamless white "
    "background. No characters, no creatures, no figures - only the base."
)
BASE_PROMPT_ZH = (
    "一个圆形手办展示地台，直径 30cm、厚 1.5cm；顶面是雕刻的苔绿色草皮和不规则草簇，"
    "侧面是深棕色泥土断面并带小石子，顶面有一块雕刻的灰色石头，底边有一圈薄透明亚克力边。"
    "手涂树脂、哑光质感，左上方柔光，商品摄影，纯白无缝背景。不要人物、不要精灵、不要任何角色，只要地台。"
)


def clean_mask(mask: Image.Image) -> Image.Image:
    binary = np.asarray(mask) > 16
    labels, count = ndimage.label(binary)
    if count == 0:
        return mask
    sizes = ndimage.sum(binary, labels, range(1, count + 1))
    main = int(np.argmax(sizes)) + 1
    slices = ndimage.find_objects(labels)
    main_slice = slices[main - 1]
    main_bottom = main_slice[0].stop
    main_height = max(1, main_slice[0].stop - main_slice[0].start)
    keep = np.zeros_like(binary)
    for index in range(1, count + 1):
        if float(sizes[index - 1]) < float(sizes.max()) * 0.005:
            continue
        sl = slices[index - 1]
        height = max(1, sl[0].stop - sl[0].start)
        width = max(1, sl[1].stop - sl[1].start)
        is_shadow = (sl[0].start >= main_bottom - main_height * 0.05) and (width > height * 2.5)
        if index != main and is_shadow:
            continue
        keep |= labels == index
    keep = ndimage.binary_fill_holes(keep)
    keep = ndimage.binary_erosion(keep, iterations=1)
    return Image.fromarray((keep * 255).astype(np.uint8))


def content_bbox(image: Image.Image, threshold: int = 250):
    gray = image.convert("L")
    mask = gray.point(lambda value: 255 if value < threshold else 0)
    return mask.getbbox()


def cutout(image_path: Path, mask_path: Path | None, trim_bottom: float) -> Image.Image:
    image = Image.open(image_path).convert("RGB")
    if mask_path and mask_path.exists():
        mask = Image.open(mask_path).convert("L")
        if mask.size != image.size:
            mask = mask.resize(image.size, Image.LANCZOS)
        mask = clean_mask(mask)
        canvas = Image.new("RGB", image.size, "#FFFFFF")
        canvas.paste(image, (0, 0), mask)
        image = canvas
    cut = int(round(image.height * trim_bottom))
    if cut > 0:
        image = image.crop((0, 0, image.width, max(8, image.height - cut)))
    box = content_bbox(image)
    if box:
        pad = 6
        image = image.crop((max(0, box[0] - pad), max(0, box[1] - pad),
                            min(image.width, box[2] + pad), min(image.height, box[3] + pad)))
    return image


def place(image: Image.Image, cell: Image.Image, origin: tuple[int, int]) -> None:
    max_w = int(CELL * 0.92)
    max_h = int(CELL * 0.80)
    scale = min(max_w / image.width, max_h / image.height)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    image = image.resize(size, Image.LANCZOS)
    x = origin[0] + (CELL - size[0]) // 2
    baseline = origin[1] + int(CELL * 0.92)
    y = baseline - size[1]
    cell.paste(image, (x, y))


def main() -> None:
    parser = argparse.ArgumentParser(description="2x4 PVC view sheet + base prompt")
    parser.add_argument("--dir", default=r"A:\Comfy-Desktop\ComfyUI-Shared\input\roco-pvc")
    parser.add_argument("--mask-dir", default=r"A:\Comfy-Desktop\ComfyUI-Shared\output\roco-mask")
    parser.add_argument("--out", default=r"A:\Comfy-Desktop\ComfyUI-Shared\output\洛克王国-2x4视角图")
    args = parser.parse_args()

    source = Path(args.dir)
    mask_dir = Path(args.mask_dir)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    sheet = Image.new("RGB", (CELL * 4, CELL * 2), "#FFFFFF")
    for row, (_, items) in enumerate(ROWS):
        for col, (name, trim) in enumerate(items):
            path = source / f"{name}.png"
            if not path.exists():
                raise SystemExit(f"missing: {path}")
            mask_path = mask_dir / f"{name}_00001_.png"
            image = cutout(path, mask_path, trim)
            place(image, sheet, (col * CELL, row * CELL))

    sheet_path = out_dir / "2x4-视角图.png"
    sheet.save(sheet_path)
    preview = sheet.copy()
    preview.thumbnail((1600, 1600), Image.LANCZOS)
    preview.save(out_dir / "2x4-视角图-preview.jpg", quality=90)

    prompt_path = out_dir / "base-prompt.txt"
    prompt_path.write_text(
        "EN:\n" + BASE_PROMPT_EN + "\n\n---\n\nZH:\n" + BASE_PROMPT_ZH + "\n",
        encoding="utf-8",
    )

    print("saved:", sheet_path, sheet.size)
    print("saved:", prompt_path)


if __name__ == "__main__":
    main()
