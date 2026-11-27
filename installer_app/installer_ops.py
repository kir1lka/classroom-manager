"""Windows installation operations: payload extraction, firewall script, autostart, shortcuts, and pre-config."""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from shared.config import StudentConfig, get_app_data_dir, save_config
from shared.security import hash_password


def is_admin() -> bool:
    """Return True if the current process is running with Windows Administrator privileges."""
    if sys.platform != "win32":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def get_payload_dir() -> Path:
    """Locate bundled EXE payload (inside PyInstaller _MEIPASS or local dist/)."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bundled = Path(meipass) / "payload"
        if bundled.exists():
            return bundled
    # Fallback for running installer from source
    repo_root = Path(__file__).resolve().parent.parent
    dist_dir = repo_root / "dist"
    if dist_dir.exists():
        return dist_dir
    return Path.cwd()


def get_firewall_script_path() -> Path | None:
    """Locate setup_firewall.ps1 inside payload or scripts/."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate = Path(meipass) / "payload" / "setup_firewall.ps1"
        if candidate.is_file():
            return candidate
    repo_root = Path(__file__).resolve().parent.parent
    for cand in (repo_root / "scripts" / "setup_firewall.ps1", get_payload_dir() / "setup_firewall.ps1"):
        if cand.is_file():
            return cand
    return None


def default_install_dir() -> Path:
    if is_admin():
        return Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "ClassroomManager"
    local_app = Path(os.environ.get("LOCALAPPDATA") or str(Path.home()))
    return local_app / "Programs" / "ClassroomManager"


@dataclass
class InstallOptions:
    install_teacher: bool = True
    install_student: bool = False
    install_dir: Path = default_install_dir()
    configure_firewall: bool = True
    add_autostart: bool = True
    create_shortcuts: bool = True
    launch_after: bool = True
    # Optional Student pre-configuration
    student_room_id: str = ""
    student_class_secret: str = ""
    student_admin_password: str = ""
    student_display_name: str = ""


def _create_windows_shortcut(shortcut_path: Path, target_exe: Path, description: str) -> None:
    """Create a .lnk shortcut via PowerShell WScript.Shell (zero extra dependencies)."""
    shortcut_path.parent.mkdir(parents=True, exist_ok=True)
    ps = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut('{str(shortcut_path).replace(chr(39), chr(39)*2)}'); "
        f"$s.TargetPath = '{str(target_exe).replace(chr(39), chr(39)*2)}'; "
        f"$s.WorkingDirectory = '{str(target_exe.parent).replace(chr(39), chr(39)*2)}'; "
        f"$s.Description = '{description.replace(chr(39), chr(39)*2)}'; "
        "$s.Save()"
    )
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
        check=False,
        capture_output=True,
        creationflags=creation_flags,
    )


def _register_autostart(name: str, exe_path: Path, log: Callable[[str], None]) -> None:
    """Register autostart: Scheduled Task with highest privileges if admin, else HKCU Run key."""
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if is_admin():
        cmd = [
            "schtasks",
            "/Create",
            "/TN",
            f"ClassroomManager_{name}",
            "/TR",
            f'"{exe_path}"',
            "/SC",
            "ONLOGON",
            "/RL",
            "HIGHEST",
            "/F",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, creationflags=creation_flags)
        if res.returncode == 0:
            log(f"  [OK] Автозагрузка (Планировщик с правами администратора): {name}")
            return

    # Fallback: per-user HKCU Run registry key (works without admin rights)
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(key, f"ClassroomManager_{name}", 0, winreg.REG_SZ, f'"{exe_path}"')
        log(f"  [OK] Автозагрузка (HKCU Run): {name}")
    except Exception as exc:
        log(f"  [!] Не удалось добавить в автозагрузку ({name}): {exc}")


def _run_firewall_setup(script_path: Path, log: Callable[[str], None]) -> None:
    """Run setup_firewall.ps1 directly if elevated, or trigger clean UAC elevation."""
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if is_admin():
        res = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_path),
            ],
            capture_output=True,
            text=True,
            creationflags=creation_flags,
        )
        if res.returncode == 0:
            log("  [OK] Порты Брандмауэра Windows открыты (TCP 45455 / UDP 45454)")
        else:
            log(f"  [!] Брандмауэр: {(res.stderr or res.stdout).strip()[:160]}")
    else:
        # Request elevation via ShellExecuteW 'runas' so Windows shows standard UAC dialog
        try:
            params = f'-NoProfile -ExecutionPolicy Bypass -File "{script_path}"'
            rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", "powershell.exe", params, None, 0)
            if rc > 32:
                log("  [OK] Запущена настройка Брандмауэра Windows (подтвердите запрос UAC)")
            else:
                log("  [!] Запрос UAC отклонён — порты можно открыть позже через setup_firewall.ps1")
        except Exception as exc:
            log(f"  [!] Не удалось запустить настройку Брандмауэра: {exc}")


def run_installation(
    opts: InstallOptions,
    log: Callable[[str], None],
    on_progress: Callable[[int], None],
) -> tuple[bool, list[Path]]:
    """Perform full installation synchronously (call in a background thread)."""
    launched_exes: list[Path] = []
    payload = get_payload_dir()
    dest = opts.install_dir

    try:
        on_progress(5)
        log(f"Папка установки: {dest}")
        dest.mkdir(parents=True, exist_ok=True)

        # Copy firewall helper script into install folder
        fw_src = get_firewall_script_path()
        fw_dest = dest / "setup_firewall.ps1"
        if fw_src is not None and fw_src.is_file():
            shutil.copy2(fw_src, fw_dest)
            log("  [OK] Скопирован скрипт setup_firewall.ps1")
        on_progress(15)

        # Stop running instances cleanly before copying
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if opts.install_teacher:
            subprocess.run(
                ["taskkill", "/F", "/IM", "ClassroomTeacher.exe"],
                capture_output=True,
                creationflags=creation_flags,
            )
        if opts.install_student:
            subprocess.run(
                ["taskkill", "/F", "/IM", "ClassroomStudent.exe"],
                capture_output=True,
                creationflags=creation_flags,
            )

        desktop_dir = Path.home() / "Desktop"
        start_menu_dir = (
            Path(os.environ.get("APPDATA", str(Path.home())))
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
            / "Classroom Manager"
        )

        # 1. Install Teacher App
        if opts.install_teacher:
            src_teacher = payload / "ClassroomTeacher.exe"
            if not src_teacher.is_file():
                log(f"  [ОШИБКА] Не найден файл {src_teacher}")
                return False, []
            dst_teacher = dest / "ClassroomTeacher.exe"
            log("Копирование ClassroomTeacher.exe...")
            shutil.copy2(src_teacher, dst_teacher)
            log(f"  [OK] Установлен: {dst_teacher}")
            launched_exes.append(dst_teacher)
            on_progress(40)

            if opts.create_shortcuts:
                _create_windows_shortcut(
                    desktop_dir / "Classroom Manager (Учитель).lnk",
                    dst_teacher,
                    "Classroom Manager — Панель учителя",
                )
                _create_windows_shortcut(
                    start_menu_dir / "Classroom Manager (Учитель).lnk",
                    dst_teacher,
                    "Classroom Manager — Панель учителя",
                )
                log("  [OK] Созданы ярлыки на Рабочем столе и в меню «Пуск»")

            if opts.add_autostart:
                _register_autostart("Teacher", dst_teacher, log)

        on_progress(55)

        # 2. Install Student App
        if opts.install_student:
            src_student = payload / "ClassroomStudent.exe"
            if not src_student.is_file():
                log(f"  [ОШИБКА] Не найден файл {src_student}")
                return False, []
            dst_student = dest / "ClassroomStudent.exe"
            log("Копирование ClassroomStudent.exe...")
            shutil.copy2(src_student, dst_student)
            log(f"  [OK] Установлен: {dst_student}")
            launched_exes.append(dst_student)
            on_progress(72)

            # Optional quick pre-configuration for Student
            if (
                opts.student_room_id.strip()
                and len(opts.student_class_secret.strip()) >= 6
                and len(opts.student_admin_password) >= 4
            ):
                s_dir = get_app_data_dir("student")
                s_cfg_path = s_dir / "config.json"
                s_cfg = StudentConfig(
                    initialized=True,
                    admin_password_hash=hash_password(opts.student_admin_password),
                    classroom_id=opts.student_room_id.strip(),
                    class_secret=opts.student_class_secret.strip(),
                    discovery_enabled=True,
                    display_name=opts.student_display_name.strip(),
                )
                save_config(s_cfg_path, s_cfg)
                log(f"  [OK] Агент ученика преднастроен для кабинета «{s_cfg.classroom_id}»")

            if opts.create_shortcuts:
                _create_windows_shortcut(
                    start_menu_dir / "Classroom Manager (Ученик).lnk",
                    dst_student,
                    "Classroom Manager — Фоновый агент ученика",
                )
                log("  [OK] Создан ярлык агента ученика в меню «Пуск»")

            if opts.add_autostart:
                _register_autostart("Student", dst_student, log)

        on_progress(85)

        # 3. Configure Windows Firewall
        if opts.configure_firewall and fw_dest.is_file():
            log("Настройка правил Брандмауэра Windows (TCP 45455 / UDP 45454)...")
            _run_firewall_setup(fw_dest, log)

        on_progress(95)

        # 4. Launch installed applications if requested
        if opts.launch_after:
            for exe in launched_exes:
                try:
                    subprocess.Popen([str(exe)], cwd=str(exe.parent))
                    log(f"  [OK] Запущено: {exe.name}")
                except OSError as exc:
                    log(f"  [!] Не удалось запустить {exe.name}: {exc}")

        on_progress(100)
        log("Установка успешно завершена!")
        return True, launched_exes
    except Exception as exc:
        log(f"[ОШИБКА] {exc}")
        return False, []
