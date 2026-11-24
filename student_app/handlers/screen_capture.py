"""Fast off-thread screen capture and JPEG compression with graceful lock-screen fallback."""

from __future__ import annotations

import io

import mss
from PIL import Image, ImageDraw, ImageGrab


def _make_placeholder_image(width: int, height: int) -> Image.Image:
    """Render a clean placeholder image when GDI screen capture is unavailable (e.g. Windows Lock/UAC)."""
    img = Image.new("RGB", (max(320, width), max(180, height)), color=(15, 23, 42))
    draw = ImageDraw.Draw(img)
    draw.rectangle([4, 4, img.width - 5, img.height - 5], outline=(51, 65, 85), width=2)
    draw.text((20, img.height // 2 - 10), "Screen unavailable (Windows Lock / UAC)", fill=(148, 163, 184))
    return img


def capture_screen_jpeg(target_width: int = 360, quality: int = 55) -> tuple[int, int, bytes]:
    """Capture primary monitor and return (orig_width, orig_height, jpeg_bytes)."""
    img: Image.Image | None = None
    orig_w, orig_h = 1920, 1080

    # Tier 1: Fast mss.MSS capture
    try:
        with mss.MSS() as sct:
            monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            shot = sct.grab(monitor)
            orig_w, orig_h = shot.size
            img = Image.frombytes("RGB", shot.size, shot.rgb)
    except Exception:
        img = None

    # Tier 2: Pillow ImageGrab fallback
    if img is None:
        try:
            grabbed = ImageGrab.grab()
            orig_w, orig_h = grabbed.size
            img = grabbed.convert("RGB")
        except Exception:
            img = None

    # Tier 3: Graceful placeholder (Windows Lock Screen / UAC / headless session)
    if img is None:
        w = target_width if target_width > 0 else 640
        h = max(180, int(w * 9 / 16))
        img = _make_placeholder_image(w, h)
        orig_w, orig_h = 1920, 1080
    elif target_width > 0 and orig_w > target_width:
        scale = target_width / float(orig_w)
        new_h = max(1, int(orig_h * scale))
        img = img.resize((target_width, new_h), Image.Resampling.BILINEAR)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=max(20, min(95, quality)), optimize=False)
    return orig_w, orig_h, buf.getvalue()
