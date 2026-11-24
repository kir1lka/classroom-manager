"""Generate crisp multi-DPI Windows .ico and .png application icons for Teacher and Student apps."""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PIL import Image  # noqa: E402
from PySide6.QtCore import QBuffer, QByteArray, QIODevice  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from teacher_app.ui.theme import render_app_icon_pixmap  # noqa: E402

ICO_SIZES: list[tuple[int, int]] = [
    (16, 16),
    (24, 24),
    (32, 32),
    (48, 48),
    (64, 64),
    (128, 128),
    (256, 256),
]


def _pixmap_to_pil(role: str, render_size: int = 512) -> Image.Image:
    pixmap = render_app_icon_pixmap(role, render_size)
    byte_array = QByteArray()
    buffer = QBuffer(byte_array)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not pixmap.save(buffer, "PNG"):
        buffer.close()
        raise RuntimeError(f"Failed to encode QPixmap to PNG for role={role!r}")
    buffer.close()
    return Image.open(io.BytesIO(bytes(byte_array.data()))).convert("RGBA")


def generate_all_icons(assets_dir: Path | None = None) -> dict[str, Path]:
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    _ = app  # keep reference alive during offscreen QPixmap rendering

    out_dir = assets_dir or (PROJECT_ROOT / "assets")
    out_dir.mkdir(parents=True, exist_ok=True)

    generated: dict[str, Path] = {}
    for role in ("teacher", "student"):
        master_512 = _pixmap_to_pil(role, 512)

        png_256 = master_512.resize((256, 256), Image.Resampling.LANCZOS)
        png_path = out_dir / f"{role}_icon.png"
        png_256.save(png_path, format="PNG", optimize=True)

        sub_frames = [
            master_512.resize(sz, Image.Resampling.LANCZOS)
            for sz in ICO_SIZES
            if sz != (256, 256)
        ]
        ico_path = out_dir / f"{role}.ico"
        png_256.save(
            ico_path,
            format="ICO",
            sizes=ICO_SIZES,
            append_images=sub_frames,
        )

        generated[f"{role}_png"] = png_path
        generated[f"{role}_ico"] = ico_path

    return generated


def main() -> None:
    paths = generate_all_icons()
    for label, path in paths.items():
        print(f"[OK] {label}: {path} ({path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
