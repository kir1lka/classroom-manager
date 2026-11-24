"""High-clarity off-thread multi-monitor screen capture and JPEG encoding."""

from __future__ import annotations

import io
from typing import Any

import mss
from PIL import Image, ImageDraw, ImageGrab


def list_monitors() -> list[dict[str, Any]]:
    """Return metadata for all physical monitors (1..N) plus virtual desktop summary."""
    result: list[dict[str, Any]] = []
    try:
        with mss.MSS() as sct:
            # sct.monitors[0] is the combined virtual desktop; 1..N are individual displays
            for idx, mon in enumerate(sct.monitors[1:], start=1):
                result.append(
                    {
                        "index": idx,
                        "name": f"Монитор {idx} ({mon['width']}×{mon['height']})",
                        "left": int(mon["left"]),
                        "top": int(mon["top"]),
                        "width": int(mon["width"]),
                        "height": int(mon["height"]),
                    }
                )
    except Exception:
        pass

    if not result:
        result.append(
            {
                "index": 1,
                "name": "Монитор 1 (1920×1080)",
                "left": 0,
                "top": 0,
                "width": 1920,
                "height": 1080,
            }
        )
    return result


def get_monitor_rect(monitor_index: int = 1) -> tuple[int, int, int, int]:
    """Return (left, top, width, height) of the requested monitor (0 = all monitors)."""
    try:
        with mss.MSS() as sct:
            if monitor_index == 0:
                m = sct.monitors[0]
            elif 1 <= monitor_index < len(sct.monitors):
                m = sct.monitors[monitor_index]
            else:
                m = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            return int(m["left"]), int(m["top"]), int(m["width"]), int(m["height"])
    except Exception:
        return 0, 0, 1920, 1080


def _make_placeholder_image(width: int, height: int) -> Image.Image:
    """Render a clean placeholder image when GDI capture is unavailable (e.g. Lock/UAC)."""
    img = Image.new("RGB", (max(320, width), max(180, height)), color=(18, 18, 18))
    draw = ImageDraw.Draw(img)
    draw.rectangle([4, 4, img.width - 5, img.height - 5], outline=(42, 42, 42), width=2)
    draw.text((20, img.height // 2 - 10), "Screen unavailable (Windows Lock / UAC)", fill=(160, 160, 160))
    return img


def capture_screen_jpeg(
    target_width: int = 480,
    quality: int = 85,
    monitor_index: int = 1,
) -> tuple[int, int, bytes]:
    """Capture the selected monitor and return (orig_width, orig_height, crisp_jpeg_bytes).

    Uses 4:4:4 chroma (subsampling=0) for high quality so text and UI stay razor sharp.
    """
    img: Image.Image | None = None
    orig_w, orig_h = 1920, 1080

    # Tier 1: Fast mss.MSS capture on the chosen monitor (0 = all displays, 1..N = specific monitor)
    try:
        with mss.MSS() as sct:
            if monitor_index == 0:
                monitor = sct.monitors[0]
            elif 1 <= monitor_index < len(sct.monitors):
                monitor = sct.monitors[monitor_index]
            else:
                monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            shot = sct.grab(monitor)
            orig_w, orig_h = shot.size
            img = Image.frombytes("RGB", shot.size, shot.rgb)
    except Exception:
        img = None

    # Tier 2: Pillow ImageGrab fallback
    if img is None:
        try:
            grabbed = ImageGrab.grab(all_screens=(monitor_index == 0))
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
        # LANCZOS preserves crisp edges on UI text and code
        resample = Image.Resampling.LANCZOS if target_width >= 720 else Image.Resampling.BILINEAR
        img = img.resize((target_width, new_h), resample)

    q = max(30, min(98, int(quality)))
    # Disable chroma subsampling (4:4:4) for high-quality streams so small text never blurs
    subsampling = 0 if q >= 80 else 2
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=q, subsampling=subsampling, optimize=False)
    return orig_w, orig_h, buf.getvalue()
