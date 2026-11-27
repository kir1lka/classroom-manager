"""Configuration persistence for Teacher and Student desktop applications."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TypeVar

T = TypeVar("T", "TeacherConfig", "StudentConfig")


def get_app_data_dir(role: str) -> Path:
    """Return the configuration/log directory for the given app role ('teacher' or 'student')."""
    override = os.environ.get("CLASSROOM_DATA_DIR")
    if override:
        base = Path(override)
    else:
        local_app_data = os.environ.get("LOCALAPPDATA") or str(Path.home())
        base = Path(local_app_data) / "ClassroomManager"
    target = base / role
    target.mkdir(parents=True, exist_ok=True)
    return target


@dataclass
class TeacherConfig:
    initialized: bool = False
    password_hash: str = ""
    classroom_id: str = "Cab-101"
    class_secret: str = ""
    classrooms: list[dict[str, str]] = field(default_factory=list)
    bind_host: str = "0.0.0.0"
    tcp_port: int = 45455
    discovery_port: int = 45454
    discovery_enabled: bool = True
    mcp_enabled: bool = False
    mcp_port: int = 45460
    mcp_token: str = ""
    theme: str = "dark"
    grid_sort_mode: str = "natural_asc"
    grid_card_width: int = 326
    grid_custom_order: dict[str, list[str]] = field(default_factory=dict)
    known_students: dict[str, dict[str, str]] = field(default_factory=dict)
    thumb_fps: float = 1.0
    live_fps: float = 12.0
    thumb_width: int = 480
    live_width: int = 1920
    live_quality: int = 88
    demo_fps: float = 10.0
    demo_width: int = 1920
    demo_quality: int = 88
    saved_commands: list[dict[str, str]] = field(
        default_factory=lambda: [
            {
                "name": "Имя ПК, пользователь и IP",
                "script": "hostname; whoami; (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.IPAddress -notlike '127.*'}).IPAddress",
            },
            {
                "name": "Топ-10 процессов по памяти",
                "script": "Get-Process | Sort-Object WS -Descending | Select-Object -First 10 Name, Id, @{N='MB';E={[math]::Round($_.WS/1MB,1)}} | Format-Table -AutoSize",
            },
            {
                "name": "Закрыть браузеры (Chrome/Edge)",
                "script": "Stop-Process -Name chrome,msedge -Force -ErrorAction SilentlyContinue; 'Готово'",
            },
            {
                "name": "Открыть сайт в браузере",
                "script": "Start-Process 'https://docs.python.org/3/'",
            },
        ]
    )

    def ensure_classrooms(self) -> list[dict[str, str]]:
        """Ensure at least the active classroom exists in `self.classrooms` and return normalized list."""
        cleaned: list[dict[str, str]] = []
        seen: set[str] = set()
        for entry in self.classrooms:
            if not isinstance(entry, dict):
                continue
            rid = str(entry.get("id", "")).strip()
            sec = str(entry.get("secret", "")).strip()
            if rid and rid.lower() not in seen:
                cleaned.append({"id": rid, "secret": sec})
                seen.add(rid.lower())

        cur_id = (self.classroom_id or "Cab-101").strip()
        cur_sec = (self.class_secret or "").strip()
        if cur_id.lower() not in seen:
            cleaned.insert(0, {"id": cur_id, "secret": cur_sec})
        else:
            for item in cleaned:
                if item["id"].lower() == cur_id.lower():
                    if cur_sec and item["secret"] != cur_sec:
                        item["secret"] = cur_sec
                    elif not cur_sec and item["secret"]:
                        self.class_secret = item["secret"]
                    self.classroom_id = item["id"]
                    break
        self.classrooms = cleaned
        return self.classrooms

    def add_or_update_classroom(self, room_id: str, secret: str) -> None:
        rid = room_id.strip()
        sec = secret.strip()
        if not rid:
            return
        self.ensure_classrooms()
        for item in self.classrooms:
            if item["id"].lower() == rid.lower():
                item["id"] = rid
                item["secret"] = sec
                if self.classroom_id.strip().lower() == rid.lower():
                    self.classroom_id = rid
                    self.class_secret = sec
                return
        self.classrooms.append({"id": rid, "secret": sec})

    def set_active_classroom(self, room_id: str) -> bool:
        rid = room_id.strip().lower()
        self.ensure_classrooms()
        for item in self.classrooms:
            if item["id"].lower() == rid:
                self.classroom_id = item["id"]
                self.class_secret = item["secret"]
                return True
        return False

    def remove_classroom(self, room_id: str) -> bool:
        self.ensure_classrooms()
        if len(self.classrooms) <= 1:
            return False
        rid = room_id.strip().lower()
        remaining = [item for item in self.classrooms if item["id"].lower() != rid]
        if len(remaining) == len(self.classrooms):
            return False
        self.classrooms = remaining
        if self.classroom_id.strip().lower() == rid:
            self.classroom_id = self.classrooms[0]["id"]
            self.class_secret = self.classrooms[0]["secret"]
        return True


@dataclass
class StudentConfig:
    initialized: bool = False
    admin_password_hash: str = ""
    classroom_id: str = "Cab-101"
    class_secret: str = ""
    discovery_enabled: bool = True
    discovery_port: int = 45454
    manual_host: str = ""
    manual_port: int = 45455
    last_server_host: str = ""
    last_server_name: str = ""
    last_server_port: int = 45455
    pinned_fingerprint: str = ""
    hotkey: str = "Ctrl+Alt+Shift+M"
    display_name: str = ""


def load_config(path: Path, cls: type[T]) -> T:
    """Load JSON configuration from disk, filling defaults for missing fields."""
    if not path.exists():
        return cls()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return cls()
    if not isinstance(raw, dict):
        return cls()
    allowed = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
    return cls(**allowed)


def save_config(path: Path, cfg: TeacherConfig | StudentConfig) -> None:
    """Atomically save configuration JSON to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(
        json.dumps(asdict(cfg), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp_path.replace(path)
