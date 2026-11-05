"""Рисует значок программы «Наушники»: оранжевый фон, белые наушники, лучи-звук."""
import math
from PIL import Image, ImageDraw, ImageFilter

ORANGE_A = (232, 132, 92)   # светлее, сверху
ORANGE_B = (204, 96, 60)    # темнее, снизу
WHITE = (255, 248, 242)


def gradient(size):
    im = Image.new("RGB", (size, size))
    d = ImageDraw.Draw(im)
    for y in range(size):
        t = y / size
        d.line([(0, y), (size, y)], fill=tuple(int(ORANGE_A[i] + (ORANGE_B[i] - ORANGE_A[i]) * t) for i in range(3)))
    return im


def draw_mark(size, color=WHITE, scale=1.0):
    """Белые наушники + 3 луча с каждой стороны на прозрачном слое size×size."""
    S = 4  # рисуем крупнее и уменьшаем — так края гладкие
    W = size * S
    im = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c = W / 2
    k = W * 0.30 * scale  # радиус дуги оголовья
    lw = int(W * 0.055 * scale)
    # оголовье
    d.arc([c - k, c - k * 1.05, c + k, c + k * 0.95], 195, 345, fill=color, width=lw)
    # чашки
    cw, ch = W * 0.13 * scale, W * 0.24 * scale
    for side in (-1, 1):
        x = c + side * (k * 0.93) - cw / 2
        y = c - ch * 0.15
        d.rounded_rectangle([x, y, x + cw, y + ch], radius=cw * 0.45, fill=color)
    # лучи-звук
    for side in (-1, 1):
        for i, ang in enumerate((-28, 0, 28)):
            a = math.radians(ang)
            r0, r1 = k * 1.30, k * (1.55 if i == 1 else 1.47)
            cx, cy = c + side * 0, c + ch * 0.35
            x0 = cx + side * r0 * math.cos(a); y0 = cy + r0 * math.sin(a)
            x1 = cx + side * r1 * math.cos(a); y1 = cy + r1 * math.sin(a)
            d.line([(x0, y0), (x1, y1)], fill=color, width=int(lw * 0.8))
            for (px, py) in ((x0, y0), (x1, y1)):
                rr = lw * 0.4
                d.ellipse([px - rr, py - rr, px + rr, py + rr], fill=color)
    return im.resize((size, size), Image.LANCZOS)


def rounded(im, radius_frac=0.22):
    s = im.size[0]
    m = Image.new("L", (s * 4, s * 4), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, s * 4 - 1, s * 4 - 1], radius=int(s * 4 * radius_frac), fill=255)
    m = m.resize((s, s), Image.LANCZOS)
    out = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    out.paste(im, (0, 0), m)
    return out


def full_icon(size, round_corners=False):
    bg = gradient(size).convert("RGBA")
    # мягкая тень под знаком
    mark = draw_mark(size)
    shadow = Image.new("RGBA", mark.size, (0, 0, 0, 0))
    shadow.putalpha(mark.split()[3].point(lambda a: a * 0.25))
    shadow = shadow.filter(ImageFilter.GaussianBlur(size * 0.015))
    bg.alpha_composite(shadow, (0, int(size * 0.012)))
    bg.alpha_composite(mark)
    return rounded(bg) if round_corners else bg


if __name__ == "__main__":
    import os, sys
    root = sys.argv[1]
    a = os.path.join(root, "mobile", "assets")
    full_icon(1024).convert("RGB").save(os.path.join(a, "icon.png"))
    gradient(1024).save(os.path.join(a, "android-icon-background.png"))
    draw_mark(1024, scale=0.72).save(os.path.join(a, "android-icon-foreground.png"))
    draw_mark(1024, color=(255, 255, 255), scale=0.72).save(os.path.join(a, "android-icon-monochrome.png"))
    draw_mark(1024, color=ORANGE_B, scale=0.9).save(os.path.join(a, "splash-icon.png"))
    full_icon(48, True).save(os.path.join(a, "favicon.png"))
    full_icon(512, True).save(os.path.join(root, "icons", "buds.png"))
    full_icon(128, True).save(os.path.join(root, "icons", "buds-128.png"))
    print("ok")
