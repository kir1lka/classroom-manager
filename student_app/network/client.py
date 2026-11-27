"""Asyncio TLS client for the Student agent with multi-teacher support and 60 FPS streaming."""

from __future__ import annotations

import asyncio
import contextlib
import getpass
import logging
import platform
import socket
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from shared.config import StudentConfig, save_config
from shared.protocol import (
    MessageType,
    ProtocolError,
    ScreenMode,
    decode_json,
    pack_screen_frame,
    read_frame,
    send_json,
    send_raw,
    unpack_file_chunk,
)
from shared.security import (
    compute_session_hmac,
    create_client_ssl_context,
    get_peer_cert_fingerprint,
)
from student_app.handlers.file_transfer import FileTransferReceiver
from student_app.handlers.remote_input import handle_remote_input
from student_app.handlers.router import CommandRouter
from student_app.handlers.screen_capture import capture_screen_jpeg, list_monitors
from student_app.handlers.system_ops import get_active_window_title, get_screen_resolution
from student_app.network.discovery import DiscoveredEndpoint, resolve_teacher_candidates

logger = logging.getLogger("classroom_manager.student.client")


@dataclass
class _StreamState:
    mode: ScreenMode = ScreenMode.OFF
    fps: float = 1.0
    width: int = 480
    quality: int = 72
    monitor: int = 1
    fast: bool = False
    event: asyncio.Event = field(default_factory=asyncio.Event)


class StudentClient:
    """Maintains encrypted, auto-reconnecting links to one or multiple Teacher servers simultaneously."""

    def __init__(
        self,
        config: StudentConfig,
        config_path: Path,
        router: CommandRouter,
        on_state_changed: Callable[[str, str], None] | None = None,
        on_demo_control: Callable[[bool, str, bool], None] | None = None,
        on_demo_frame: Callable[[bytes], None] | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self.config = config
        self.config_path = config_path
        self.router = router
        self.on_state_changed = on_state_changed
        self.on_demo_control = on_demo_control
        self.on_demo_frame = on_demo_frame
        self._loop = loop

        self.client_id = self._load_or_create_client_id(config_path.parent / "client_id.txt")
        self._running = False
        self._main_task: asyncio.Task[None] | None = None
        self._wakeup_event = asyncio.Event()

        # Active per-teacher connection tasks: (host, port) -> Task
        self._teacher_tasks: dict[tuple[str, int], asyncio.Task[None]] = {}
        # Connected teacher labels: (host, port) -> "HOSTNAME (ip:port)"
        self._connected_teachers: dict[tuple[str, int], str] = {}
        # Dedup by TLS certificate fingerprint so one multi-NIC teacher is not connected twice
        self._connected_fingerprints: dict[str, tuple[str, int]] = {}

        self.state = "STOPPED"
        self.state_detail = ""
        self.connected_server = ""

    @staticmethod
    def _load_or_create_client_id(path: Path) -> str:
        if path.exists():
            val = path.read_text(encoding="utf-8").strip()
            if val:
                return val
        val = f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(val, encoding="utf-8")
        return val

    def _set_state(self, state: str, detail: str = "") -> None:
        self.state = state
        self.state_detail = detail
        if self.on_state_changed:
            self.on_state_changed(state, detail)

    def _refresh_connected_state(self) -> None:
        if self._connected_teachers:
            labels = list(self._connected_teachers.values())
            if len(labels) == 1:
                self.connected_server = labels[0]
                self._set_state("CONNECTED", f"Подключён к {labels[0]}")
            else:
                self.connected_server = f"{len(labels)} учителей"
                self._set_state("CONNECTED", f"Подключён к {len(labels)} учителям")
        elif self._running:
            self.connected_server = ""

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is not None:
            return self._loop
        try:
            return asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.get_event_loop()

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._wakeup_event.clear()
        self._main_task = self._get_loop().create_task(self._run_loop())

    async def stop(self) -> None:
        self._running = False
        self._wakeup_event.set()
        for task in list(self._teacher_tasks.values()):
            task.cancel()
        if self._teacher_tasks:
            await asyncio.gather(*self._teacher_tasks.values(), return_exceptions=True)
        self._teacher_tasks.clear()
        self._connected_teachers.clear()
        self._connected_fingerprints.clear()

        if self._main_task:
            self._main_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._main_task
            self._main_task = None
        self._set_state("STOPPED", "Агент остановлен")

    def trigger_reconnect(self) -> None:
        """Force immediate reconnection to all teachers after settings change."""
        for task in list(self._teacher_tasks.values()):
            task.cancel()
        self._teacher_tasks.clear()
        self._connected_teachers.clear()
        self._connected_fingerprints.clear()
        if self._main_task and not self._main_task.done():
            self._main_task.cancel()
            self._main_task = self._get_loop().create_task(self._run_loop())

    async def _run_loop(self) -> None:
        backoff = 1.0
        while self._running:
            if not self.config.initialized or not self.config.class_secret:
                self._set_state("UNCONFIGURED", "Требуется первичная настройка")
                await asyncio.sleep(2.0)
                continue

            # Prune finished connection tasks
            for key, task in list(self._teacher_tasks.items()):
                if task.done():
                    self._teacher_tasks.pop(key, None)

            if not self._connected_teachers:
                self._set_state("DISCOVERING", f"Поиск учителя ({self.config.classroom_id})...")

            candidates = await resolve_teacher_candidates(self.config, udp_timeout=1.2)
            for ep in candidates:
                if not self._running:
                    return
                key = (ep.host, ep.port)
                if key in self._teacher_tasks and not self._teacher_tasks[key].done():
                    continue
                if ep.cert_fingerprint and ep.cert_fingerprint in self._connected_fingerprints:
                    continue
                task = asyncio.create_task(self._teacher_session_wrapper(ep))
                self._teacher_tasks[key] = task

            if self._connected_teachers or self._teacher_tasks:
                backoff = 1.0
                # Periodically scan for additional teachers joining the same classroom
                wait_sec = 6.0 if self._connected_teachers else 1.5
            else:
                self._set_state("RECONNECTING", f"Учитель не найден, повтор через {backoff:.0f} с...")
                wait_sec = backoff
                backoff = min(8.0, backoff * 1.6)

            try:
                await asyncio.wait_for(self._wakeup_event.wait(), timeout=wait_sec)
                self._wakeup_event.clear()
            except asyncio.TimeoutError:
                pass

    async def _teacher_session_wrapper(self, ep: DiscoveredEndpoint) -> None:
        key = (ep.host, ep.port)
        try:
            await self._connect_and_serve(ep)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug("Teacher %s:%d (%s) session ended: %s", ep.host, ep.port, ep.source, exc)
        finally:
            self._connected_teachers.pop(key, None)
            for fp, mapped_key in list(self._connected_fingerprints.items()):
                if mapped_key == key:
                    self._connected_fingerprints.pop(fp, None)
            self._refresh_connected_state()
            if not self._connected_teachers and self._running:
                self._wakeup_event.set()

    async def _connect_and_serve(self, ep: DiscoveredEndpoint) -> bool:
        key = (ep.host, ep.port)
        if not self._connected_teachers:
            self._set_state("CONNECTING", f"Подключение к {ep.host}:{ep.port}...")

        ssl_ctx = create_client_ssl_context()
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ep.host, ep.port, ssl=ssl_ctx),
            timeout=5.0,
        )
        # Enable TCP_NODELAY for low-latency 60 FPS frames and instant mouse/keyboard response
        raw_sock = writer.get_extra_info("socket")
        if raw_sock is not None:
            with contextlib.suppress(OSError):
                raw_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        write_lock = asyncio.Lock()

        try:
            ssl_obj = writer.get_extra_info("ssl_object")
            peer_fp = get_peer_cert_fingerprint(ssl_obj)
            if self.config.pinned_fingerprint and peer_fp:
                if peer_fp.upper() != self.config.pinned_fingerprint.strip().upper():
                    logger.error("TLS fingerprint mismatch! Expected %s, got %s", self.config.pinned_fingerprint, peer_fp)
                    if not self._connected_teachers:
                        self._set_state("AUTH_ERROR", "Ошибка проверки TLS-сертификата")
                    return False

            # Avoid duplicate session to the exact same teacher server via two different NIC IPs
            if peer_fp and peer_fp in self._connected_fingerprints:
                return False

            if not self._connected_teachers:
                self._set_state("AUTHENTICATING", f"Авторизация на {ep.host}...")

            msg_type, payload = await asyncio.wait_for(read_frame(reader), timeout=8.0)
            if msg_type != MessageType.AUTH_CHALLENGE:
                raise ProtocolError(f"Expected AUTH_CHALLENGE, got {msg_type}")

            challenge = decode_json(payload)
            nonce = str(challenge.get("nonce", ""))
            server_name = str(challenge.get("server_name", ep.server_name))

            screen_w, screen_h = get_screen_resolution()
            response_hmac = compute_session_hmac(
                self.config.class_secret,
                self.config.classroom_id,
                nonce,
            )
            await send_json(
                writer,
                MessageType.AUTH_RESPONSE,
                {
                    "hmac": response_hmac,
                    "classroom_id": self.config.classroom_id,
                    "client_id": self.client_id,
                    "hostname": socket.gethostname(),
                    "display_name": self.config.display_name,
                    "username": getpass.getuser(),
                    "os_info": f"{platform.system()} {platform.release()}",
                    "screen_width": screen_w,
                    "screen_height": screen_h,
                    "monitors": list_monitors(),
                },
            )

            res_type, res_payload = await asyncio.wait_for(read_frame(reader), timeout=8.0)
            if res_type != MessageType.AUTH_RESULT:
                raise ProtocolError(f"Expected AUTH_RESULT, got {res_type}")

            auth_res = decode_json(res_payload)
            if not auth_res.get("ok"):
                reason = str(auth_res.get("reason", "Доступ запрещён"))
                logger.warning("Teacher rejected authentication: %s", reason)
                if not self._connected_teachers:
                    self._set_state("AUTH_ERROR", reason)
                await asyncio.sleep(3.0)
                return False

            # Save successful server info for Tier 3 fallback
            changed = False
            if self.config.last_server_host != ep.host:
                self.config.last_server_host = ep.host
                changed = True
            if server_name and self.config.last_server_name != server_name:
                self.config.last_server_name = server_name
                changed = True
            if self.config.last_server_port != ep.port:
                self.config.last_server_port = ep.port
                changed = True
            if changed:
                save_config(self.config_path, self.config)

            label = f"{server_name or ep.host} ({ep.host}:{ep.port})"
            self._connected_teachers[key] = label
            if peer_fp:
                self._connected_fingerprints[peer_fp] = key
            self._refresh_connected_state()
            logger.info("Connected to Teacher server %s via %s", label, ep.source)

            stream_state = _StreamState()
            hb_task = asyncio.create_task(self._heartbeat_loop(writer, write_lock))
            stream_task = asyncio.create_task(self._screen_stream_loop(writer, write_lock, stream_state))
            file_receiver = FileTransferReceiver()
            demo_from_this_teacher = False

            try:
                while self._running:
                    mtype, data = await read_frame(reader)
                    if mtype == MessageType.HEARTBEAT_ACK:
                        continue
                    elif mtype == MessageType.CMD_REQUEST:
                        req = decode_json(data)
                        asyncio.create_task(self._handle_cmd_request(writer, write_lock, req))
                    elif mtype == MessageType.SCREEN_CONTROL:
                        ctrl = decode_json(data)
                        stream_state.mode = ScreenMode(int(ctrl.get("mode", 0)))
                        stream_state.fps = max(0.2, min(60.0, float(ctrl.get("fps", 1.0))))
                        stream_state.width = int(ctrl.get("width", 480))
                        stream_state.quality = int(ctrl.get("quality", 72))
                        stream_state.monitor = int(ctrl.get("monitor", 1))
                        stream_state.fast = bool(ctrl.get("fast", stream_state.fps >= 24.0))
                        stream_state.event.set()
                    elif mtype == MessageType.REMOTE_INPUT:
                        inp = decode_json(data)
                        await asyncio.to_thread(handle_remote_input, inp)
                    elif mtype == MessageType.FILE_START:
                        meta = decode_json(data)
                        err = await asyncio.to_thread(file_receiver.start_transfer, meta)
                        if err is not None:
                            async with write_lock:
                                await send_json(writer, MessageType.FILE_RESULT, err)
                    elif mtype == MessageType.FILE_CHUNK:
                        tid, chunk = unpack_file_chunk(data)
                        await asyncio.to_thread(file_receiver.write_chunk, tid, chunk)
                    elif mtype == MessageType.FILE_END:
                        end_meta = decode_json(data)
                        tid = str(end_meta.get("transfer_id", ""))
                        res = await asyncio.to_thread(file_receiver.finish_transfer, tid)
                        async with write_lock:
                            await send_json(writer, MessageType.FILE_RESULT, res)
                    elif mtype == MessageType.DEMO_CONTROL:
                        ctrl = decode_json(data)
                        active = bool(ctrl.get("active", False))
                        title = str(ctrl.get("title") or "Демонстрация экрана учителя")
                        fullscreen = bool(ctrl.get("fullscreen", True))
                        demo_from_this_teacher = active
                        if self.on_demo_control:
                            self.on_demo_control(active, title, fullscreen)
                    elif mtype == MessageType.DEMO_FRAME:
                        if self.on_demo_frame:
                            self.on_demo_frame(data)
            finally:
                if demo_from_this_teacher and self.on_demo_control:
                    self.on_demo_control(False, "", True)
                file_receiver.cleanup_all()
                hb_task.cancel()
                stream_task.cancel()
                await asyncio.gather(hb_task, stream_task, return_exceptions=True)

            return True
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    async def _handle_cmd_request(
        self,
        writer: asyncio.StreamWriter,
        write_lock: asyncio.Lock,
        req: dict,
    ) -> None:
        req_id = str(req.get("request_id", ""))
        command = str(req.get("command", ""))
        params = req.get("params") if isinstance(req.get("params"), dict) else {}
        result = await self.router.dispatch(command, params)
        response = {
            "request_id": req_id,
            "ok": bool(result.get("ok", False)),
            "data": result.get("data", {}),
            "error": str(result.get("error", "")),
        }
        try:
            async with write_lock:
                await send_json(writer, MessageType.CMD_RESPONSE, response)
        except Exception:
            pass

    async def _heartbeat_loop(
        self,
        writer: asyncio.StreamWriter,
        write_lock: asyncio.Lock,
    ) -> None:
        while self._running:
            await asyncio.sleep(8.0)
            active_win = await asyncio.to_thread(get_active_window_title)
            async with write_lock:
                await send_json(
                    writer,
                    MessageType.HEARTBEAT,
                    {
                        "ts": time.time(),
                        "locked": self.router.screen_locked,
                        "active_window": active_win,
                    },
                )

    async def _screen_stream_loop(
        self,
        writer: asyncio.StreamWriter,
        write_lock: asyncio.Lock,
        stream_state: _StreamState,
    ) -> None:
        while self._running:
            if stream_state.mode == ScreenMode.OFF:
                stream_state.event.clear()
                await stream_state.event.wait()
                continue

            t0 = time.perf_counter()
            mode = stream_state.mode
            target_w = stream_state.width
            quality = stream_state.quality
            mon_idx = stream_state.monitor
            fast = stream_state.fast
            try:
                orig_w, orig_h, jpeg_bytes = await asyncio.to_thread(
                    capture_screen_jpeg,
                    target_w,
                    quality,
                    mon_idx,
                    fast,
                )
                packed = pack_screen_frame(orig_w, orig_h, mode, jpeg_bytes)
                async with write_lock:
                    await send_raw(writer, MessageType.SCREEN_FRAME, packed)
            except Exception as exc:
                logger.debug("Screen capture failed: %s", exc)
                await asyncio.sleep(0.5)
                continue

            interval = 1.0 / max(0.2, stream_state.fps)
            elapsed = time.perf_counter() - t0
            sleep_for = interval - elapsed
            if sleep_for > 0.001:
                stream_state.event.clear()
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(stream_state.event.wait(), timeout=sleep_for)
            else:
                await asyncio.sleep(0)
