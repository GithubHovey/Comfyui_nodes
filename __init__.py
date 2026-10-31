"""
save-near-input
两个节点：
  LoadImageWithDir  —— 和内置 Load Image 一样，但多输出一个「图片所在目录」字符串
  SaveImageToDir    —— 把图片保存到指定目录（可传入上面那个目录），同时可选在 output 留一份预览

用法：LoadImageWithDir.image_dir -> SaveImageToDir.image_dir
"""

import os
import json
import hashlib
import numpy as np
import torch
from PIL import Image, ImageOps, PngImagePlugin

import folder_paths


class LoadImageWithDir:
    @classmethod
    def INPUT_TYPES(s):
        input_dir = folder_paths.get_input_directory()
        try:
            files = [
                f for f in os.listdir(input_dir)
                if os.path.isfile(os.path.join(input_dir, f))
            ]
        except Exception:
            files = []
        return {"required": {"image": (sorted(files), {"image_upload": True})}}

    CATEGORY = "image"
    RETURN_TYPES = ("IMAGE", "MASK", "STRING")
    RETURN_NAMES = ("image", "mask", "image_dir")
    FUNCTION = "load_image"

    def load_image(self, image):
        image_path = folder_paths.get_annotated_filepath(image)
        img = Image.open(image_path)
        img = ImageOps.exif_transpose(img)

        if img.mode == "I":
            img = img.point(lambda i: i * (1 / 255))

        rgb = img.convert("RGB")
        arr = np.array(rgb).astype(np.float32) / 255.0
        image_out = torch.from_numpy(arr)[None,]

        if "A" in img.getbands():
            mask = np.array(img.getchannel("A")).astype(np.float32) / 255.0
            mask = 1.0 - torch.from_numpy(mask)
        else:
            mask = torch.zeros((64, 64), dtype=torch.float32)

        return (image_out, mask.unsqueeze(0), os.path.dirname(image_path))

    @classmethod
    def IS_CHANGED(s, image):
        image_path = folder_paths.get_annotated_filepath(image)
        m = hashlib.sha256()
        with open(image_path, "rb") as f:
            m.update(f.read())
        return m.digest().hex()

    @classmethod
    def VALIDATE_INPUTS(s, image):
        if not folder_paths.exists_annotated_filepath(image):
            return "Invalid image file: {}".format(image)
        return True


class SaveImageToDir:
    def __init__(self):
        self.output_dir = folder_paths.get_output_directory()
        self.compress_level = 4

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "images": ("IMAGE",),
                "image_dir": ("STRING", {"default": ""}),
                "filename_prefix": ("STRING", {"default": "output"}),
                "keep_preview_in_output": ("BOOLEAN", {"default": True}),
            },
            "hidden": {
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }

    CATEGORY = "image"
    RETURN_TYPES = ()
    FUNCTION = "save"
    OUTPUT_NODE = True

    def _pnginfo(self, prompt, extra_pnginfo):
        meta = PngImagePlugin.PngInfo()
        if prompt is not None:
            meta.add_text("prompt", json.dumps(prompt))
        if extra_pnginfo is not None:
            for k, v in extra_pnginfo.items():
                meta.add_text(k, json.dumps(v))
        return meta

    def save(self, images, image_dir, filename_prefix, keep_preview_in_output=True,
             prompt=None, extra_pnginfo=None):
        target = (image_dir or "").strip().strip('"')
        if not target:
            target = self.output_dir

        try:
            os.makedirs(target, exist_ok=True)
        except Exception as e:
            print("[save-near-input] 无法创建目录 %s: %s" % (target, e))
            target = self.output_dir

        results = []
        for image in images:
            i = 255.0 * image.cpu().numpy()
            img = Image.fromarray(np.clip(i, 0, 255).astype(np.uint8))
            info = self._pnginfo(prompt, extra_pnginfo)

            # 递增编号，避免覆盖
            idx = 1
            while True:
                name = "%s_%05d_.png" % (filename_prefix, idx)
                path = os.path.join(target, name)
                if not os.path.exists(path):
                    break
                idx += 1

            img.save(path, pnginfo=info, compress_level=self.compress_level)
            print("[save-near-input] saved -> %s" % path)

            if keep_preview_in_output:
                sub = "near-input-preview"
                out_folder = os.path.join(self.output_dir, sub)
                os.makedirs(out_folder, exist_ok=True)
                img.save(os.path.join(out_folder, name), pnginfo=info,
                         compress_level=self.compress_level)
                results.append({"filename": name, "subfolder": sub, "type": "output"})

        return {"ui": {"images": results}}


NODE_CLASS_MAPPINGS = {
    "LoadImageWithDir": LoadImageWithDir,
    "SaveImageToDir": SaveImageToDir,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LoadImageWithDir": "Load Image (with dir)",
    "SaveImageToDir": "Save Image to Dir",
}
