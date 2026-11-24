#!/usr/bin/env python
"""Assemble the four base views into a 2x2 sheet and export single views."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from PIL import Image

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")

CELL = 1024
SRC = Path(r"A:\Comfy-Desktop\ComfyUI-Shared\output\洛克王国-草地地台")
OUT = Path(r"A:\Comfy-Desktop\ComfyUI-Shared\output\洛克王国-草地地台四视图")
PROMPT_SRC = Path(r"A:\Comfy-Desktop\ComfyUI-Shared\output\洛克王国-2x4视角图\base-prompt.txt")
VIEWS = (("正面", "正面_00001_.png"), ("左侧", "左侧_00001_.png"),
         ("背面", "背面_00001_.png"), ("右侧", "右侧_00001_.png"))


def fit(image: Image.Image) -> Image.Image:
    max_size = int(CELL * 0.92)
    scale = min(max_size / image.width, max_size / image.height)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    image = image.resize(size, Image.LANCZOS)
    cell = Image.new("RGB", (CELL, CELL), "#FFFFFF")
    cell.paste(image, ((CELL - size[0]) // 2, (CELL - size[1]) // 2))
    return cell


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    sheet = Image.new("RGB", (CELL * 2, CELL * 2), "#FFFFFF")
    for index, (label, name) in enumerate(VIEWS):
        path = SRC / name
        if not path.exists():
            raise SystemExit(f"missing: {path}")
        cell = fit(Image.open(path).convert("RGB"))
        cell.save(OUT / f"{label}.png")
        row, col = divmod(index, 2)
        sheet.paste(cell, (col * CELL, row * CELL))
    sheet.save(OUT / "地台四视图.png")
    preview = sheet.copy()
    preview.thumbnail((1400, 1400), Image.LANCZOS)
    preview.save(OUT / "地台四视图-preview.jpg", quality=90)
    if PROMPT_SRC.exists():
        shutil.copyfile(PROMPT_SRC, OUT / "base-prompt.txt")
    print("saved:", OUT, sheet.size)


if __name__ == "__main__":
    main()
