import math

import numpy as np
import torch
from PIL import Image, ImageChops, ImageDraw, ImageFilter
from scipy import ndimage

VIEWS = ("front", "left", "back", "right")


def _tensor_to_pil(image, mask):
    rgb = (image[0].detach().cpu().numpy() * 255.0).clip(0, 255).astype(np.uint8)
    alpha = (mask[0].detach().cpu().numpy() * 255.0).clip(0, 255).astype(np.uint8)
    return Image.fromarray(rgb).convert("RGB"), Image.fromarray(alpha).convert("L")


def _clean_mask(mask):
    """Keep the subject, drop detached UI icons, effect bubbles and ground shadows."""
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
        size = float(sizes[index - 1])
        if size < float(sizes.max()) * 0.005:
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


def _cutout(image, mask):
    mask = _clean_mask(mask)
    box = mask.getbbox()
    if box is None:
        raise ValueError("background removal returned an empty mask")
    image = image.crop(box)
    mask = mask.crop(box).filter(ImageFilter.GaussianBlur(0.7))
    return image, mask


def _scale_to_height(image, mask, height):
    height = max(8, int(round(height)))
    width = max(1, int(round(image.width * height / image.height)))
    return image.resize((width, height), Image.LANCZOS), mask.resize((width, height), Image.LANCZOS)


def _trim_bottom(image, mask, ratio):
    """Drop the thin clear acrylic disc the figurine render likes to add."""
    cut = int(round(image.height * max(0.0, ratio)))
    if cut <= 0:
        return image, mask
    width, height = image.size
    bottom = max(8, height - cut)
    return image.crop((0, 0, width, bottom)), mask.crop((0, 0, width, bottom))


def _grass_texture(size, rng):
    array = np.zeros((size[1], size[0], 4), dtype=np.uint8)
    base = np.array([104, 132, 70], dtype=np.int16)
    noise = rng.normal(0, 10, (size[1], size[0], 1))
    array[..., :3] = np.clip(base + noise, 0, 255).astype(np.uint8)
    array[..., 3] = 255
    return Image.fromarray(array, "RGBA")


def _dirt_texture(size, rng):
    array = np.zeros((size[1], size[0], 4), dtype=np.uint8)
    base = np.array([96, 70, 48], dtype=np.int16)
    noise = rng.normal(0, 8, (size[1], size[0], 1))
    array[..., :3] = np.clip(base + noise, 0, 255).astype(np.uint8)
    array[..., 3] = 255
    return Image.fromarray(array, "RGBA")


def _paste_texture(layer, box, texture, width, height):
    mask = Image.new("L", layer.size, 0)
    ImageDraw.Draw(mask).ellipse([int(round(v)) for v in box], fill=255)
    patch = texture.resize((max(1, int(round(width))), max(1, int(round(height)))), Image.LANCZOS)
    patch = patch.resize(layer.size, Image.LANCZOS)
    layer.paste(patch, (0, 0), mask)


def _draw_shadow(canvas, x, y, width, alpha):
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    half = width / 2.0
    draw.ellipse([x - half, y - width * 0.045, x + half, y + width * 0.045],
                 fill=(38, 33, 28, int(alpha)))
    layer = layer.filter(ImageFilter.GaussianBlur(max(2, width * 0.03)))
    canvas.alpha_composite(layer)


def _draw_rock(layer, x, ground_y, width, height):
    draw = ImageDraw.Draw(layer)
    points = [
        (x - width * 0.50, ground_y),
        (x - width * 0.42, ground_y - height * 0.55),
        (x - width * 0.16, ground_y - height * 0.96),
        (x + width * 0.20, ground_y - height * 0.88),
        (x + width * 0.48, ground_y - height * 0.42),
        (x + width * 0.52, ground_y),
    ]
    draw.polygon([(int(round(a)), int(round(b))) for a, b in points], fill=(122, 118, 110, 255))
    draw.polygon([
        (int(round(x - width * 0.30)), int(round(ground_y - height * 0.62))),
        (int(round(x - width * 0.10)), int(round(ground_y - height * 0.88))),
        (int(round(x + width * 0.10)), int(round(ground_y - height * 0.70))),
        (int(round(x - width * 0.04)), int(round(ground_y - height * 0.46))),
    ], fill=(144, 140, 132, 255))
    return ground_y - height * 0.9


def _compose_view(view, subjects, cfg, rng, pad, draw_order="depth"):
    width = cfg["canvas_width"]
    height = cfg["canvas_height"]
    canvas = Image.new("RGBA", (width + 2 * pad, height + 2 * pad), (255, 255, 255, 255))

    char_px = height * cfg["char_height_ratio"]
    px_per_cm = char_px / max(cfg["char_height_cm"], 0.1)
    radius = char_px * cfg["base_diameter_ratio"] / 2.0
    pitch = math.radians(cfg["pitch_deg"])
    ry = radius * math.sin(pitch)
    side_h = cfg["base_thickness_cm"] * px_per_cm * math.cos(pitch)

    cx = pad + width / 2.0
    bottom = pad + height * 0.93
    top_cy = bottom - side_h - ry

    left = cx - radius
    right = cx + radius
    top_box = (left, top_cy - ry, right, top_cy + ry)
    side_bottom = top_cy + ry + side_h

    base_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(base_layer)
    sd.rectangle([int(left), int(top_cy), int(right), int(side_bottom)], fill=(92, 68, 46, 255))
    sd.ellipse([int(left), int(side_bottom - ry), int(right), int(side_bottom + ry)],
               fill=(74, 54, 36, 255))
    base_layer.putalpha(base_layer.getchannel("A").filter(ImageFilter.GaussianBlur(0.6)))
    _paste_texture(base_layer, top_box, _grass_texture((int(2 * radius) + 8, int(2 * ry) + 8), rng),
                   2 * radius, 2 * ry)
    ImageDraw.Draw(base_layer).arc(top_box, 0, 360, fill=(78, 102, 54, 255),
                                   width=max(2, int(radius * 0.018)))

    angle = {"front": 0.0, "left": math.pi / 2, "back": math.pi, "right": 3 * math.pi / 2}[view]
    cos_a, sin_a = math.cos(angle), math.sin(angle)

    def project(x_cm, z_cm):
        screen_x = cx + (x_cm * cos_a - z_cm * sin_a) * px_per_cm
        depth = x_cm * sin_a + z_cm * cos_a
        ground_y = top_cy + depth * px_per_cm * math.sin(pitch)
        return screen_x, ground_y, depth

    char_x, char_y, char_depth = project(cfg["char_x_cm"], cfg["char_z_cm"])
    spirit_x, spirit_y, spirit_depth = project(cfg["spirit_x_cm"], cfg["spirit_z_cm"])

    rock_h = cfg["mound_cm"] * px_per_cm
    spirit_contact = _draw_rock(base_layer, spirit_x, spirit_y, char_px * 0.22, rock_h)
    canvas.alpha_composite(base_layer)
    _draw_shadow(canvas, spirit_x, spirit_contact + rock_h * 0.03, char_px * 0.18,
                 cfg["shadow_strength"] * 255)
    _draw_shadow(canvas, char_x, char_y + 2, char_px * 0.42, cfg["shadow_strength"] * 255)

    placed = []
    for name, screen_x, contact_y, depth in (
        ("char", char_x, char_y, char_depth),
        ("spirit", spirit_x, spirit_contact, spirit_depth),
    ):
        image, mask = subjects[name]
        placed.append((name, depth, image, mask, screen_x, contact_y))

    if draw_order == "character_on_top":
        placed.sort(key=lambda item: (item[0] == "char", item[1]))
    elif draw_order == "spirit_on_top":
        placed.sort(key=lambda item: (item[0] == "spirit", item[1]))
    else:
        placed.sort(key=lambda item: item[1])

    subject_mask = Image.new("L", canvas.size, 0)
    for _, _, image, mask, screen_x, contact_y in placed:
        paste_x = int(round(screen_x - image.width / 2.0))
        paste_y = int(round(contact_y - image.height))
        canvas.paste(image, (paste_x, paste_y), mask)
        subject_mask.paste(mask, (paste_x, paste_y))

    base_alpha = base_layer.getchannel("A").filter(ImageFilter.MinFilter(5))
    subject_dilated = subject_mask.filter(ImageFilter.MaxFilter(7))
    base_mask = ImageChops.subtract(base_alpha, subject_dilated)
    base_mask = base_mask.filter(ImageFilter.GaussianBlur(1.5))
    return canvas, base_mask


def _content_bbox(canvas):
    gray = canvas.convert("L")
    mask = gray.point(lambda value: 255 if value < 250 else 0)
    return mask.getbbox()


def _fit_for(views, cfg, pad):
    width = cfg["canvas_width"]
    height = cfg["canvas_height"]
    cx = pad + width / 2.0
    bottom = pad + height * 0.93
    lefts, rights, tops = [], [], []
    for canvas in views.values():
        box = _content_bbox(canvas)
        if box:
            lefts.append(box[0])
            rights.append(box[2])
            tops.append(box[1])
    if not lefts:
        return 1.0
    half_w = max(cx - min(lefts), max(rights) - cx, 1.0)
    content_h = max(bottom - min(tops), 1.0)
    fit_w = (width * 0.94) / (2.0 * half_w)
    fit_h = (height * 0.91) / content_h
    return min(fit_w, fit_h, 1.0)


def _transform(canvas, mask, fit, cfg, pad):
    width = cfg["canvas_width"]
    height = cfg["canvas_height"]
    cx = pad + width / 2.0
    bottom = pad + height * 0.93
    if fit < 0.999:
        canvas = canvas.resize((max(1, round(canvas.width * fit)),
                                max(1, round(canvas.height * fit))), Image.LANCZOS)
        mask = mask.resize(canvas.size, Image.LANCZOS)
    out = Image.new("RGB", (width, height), (255, 255, 255))
    px = round(width / 2.0 - cx * fit)
    py = round(height * 0.93 - bottom * fit)
    out.paste(canvas, (px, py), canvas)
    out_mask = Image.new("L", (width, height), 0)
    out_mask.paste(mask, (px, py))
    return out, out_mask


def _to_tensor(image):
    array = np.asarray(image).astype(np.float32) / 255.0
    return torch.from_numpy(array)[None]


def _to_mask_tensor(mask):
    array = np.asarray(mask).astype(np.float32) / 255.0
    return torch.from_numpy(array)[None]


class RocoSceneGuide:
    """Build four geometrically consistent composites of a character and a spirit
    on one grass diorama base. The two subjects are placed from a shared world
    layout and projected into front / left / back / right views."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "char_front": ("IMAGE",),
                "char_front_mask": ("MASK",),
                "char_left": ("IMAGE",),
                "char_left_mask": ("MASK",),
                "char_back": ("IMAGE",),
                "char_back_mask": ("MASK",),
                "char_right": ("IMAGE",),
                "char_right_mask": ("MASK",),
                "spirit_front": ("IMAGE",),
                "spirit_front_mask": ("MASK",),
                "spirit_left": ("IMAGE",),
                "spirit_left_mask": ("MASK",),
                "spirit_back": ("IMAGE",),
                "spirit_back_mask": ("MASK",),
                "spirit_right": ("IMAGE",),
                "spirit_right_mask": ("MASK",),
                "canvas_width": ("INT", {"default": 1152, "min": 512, "max": 2048, "step": 16}),
                "canvas_height": ("INT", {"default": 1536, "min": 512, "max": 2048, "step": 16}),
                "char_height_cm": ("FLOAT", {"default": 21.0, "min": 5.0, "max": 60.0, "step": 0.5}),
                "char_height_ratio": ("FLOAT", {"default": 0.78, "min": 0.40, "max": 0.95, "step": 0.01}),
                "spirit_height_ratio": ("FLOAT", {"default": 0.35, "min": 0.10, "max": 3.00, "step": 0.01,
                                                  "tooltip": "精灵身高 / 角色身高。1.0 = 同高，1.5 = 1.5 倍。"}),
                "base_diameter_ratio": ("FLOAT", {"default": 0.70, "min": 0.40, "max": 1.20, "step": 0.01}),
                "base_thickness_cm": ("FLOAT", {"default": 1.4, "min": 0.4, "max": 5.0, "step": 0.1}),
                "char_x_cm": ("FLOAT", {"default": -2.0, "min": -20.0, "max": 20.0, "step": 0.1}),
                "char_z_cm": ("FLOAT", {"default": 0.0, "min": -20.0, "max": 20.0, "step": 0.1}),
                "spirit_x_cm": ("FLOAT", {"default": 4.0, "min": -20.0, "max": 20.0, "step": 0.1}),
                "spirit_z_cm": ("FLOAT", {"default": 4.5, "min": -20.0, "max": 20.0, "step": 0.1}),
                "mound_cm": ("FLOAT", {"default": 1.5, "min": 0.0, "max": 8.0, "step": 0.1}),
                "pitch_deg": ("FLOAT", {"default": 10.0, "min": 0.0, "max": 25.0, "step": 0.5}),
                "spirit_on_character_left": ("BOOLEAN", {"default": True}),
                "shadow_strength": ("FLOAT", {"default": 0.35, "min": 0.0, "max": 1.0, "step": 0.01}),
                "char_bottom_trim": ("FLOAT", {"default": 0.01, "min": 0.0, "max": 0.10, "step": 0.005}),
                "spirit_bottom_trim": ("FLOAT", {"default": 0.03, "min": 0.0, "max": 0.15, "step": 0.005}),
                "draw_order": (["depth", "character_on_top", "spirit_on_top"],
                               {"default": "depth",
                                "tooltip": "depth = 真实 3D 遮挡；character_on_top = 角色永远在最前，适合展示图；spirit_on_top = 精灵永远在最前。"}),
            }
        }

    RETURN_TYPES = ("IMAGE", "IMAGE", "IMAGE", "IMAGE",
                    "MASK", "MASK", "MASK", "MASK")
    RETURN_NAMES = ("front", "left", "back", "right",
                    "front_mask", "left_mask", "back_mask", "right_mask")
    FUNCTION = "compose"
    CATEGORY = "roco"

    def compose(self, char_front, char_front_mask, char_left, char_left_mask,
                char_back, char_back_mask, char_right, char_right_mask,
                spirit_front, spirit_front_mask, spirit_left, spirit_left_mask,
                spirit_back, spirit_back_mask, spirit_right, spirit_right_mask,
                canvas_width, canvas_height, char_height_cm, char_height_ratio,
                spirit_height_ratio, base_diameter_ratio, base_thickness_cm,
                char_x_cm, char_z_cm, spirit_x_cm, spirit_z_cm, mound_cm,
                pitch_deg, spirit_on_character_left, shadow_strength,
                char_bottom_trim=0.01, spirit_bottom_trim=0.03, draw_order="depth"):

        sign = 1.0 if spirit_on_character_left else -1.0
        cfg = {
            "canvas_width": int(canvas_width),
            "canvas_height": int(canvas_height),
            "char_height_cm": float(char_height_cm),
            "char_height_ratio": float(char_height_ratio),
            "base_diameter_ratio": float(base_diameter_ratio),
            "base_thickness_cm": float(base_thickness_cm),
            "char_x_cm": float(char_x_cm) * sign,
            "char_z_cm": float(char_z_cm),
            "spirit_x_cm": float(spirit_x_cm) * sign,
            "spirit_z_cm": float(spirit_z_cm),
            "mound_cm": float(mound_cm),
            "pitch_deg": float(pitch_deg),
            "shadow_strength": float(shadow_strength),
        }

        char_px = cfg["canvas_height"] * cfg["char_height_ratio"]
        spirit_px = char_px * float(spirit_height_ratio)

        char_src = {
            "front": (char_front, char_front_mask),
            "left": (char_left, char_left_mask),
            "back": (char_back, char_back_mask),
            "right": (char_right, char_right_mask),
        }
        spirit_src = {
            "front": (spirit_front, spirit_front_mask),
            "left": (spirit_left, spirit_left_mask),
            "back": (spirit_back, spirit_back_mask),
            "right": (spirit_right, spirit_right_mask),
        }

        pad = int(max(cfg["canvas_width"], cfg["canvas_height"]) * 0.65)
        views, masks = {}, {}
        for view in VIEWS:
            char_img, char_mask = _tensor_to_pil(*char_src[view])
            spirit_img, spirit_mask = _tensor_to_pil(*spirit_src[view])
            char_img, char_mask = _cutout(char_img, char_mask)
            spirit_img, spirit_mask = _cutout(spirit_img, spirit_mask)
            char_img, char_mask = _trim_bottom(char_img, char_mask, char_bottom_trim)
            spirit_img, spirit_mask = _trim_bottom(spirit_img, spirit_mask, spirit_bottom_trim)
            char_img, char_mask = _scale_to_height(char_img, char_mask, char_px)
            spirit_img, spirit_mask = _scale_to_height(spirit_img, spirit_mask, spirit_px)
            subjects = {
                "char": (char_img, char_mask),
                "spirit": (spirit_img, spirit_mask),
            }
            rng = np.random.default_rng(7)
            canvas, base_mask = _compose_view(view, subjects, cfg, rng, pad, draw_order)
            views[view] = canvas
            masks[view] = base_mask

        fit = _fit_for(views, cfg, pad)
        images, out_masks = {}, {}
        for view in VIEWS:
            image, mask = _transform(views[view], masks[view], fit, cfg, pad)
            images[view] = _to_tensor(image)
            out_masks[view] = _to_mask_tensor(mask)

        return (images["front"], images["left"], images["back"], images["right"],
                out_masks["front"], out_masks["left"], out_masks["back"], out_masks["right"])


class RocoSideBlend:
    """Blend a PVC upper body with a no-leg tail lower body.

    The two images must be the same camera and size. The top `cut` fraction comes
    from `pvc`, the rest from `noleg`, with a soft transition. The bottom `trim`
    fraction is cropped to remove the clear acrylic display disc.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "pvc": ("IMAGE",),
                "noleg": ("IMAGE",),
                "cut": ("FLOAT", {"default": 0.60, "min": 0.30, "max": 0.85, "step": 0.01}),
                "blur": ("INT", {"default": 26, "min": 0, "max": 80, "step": 1}),
                "trim": ("FLOAT", {"default": 0.03, "min": 0.0, "max": 0.20, "step": 0.005}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "blend"
    CATEGORY = "roco"

    def blend(self, pvc, noleg, cut, blur, trim):
        pvc_img = _tensor_to_pil(pvc, torch.ones_like(pvc[..., 0]))[0]
        noleg_img = _tensor_to_pil(noleg, torch.ones_like(noleg[..., 0]))[0]
        if pvc_img.size != noleg_img.size:
            pvc_img = pvc_img.resize(noleg_img.size, Image.LANCZOS)
        width, height = noleg_img.size
        cut_px = int(height * float(cut))
        mask = Image.new("L", (width, height), 0)
        ImageDraw.Draw(mask).rectangle([0, 0, width, cut_px], fill=255)
        if blur > 0:
            mask = mask.filter(ImageFilter.GaussianBlur(int(blur)))
        out = noleg_img.copy()
        out.paste(pvc_img, (0, 0), mask)
        crop = int(height * float(trim))
        if crop > 0:
            out = out.crop((0, 0, width, max(8, height - crop)))
        return (_to_tensor(out),)


NODE_CLASS_MAPPINGS = {"RocoSceneGuide": RocoSceneGuide, "RocoSideBlend": RocoSideBlend}
NODE_DISPLAY_NAME_MAPPINGS = {"RocoSceneGuide": "Roco Scene Guide",
                              "RocoSideBlend": "Roco Side Blend"}
