"""Chunked file receiver with SHA-256 integrity check and preset Windows folders."""

from __future__ import annotations

import hashlib
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO

logger = logging.getLogger("classroom_manager.student.files")


def resolve_destination_dir(dest_spec: str) -> Path:
    """Resolve preset tokens (@desktop, @downloads, @documents, @public_desktop) or custom path."""
    spec = (dest_spec or "@desktop").strip()
    home = Path.home()

    presets = {
        "@desktop": home / "Desktop",
        "@downloads": home / "Downloads",
        "@documents": home / "Documents",
        "@public_desktop": Path(os.environ.get("PUBLIC", str(home))) / "Desktop",
    }
    lower = spec.lower()
    if lower in presets:
        target = presets[lower]
    else:
        expanded = os.path.expandvars(os.path.expanduser(spec))
        target = Path(expanded)

    target.mkdir(parents=True, exist_ok=True)
    return target


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    for idx in range(1, 10000):
        candidate = parent / f"{stem} ({idx}){suffix}"
        if not candidate.exists():
            return candidate
    return path


@dataclass
class _ActiveTransfer:
    transfer_id: str
    final_path: Path
    part_path: Path
    expected_size: int
    expected_sha256: str
    overwrite: bool
    open_after: bool
    fh: BinaryIO
    hasher: Any = field(default_factory=hashlib.sha256)
    received: int = 0


class FileTransferReceiver:
    """Manages concurrent incoming chunked file transfers from the Teacher server."""

    def __init__(self) -> None:
        self._active: dict[str, _ActiveTransfer] = {}

    def start_transfer(self, meta: dict[str, Any]) -> dict[str, Any] | None:
        """Open temp file for an incoming transfer; returns error dict immediately if setup fails."""
        transfer_id = str(meta.get("transfer_id", ""))
        raw_name = str(meta.get("filename", "")).strip()
        safe_name = Path(raw_name).name
        if not transfer_id or not safe_name or safe_name in (".", ".."):
            return {"transfer_id": transfer_id, "ok": False, "error": "Некорректное имя файла"}

        dest_dir_spec = str(meta.get("dest_dir") or "@desktop")
        expected_size = int(meta.get("size", 0))
        expected_sha256 = str(meta.get("sha256", "")).lower()
        overwrite = bool(meta.get("overwrite", True))
        open_after = bool(meta.get("open_after", False))

        try:
            dest_dir = resolve_destination_dir(dest_dir_spec)
            final_path = dest_dir / safe_name
            if not overwrite:
                final_path = _unique_path(final_path)
            part_path = dest_dir / f".{safe_name}.{transfer_id[:8]}.part"
            fh = part_path.open("wb")
        except OSError as exc:
            logger.warning("Cannot prepare destination '%s': %s", dest_dir_spec, exc)
            return {"transfer_id": transfer_id, "ok": False, "error": f"Нет доступа к папке: {exc}"}

        self._active[transfer_id] = _ActiveTransfer(
            transfer_id=transfer_id,
            final_path=final_path,
            part_path=part_path,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
            overwrite=overwrite,
            open_after=open_after,
            fh=fh,
        )
        return None

    def write_chunk(self, transfer_id: str, chunk: bytes) -> None:
        tx = self._active.get(transfer_id)
        if tx is None:
            return
        tx.fh.write(chunk)
        tx.hasher.update(chunk)
        tx.received += len(chunk)

    def finish_transfer(self, transfer_id: str) -> dict[str, Any]:
        tx = self._active.pop(transfer_id, None)
        if tx is None:
            return {"transfer_id": transfer_id, "ok": False, "error": "Передача не найдена"}

        try:
            tx.fh.close()
        except OSError:
            pass

        if tx.expected_size and tx.received != tx.expected_size:
            self._remove_quiet(tx.part_path)
            return {
                "transfer_id": transfer_id,
                "ok": False,
                "error": f"Несовпадение размера ({tx.received} из {tx.expected_size} байт)",
            }

        actual_hash = tx.hasher.hexdigest().lower()
        if tx.expected_sha256 and actual_hash != tx.expected_sha256:
            self._remove_quiet(tx.part_path)
            return {"transfer_id": transfer_id, "ok": False, "error": "Ошибка контрольной суммы SHA-256"}

        try:
            target = tx.final_path if tx.overwrite else _unique_path(tx.final_path)
            tx.part_path.replace(target)
        except OSError as exc:
            self._remove_quiet(tx.part_path)
            return {"transfer_id": transfer_id, "ok": False, "error": f"Не удалось сохранить файл: {exc}"}

        logger.info("Saved incoming file from teacher: %s (%d bytes)", target, tx.received)

        if tx.open_after and sys.platform == "win32":
            try:
                os.startfile(str(target))
            except OSError as exc:
                logger.debug("Could not auto-open file %s: %s", target, exc)

        return {
            "transfer_id": transfer_id,
            "ok": True,
            "saved_path": str(target),
            "bytes": tx.received,
        }

    def cleanup_all(self) -> None:
        for tx in list(self._active.values()):
            try:
                tx.fh.close()
            except OSError:
                pass
            self._remove_quiet(tx.part_path)
        self._active.clear()

    @staticmethod
    def _remove_quiet(path: Path) -> None:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass
