# -*- coding: utf-8 -*-
"""
make_icon.py - MEPANANA Standard Icon Generator
ROOT BENCHMARK: Schedule Link (SL) -> H=160px | Y=50-210 | Slim/Condensed Aspect Ratio

ALGORITHM:
  1. Render glyphs at master font size (220pt for pushbutton, 150pt for stack).
  2. Squeeze width horizontally (default factor 0.80) for a modern, slim/condensed look.
  3. Height is strictly preserved (160px for PushButton, 107px for StackButton).
  4. Paste onto 256x256 7-stop spectrum gradient canvas, centered horizontally and vertically in the ribbon slot.

Usage:
  py lib/py/make_icon.py "SM" "path/to/icon.png"
  py lib/py/make_icon.py "PD" "path/to/icon.png" --stack
"""
import os, sys
from PIL import Image, ImageDraw, ImageFont

# 7-Stop Master Spectrum Gradient (Left -> Right, X=0 -> X=255)
STOPS = [
    (0.00, (0x15, 0xC2, 0x7D)),   # Emerald Green
    (0.18, (0x20, 0xCB, 0x66)),   # Bright Green
    (0.35, (0x55, 0xC0, 0x46)),   # Lime Green
    (0.50, (0xB4, 0xBC, 0x1E)),   # Yellow-Lime
    (0.65, (0xEB, 0xBF, 0x13)),   # Gold
    (0.80, (0xF4, 0x87, 0x12)),   # Amber Orange
    (1.00, (0xF0, 0x4A, 0x3C)),   # Fiery Red
]

def _lerp(c1, c2, t):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))

def _gc(pos):
    for i in range(len(STOPS) - 1):
        p0, c0 = STOPS[i]; p1, c1 = STOPS[i + 1]
        if p0 <= pos <= p1:
            return _lerp(c0, c1, (pos - p0) / (p1 - p0))
    return STOPS[-1][1]

def _build_gradient(size=256):
    img = Image.new("RGBA", (size, size))
    d   = ImageDraw.Draw(img)
    for x in range(size):
        c = _gc(x / (size - 1))
        d.line([(x, 0), (x, size)], fill=c + (255,))
    return img

def _font_path():
    windir = os.environ.get("WINDIR", r"C:\Windows")
    for name in ("segoeuib.ttf", "arialbd.ttf", "arial.ttf"):
        p = os.path.join(windir, "Fonts", name)
        if os.path.exists(p):
            return p
    raise RuntimeError("No suitable bold font found in Windows Fonts.")

def _measure(ch, font):
    """Return (ink_w, ink_h, left_bearing, top_bearing)."""
    tmp = Image.new("L", (1200, 1200), 0)
    ImageDraw.Draw(tmp).text((300, 300), ch, fill=255, font=font)
    b = tmp.getbbox()
    if not b:
        return 0, 0, 0, 0
    return b[2]-b[0], b[3]-b[1], b[0]-300, b[1]-300


def generate_mepanana_icon(text, output_path, is_stack=False, squeeze_factor=0.80):
    """
    PushButton standard : H=160px (Y=50..210)  |  Font=220pt  |  GAP=8px  |  Squeeze=0.80
    StackButton standard: H=107px (Y=74..181)  |  Font=150pt  |  GAP=5px  |  Squeeze=0.80
    """
    SIZE     = 256
    TARGET_H = 107 if is_stack else 160
    Y_TOP    = 74  if is_stack else 50
    GAP      = 5   if is_stack else 8
    FONT_PT  = 150 if is_stack else 220

    fp       = _font_path()
    font     = ImageFont.truetype(fp, FONT_PT)
    gradient = _build_gradient(SIZE)

    glyphs = [(ch, *_measure(ch, font)) for ch in text]
    tot_w  = sum(g[1] for g in glyphs) + GAP * (len(text) - 1)

    PAD = 60
    mask_big = Image.new("L", (tot_w + PAD * 2, TARGET_H + PAD * 2), 0)
    d_big    = ImageDraw.Draw(mask_big)
    cx = PAD
    for ch, w, h, lb, tb in glyphs:
        d_big.text((cx - lb, PAD - tb), ch, fill=255, font=font)
        cx += w + GAP

    bb = mask_big.getbbox()
    cropped = mask_big.crop(bb) if bb else mask_big

    # Squeeze width to give a modern, slim/condensed aspect ratio
    new_w = int(cropped.width * squeeze_factor)
    new_h = TARGET_H
    resized = cropped.resize((new_w, new_h), Image.LANCZOS)

    paste_x = (SIZE - new_w) // 2
    paste_y = Y_TOP

    patch = gradient.crop((paste_x, paste_y, paste_x + new_w, paste_y + new_h))
    out   = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    out.paste(patch, (paste_x, paste_y), resized)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    out.save(output_path, "PNG")

    final_bb = out.getbbox()
    if final_bb:
        print(
            f"[make_icon] '{text}' -> "
            f"BBox({final_bb[0]},{final_bb[1]},{final_bb[2]},{final_bb[3]}) "
            f"W={final_bb[2]-final_bb[0]}px H={final_bb[3]-final_bb[1]}px "
            f"(slim factor={squeeze_factor:.2f}) -> {os.path.basename(output_path)}"
        )
    return out


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: py lib/py/make_icon.py <TEXT> <OUTPUT_PATH> [--stack] [--squeeze <float>]")
        sys.exit(1)
    
    txt = sys.argv[1]
    out = sys.argv[2]
    is_stk = "--stack" in sys.argv
    
    sq = 0.80
    if "--squeeze" in sys.argv:
        idx = sys.argv.index("--squeeze")
        if idx + 1 < len(sys.argv):
            sq = float(sys.argv[idx + 1])
            
    generate_mepanana_icon(txt, out, is_stack=is_stk, squeeze_factor=sq)
