"""Chapter-opener art.

generate_opener() produces a real, varied, book-grade grayscale/duotone background
with PIL (layered ridgelines + horizon light + grain + vignette). It is the
*pluggable slot*: in the hosted product you replace the body of generate_opener()
with a text-to-image API call seeded by `brief_for_chapter()`, and the rest of the
pipeline is unchanged.
"""
import math
import random
from PIL import Image, ImageDraw, ImageFilter, ImageOps, ImageChops


# Maps theme keywords -> the brief that would be sent to an image model / stock search.
_THEME_LIBRARY = [
    (("decision", "choice", "crossroad", "fork"),
     "lone figure at a forked stone path between two valleys, dawn light, cinematic"),
    (("fear", "faith", "fog", "mist"),
     "person standing in misty mountain valley at sunrise, vast and calm, atmospheric"),
    (("action", "climb", "imperative", "do"),
     "rock climber silhouetted on a cliff face against bright sky, dramatic backlight"),
    (("story", "rewrit", "star", "night"),
     "figure painting light across a starry night sky over still water, surreal"),
    (("impossib", "mountain", "summit", "peak"),
     "climber on a sharp snow summit above the clouds, monumental scale"),
    (("struggle", "embrace", "everest"),
     "tiny climber ascending a vast snow ridge toward a glowing peak"),
    (("enough", "worth", "victory"),
     "silhouette of a person arms raised on a hill in soft fog, triumphant"),
    (("momentum", "now", "fly", "move"),
     "paper airplanes soaring upward through bright clouds, motion and lift"),
    (("lie", "told", "begin", "start"),
     "hiker on a ridge looking out over distant mountain ranges at first light"),
]


def brief_for_chapter(title: str, number: int) -> str:
    t = title.lower()
    for keys, brief in _THEME_LIBRARY:
        if any(k in t for k in keys):
            return brief
    return _THEME_LIBRARY[(number - 1) % len(_THEME_LIBRARY)][1]


# ---- procedural renderer ---------------------------------------------------

def _ridgeline(draw, w, h, base_y, roughness, shade, seed):
    """Midpoint-displacement mountain ridge filled to the bottom."""
    rnd = random.Random(seed)
    pts = [(0, base_y + rnd.uniform(-30, 30)), (w, base_y + rnd.uniform(-30, 30))]
    disp = roughness
    for _ in range(7):
        new = [pts[0]]
        for i in range(len(pts) - 1):
            (x1, y1), (x2, y2) = pts[i], pts[i + 1]
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2 + rnd.uniform(-disp, disp)
            new.append((mx, my)); new.append(pts[i + 1])
        pts = new
        disp *= 0.55
    poly = pts + [(w, h), (0, h)]
    draw.polygon(poly, fill=shade)


def generate_opener(out_path: str, w_px: int, h_px: int, seed: int, mode: str = "grayscale"):
    rnd = random.Random(seed)
    img = Image.new("L", (w_px, h_px), 0)

    # sky: vertical gradient, brightest near the horizon band
    horizon = int(h_px * rnd.uniform(0.52, 0.66))
    sky = Image.new("L", (1, h_px))
    for y in range(h_px):
        d = abs(y - horizon) / max(horizon, h_px - horizon)
        val = int(238 - 150 * min(d * 1.25, 1.0))          # light at horizon -> dark away
        sky.putpixel((0, y), max(28, val))
    img.paste(sky.resize((w_px, h_px)), (0, 0))

    # horizon glow
    glow = Image.new("L", (w_px, h_px), 0)
    gd = ImageDraw.Draw(glow)
    gx = int(w_px * rnd.uniform(0.3, 0.7))
    gd.ellipse([gx - w_px*0.5, horizon - h_px*0.18, gx + w_px*0.5, horizon + h_px*0.10], fill=255)
    glow = glow.filter(ImageFilter.GaussianBlur(w_px * 0.10))
    img = ImageChops.lighter(img, glow.point(lambda p: int(p * 0.55)))

    # layered ridges, far (light) to near (dark)
    draw = ImageDraw.Draw(img)
    layers = rnd.randint(3, 4)
    for i in range(layers):
        t = i / max(layers - 1, 1)
        base_y = int(horizon + t * (h_px - horizon) * 0.85)
        shade = int(150 - t * 138)                          # far ridges paler
        _ridgeline(draw, w_px, h_px, base_y, roughness=h_px * (0.06 + 0.05 * (1 - t)),
                   shade=shade, seed=seed * 13 + i)

    # tiny summit marker (flag / figure) on the nearest ridge sometimes
    if rnd.random() < 0.6:
        fx = int(w_px * rnd.uniform(0.62, 0.82))
        fy = int(horizon + (h_px - horizon) * 0.18)
        draw.line([(fx, fy), (fx, fy - h_px*0.05)], fill=235, width=max(2, w_px // 600))
        draw.polygon([(fx, fy - h_px*0.05), (fx + w_px*0.025, fy - h_px*0.04),
                      (fx, fy - h_px*0.03)], fill=235)

    # film grain
    grain = Image.effect_noise((w_px, h_px), 16).point(lambda p: int((p - 128) * 0.5 + 128))
    img = Image.blend(img, ImageChops_safe_multiply(img, grain), 0.12)

    # vignette
    vig = Image.new("L", (w_px, h_px), 0)
    ImageDraw.Draw(vig).ellipse([-w_px*0.25, -h_px*0.25, w_px*1.25, h_px*1.25], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(w_px * 0.12))
    img = ImageChops_safe_multiply(img, vig)

    out = img
    if mode == "duotone":
        out = _duotone(img, (12, 16, 40), (228, 230, 246))   # indigo duotone
    elif mode == "color":
        out = img.convert("RGB")
    else:
        out = img.convert("RGB")
    out.save(out_path, "JPEG", quality=88, dpi=(300, 300))


def _duotone(gray: Image.Image, dark, light) -> Image.Image:
    lut = []
    for ch in range(3):
        lut += [int(dark[ch] + (light[ch] - dark[ch]) * (i / 255)) for i in range(256)]
    return gray.convert("L").convert("RGB").point(lut)


def ImageChops_safe_multiply(a: Image.Image, b: Image.Image) -> Image.Image:
    from PIL import ImageChops
    return ImageChops.multiply(a.convert("L"), b.convert("L"))
