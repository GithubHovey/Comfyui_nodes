#!/usr/bin/env python
"""Tile four character screenshots into one 2x2 reference sheet.

The sheet is what the four-view workflow edits in a single pass: all four
views sit in one image, so one denoise run sees every angle at once and the
figurine comes out with one material, one palette and one lighting.

Layout is fixed:

    front | back
    left  | right

split4.py uses the same order. Do not change one without the other.

Usage:
  python tools/tile4.py --dir A:/Comfy-Desktop/ComfyUI-Shared/input \
      --out A:/Comfy-Desktop/ComfyUI-Shared/input/四宫格-参考.png

  python tools/tile4.py --front 正面.png --back 背面.png --left 左侧.png \
      --right 右侧.png --out sheet.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")

# (grid position, chinese name, default filename)
VIEWS = (
    (0, "正面", "正面.png"),
    (1, "背面", "背面.png"),
    (2, "左侧", "左侧.png"),
    (3, "右侧", "右侧.png"),
)


def load(path: Path, bg: tuple[int, int, int]) -> Image.Image:
    image = Image.open(path)
    if image.mode in ("RGBA", "LA", "P"):
        image = image.convert("RGBA")
        canvas = Image.new("RGB", image.size, bg)
        canvas.paste(image, mask=image.split()[-1])
        return canvas
    return image.convert("RGB")


def main() -> None:
    parser = argparse.ArgumentParser(description="四张视角截图拼成 2x2 参考图")
    parser.add_argument("--dir", help="放着 正面/背面/左侧/右侧.png 的目录")
    parser.add_argument("--front")
    parser.add_argument("--back")
    parser.add_argument("--left")
    parser.add_argument("--right")
    parser.add_argument("--out", required=True)
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=2048)
    parser.add_argument("--margin", type=int, default=24)
    parser.add_argument("--gap", type=int, default=24)
    parser.add_argument("--bg", default="#FFFFFF")
    parser.add_argument("--fit", choices=("bottom", "center"), default="bottom",
                        help="bottom 让每格底边对齐，更接近真实四视图")
    args = parser.parse_args()

    explicit = [args.front, args.back, args.left, args.right]
    if any(explicit) and not all(explicit):
        raise SystemExit("--front/--back/--left/--right 要么全给，要么都不给（用 --dir）")
    if not any(explicit) and not args.dir:
        raise SystemExit("给 --dir，或者四个视角路径全给")

    bg = tuple(int(args.bg.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    sources = explicit if any(explicit) else [Path(args.dir) / name for _, _, name in VIEWS]
    paths = [Path(p) for p in sources]
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        raise SystemExit("缺图: " + ", ".join(missing))

    cell_w = (args.width - 2 * args.margin - args.gap) // 2
    cell_h = (args.height - 2 * args.margin - args.gap) // 2
    sheet = Image.new("RGB", (args.width, args.height), bg)

    print(f"sheet {args.width}x{args.height}  cell {cell_w}x{cell_h}")
    for index, (path, (_, name, _)) in enumerate(zip(paths, VIEWS)):
        image = load(path, bg)
        row, col = divmod(index, 2)
        cell_x = args.margin + col * (cell_w + args.gap)
        cell_y = args.margin + row * (cell_h + args.gap)

        scale = min(cell_w / image.width, cell_h / image.height)
        size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        scaled = image.resize(size, Image.LANCZOS)

        paste_x = cell_x + (cell_w - size[0]) // 2
        paste_y = cell_y + cell_h - size[1] if args.fit == "bottom" else cell_y + (cell_h - size[1]) // 2
        sheet.paste(scaled, (paste_x, paste_y))
        print(f"  {name:2}  {image.width}x{image.height} -> {size[0]}x{size[1]}  ({path.name})")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    print("saved:", out)

    preview = out.with_name(out.stem + "-preview.jpg")
    small = sheet.copy()
    small.thumbnail((900, 900), Image.LANCZOS)
    small.save(preview, quality=90)
    print("saved:", preview)


if __name__ == "__main__":
    main()
