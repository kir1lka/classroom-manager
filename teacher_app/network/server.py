"""Asyncio TLS server managing connected student agents."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import socket
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from shared.config import TeacherConfig
from shared.protocol import (
    PROTOCOL_VERSION,
    MessageType,
    ProtocolError,
    ScreenMode,
    decode_json,
    pack_file_chunk,
    read_frame,
    send_json,
    send_raw,
    unpack_screen_frame,
)
from shared.security import (
    create_server_ssl_context,
    ensure_tls_certificate,
    generate_nonce,
    verify_session_hmac,
)
from student_app.handlers.screen_capture import capture_screen_jpeg
from teacher_app.network.discovery import DiscoveryResponder

logger = logging.getLogger("classroom_manager.teacher.server")

AUTH_TIMEOUT_SEC = 10.0
HEARTBEAT_TIMEOUT_SEC = 28.0


@dataclass
class StudentSession:
    client_id: str
    hostname: str
    display_name: str
    username: str
    os_info: str
    ip: str
    screen_width: int
    screen_height: int
    writer: asyncio.StreamWriter
    classroom_id: str = ""
    monitors: list[dict[str, Any]] = field(default_factory=list)
    active_monitor: int = 1
    online: bool = True
    locked: bool = False
    active_window: str = ""
    connected_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.monotonic)
    last_ping_ms: float | None = None
    screen_mode: ScreenMode = ScreenMode.OFF
    write_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    pending_requests: dict[str, asyncio.Future[dict[str, Any]]] = field(default_factory=dict)
    pending_transfers: dict[str, asyncio.Future[dict[str, Any]]] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return self.display_name or self.hostname


class TeacherServer:
    """Central TLS server and student session registry for the Teacher desktop app."""

    def __init__(
        self,
        config: TeacherConfig,
        data_dir: Path,
        on_client_connected: Callable[[StudentSession], None] | None = None,
        on_client_disconnected: Callable[[str], None] | None = None,
        on_client_updated: Callable[[StudentSession], None] | None = None,
        on_screen_frame: Callable[[str, int, int, ScreenMode, bytes], None] | None = None,
    ) -> None:
        self.config = config
        self.data_dir = data_dir
        self.cert_path = data_dir / "certs" / "teacher_cert.pem"
        self.key_path = data_dir / "certs" / "teacher_key.pem"
        self.cert_fingerprint = ""

        self.clients: dict[str, StudentSession] = {}
        self._server: asyncio.AbstractServer | None = None
        self._discovery: DiscoveryResponder | None = None
        self._watchdog_task: asyncio.Task[None] | None = None
        self._demo_task: asyncio.Task[None] | None = None
        self._demo_active = False
        self._demo_fullscreen = True
        self._demo_title = "Демонстрация экрана учителя"
        self._client_tasks: set[asyncio.Task[None]] = set()
        self._running = False

        self.on_client_connected = on_client_connected
        self.on_client_disconnected = on_client_disconnected
        self.on_client_updated = on_client_updated
        self.on_screen_frame = on_screen_frame

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_demo_active(self) -> bool:
        return self._demo_active

    @property
    def bound_port(self) -> int:
        if self._server and self._server.sockets:
            return int(self._server.sockets[0].getsockname()[1])
        return self.config.tcp_port

    async def start(self) -> None:
        if self._running:
            return

        self.cert_fingerprint = ensure_tls_certificate(
            self.cert_path,
            self.key_path,
            common_name=socket.gethostname(),
        )
        ssl_ctx = create_server_ssl_context(self.cert_path, self.key_path)

        self._server = await asyncio.start_server(
            self._handle_connection,
            host=self.config.bind_host,
            port=self.config.tcp_port,
            ssl=ssl_ctx,
        )
        self._running = True
        logger.info(
            "Teacher TLS server started on %s:%d (room=%s, cert=%s...)",
            self.config.bind_host,
            self.bound_port,
            self.config.classroom_id,
            self.cert_fingerprint[:23],
        )

        if self.config.discovery_enabled:
            self._discovery = DiscoveryResponder(
                discovery_port=self.config.discovery_port,
                get_classroom_id=lambda: self.config.classroom_id,
                get_class_secret=lambda: self.config.class_secret,
                get_tcp_port=lambda: self.bound_port,
                get_cert_fingerprint=lambda: self.cert_fingerprint,
                get_classrooms=self.config.ensure_classrooms,
            )
            try:
                await self._discovery.start()
            except OSError as exc:
                logger.warning("Could not start UDP discovery on port %d: %s", self.config.discovery_port, exc)
                self._discovery = None

        self._watchdog_task = asyncio.create_task(self._heartbeat_watchdog())

    async def stop(self) -> None:
        await self.stop_demo_broadcast()
        self._running = False
        if self._watchdog_task:
            self._watchdog_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._watchdog_task
            self._watchdog_task = None

        if self._discovery:
            await self._discovery.stop()
            self._discovery = None

        for session in list(self.clients.values()):
            await self._close_session(session)

        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        for task in list(self._client_tasks):
            task.cancel()
        if self._client_tasks:
            await asyncio.gather(*self._client_tasks, return_exceptions=True)
        self._client_tasks.clear()
        logger.info("Teacher TLS server stopped")

    def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        task = asyncio.create_task(self._client_lifecycle(reader, writer))
        self._client_tasks.add(task)
        task.add_done_callback(self._client_tasks.discard)

    async def _client_lifecycle(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        raw_sock = writer.get_extra_info("socket")
        if raw_sock is not None:
            with contextlib.suppress(OSError):
                raw_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        peer = writer.get_extra_info("peername") or ("unknown", 0)
        peer_ip = str(peer[0])
        session: StudentSession | None = None

        try:
            # 1. Challenge-Response authentication over TLS
            nonce = generate_nonce()
            await send_json(
                writer,
                MessageType.AUTH_CHALLENGE,
                {
                    "nonce": nonce,
                    "classroom_id": self.config.classroom_id,
                    "server_name": socket.gethostname(),
                    "protocol_version": PROTOCOL_VERSION,
                },
            )

            msg_type, payload = await asyncio.wait_for(read_frame(reader), timeout=AUTH_TIMEOUT_SEC)
            if msg_type != MessageType.AUTH_RESPONSE:
                raise ProtocolError(f"Expected AUTH_RESPONSE, got {msg_type}")

            auth_data = decode_json(payload)
            req_room = str(auth_data.get("classroom_id", "")).strip()
            candidate_hmac = str(auth_data.get("hmac", ""))

            matched_room = ""
            for room in self.config.ensure_classrooms():
                rid = str(room.get("id", "")).strip()
                sec = str(room.get("secret", "")).strip()
                if not rid or not sec:
                    continue
                if req_room.lower() == rid.lower() and verify_session_hmac(sec, rid, nonce, candidate_hmac):
                    matched_room = rid
                    break

            if not matched_room:
                logger.warning("Rejected unauthenticated connection from %s (room=%s)", peer_ip, req_room)
                await send_json(
                    writer,
                    MessageType.AUTH_RESULT,
                    {"ok": False, "reason": "Неверный ключ класса или ID кабинета"},
                )
                return

            client_id = str(auth_data.get("client_id") or uuid.uuid4())
            session = StudentSession(
                client_id=client_id,
                hostname=str(auth_data.get("hostname") or peer_ip),
                display_name=str(auth_data.get("display_name") or ""),
                username=str(auth_data.get("username") or ""),
                os_info=str(auth_data.get("os_info") or "Windows"),
                ip=peer_ip,
                screen_width=int(auth_data.get("screen_width") or 1920),
                screen_height=int(auth_data.get("screen_height") or 1080),
                writer=writer,
                classroom_id=matched_room,
                monitors=list(auth_data.get("monitors") or []),
            )

            # Replace any stale connection with the same client_id
            old = self.clients.get(client_id)
            if old is not None:
                await self._close_session(old)

            self.clients[client_id] = session
            await send_json(
                writer,
                MessageType.AUTH_RESULT,
                {
                    "ok": True,
                    "server_name": socket.gethostname(),
                    "classroom_id": matched_room,
                },
            )
            logger.info(
                "Student connected: %s (%s) from %s [room=%s]",
                session.label,
                session.username,
                peer_ip,
                matched_room,
            )
            if self.on_client_connected:
                self.on_client_connected(session)

            # Start thumbnail preview stream automatically if configured
            if self.config.thumb_fps > 0:
                await self.set_screen_mode(
                    client_id,
                    ScreenMode.THUMB,
                    fps=self.config.thumb_fps,
                    width=self.config.thumb_width,
                    quality=72,
                    monitor=session.active_monitor,
                )

            # If Teacher screen demonstration is currently running, include latecomer automatically
            if self._demo_active:
                async with session.write_lock:
                    await send_json(
                        writer,
                        MessageType.DEMO_CONTROL,
                        {
                            "active": True,
                            "fullscreen": self._demo_fullscreen,
                            "title": self._demo_title,
                        },
                    )

            # 2. Main receive loop
            while self._running:
                msg_type, payload = await read_frame(reader)
                session.last_seen = time.monotonic()

                if msg_type == MessageType.HEARTBEAT:
                    hb = decode_json(payload)
                    session.locked = bool(hb.get("locked", False))
                    session.active_window = str(hb.get("active_window", ""))
                    async with session.write_lock:
                        await send_json(writer, MessageType.HEARTBEAT_ACK, {"ts": hb.get("ts", 0)})
                    if self.on_client_updated:
                        self.on_client_updated(session)

                elif msg_type == MessageType.CMD_RESPONSE:
                    resp = decode_json(payload)
                    req_id = str(resp.get("request_id", ""))
                    fut = session.pending_requests.pop(req_id, None)
                    if fut and not fut.done():
                        fut.set_result(resp)

                elif msg_type == MessageType.SCREEN_FRAME:
                    width, height, mode, jpeg_bytes = unpack_screen_frame(payload)
                    session.screen_width = width
                    session.screen_height = height
                    if self.on_screen_frame:
                        self.on_screen_frame(session.client_id, width, height, mode, jpeg_bytes)

                elif msg_type == MessageType.FILE_RESULT:
                    res = decode_json(payload)
                    tid = str(res.get("transfer_id", ""))
                    fut = session.pending_transfers.pop(tid, None)
                    if fut and not fut.done():
                        fut.set_result(res)

        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass
        except (asyncio.TimeoutError, ProtocolError) as exc:
            logger.warning("Protocol/timeout error for %s: %s", peer_ip, exc)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Unexpected error in student handler (%s): %s", peer_ip, exc)
        finally:
            if session is not None:
                await self._cleanup_session(session)
            else:
                writer.close()
                with contextlib.suppress(Exception):
                    await writer.wait_closed()

    async def _close_session(self, session: StudentSession) -> None:
        session.writer.close()
        with contextlib.suppress(Exception):
            await session.writer.wait_closed()

    async def _cleanup_session(self, session: StudentSession) -> None:
        if self.clients.get(session.client_id) is session:
            del self.clients[session.client_id]
            logger.info("Student disconnected: %s (%s)", session.label, session.ip)
            if self.on_client_disconnected:
                self.on_client_disconnected(session.client_id)

        for fut in session.pending_requests.values():
            if not fut.done():
                fut.set_result({"ok": False, "error": "Ученик отключился"})
        session.pending_requests.clear()

        for fut in session.pending_transfers.values():
            if not fut.done():
                fut.set_result({"ok": False, "error": "Ученик отключился во время передачи"})
        session.pending_transfers.clear()

        session.writer.close()
        with contextlib.suppress(Exception):
            await session.writer.wait_closed()

    async def _heartbeat_watchdog(self) -> None:
        while self._running:
            await asyncio.sleep(5.0)
            now = time.monotonic()
            for session in list(self.clients.values()):
                if now - session.last_seen > HEARTBEAT_TIMEOUT_SEC:
                    logger.warning("Heartbeat timeout for %s (%s), closing", session.label, session.ip)
                    await self._close_session(session)

    async def send_command(
        self,
        client_id: str,
        command: str,
        params: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Send an RPC command to a single student and await the response."""
        session = self.clients.get(client_id)
        if session is None:
            return {"ok": False, "error": "Ученик не в сети"}

        req_id = uuid.uuid4().hex
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        session.pending_requests[req_id] = fut

        try:
            async with session.write_lock:
                await send_json(
                    session.writer,
                    MessageType.CMD_REQUEST,
                    {
                        "request_id": req_id,
                        "command": command,
                        "params": params or {},
                    },
                )
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            session.pending_requests.pop(req_id, None)
            return {"ok": False, "error": f"Таймаут ожидания ответа ({timeout:.0f} с)"}
        except Exception as exc:
            session.pending_requests.pop(req_id, None)
            return {"ok": False, "error": str(exc)}

    async def broadcast_command(
        self,
        command: str,
        params: dict[str, Any] | None = None,
        timeout: float = 30.0,
        client_ids: list[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Send an RPC command to multiple (or all) connected students in parallel."""
        targets = client_ids if client_ids is not None else list(self.clients.keys())
        if not targets:
            return {}
        results = await asyncio.gather(
            *(self.send_command(cid, command, params, timeout=timeout) for cid in targets)
        )
        return dict(zip(targets, results))

    async def ping_client(self, client_id: str) -> dict[str, Any]:
        t0 = time.perf_counter()
        res = await self.send_command(client_id, "PING", timeout=5.0)
        if res.get("ok"):
            ms = round((time.perf_counter() - t0) * 1000.0, 1)
            res.setdefault("data", {})["rtt_ms"] = ms
            session = self.clients.get(client_id)
            if session:
                session.last_ping_ms = ms
                if self.on_client_updated:
                    self.on_client_updated(session)
        return res

    async def run_powershell(self, client_id: str, script: str, timeout: float = 30.0) -> dict[str, Any]:
        logger.info("Audit: sending PowerShell command to %s: %s", client_id, script[:120])
        return await self.send_command(
            client_id,
            "POWERSHELL",
            {"script": script, "timeout": timeout},
            timeout=timeout + 5.0,
        )

    async def lock_screen(self, client_id: str, message: str = "(срок бана: 1000 лет)") -> dict[str, Any]:
        res = await self.send_command(client_id, "LOCK_SCREEN", {"message": message}, timeout=10.0)
        if res.get("ok") and client_id in self.clients:
            self.clients[client_id].locked = True
            if self.on_client_updated:
                self.on_client_updated(self.clients[client_id])
        return res

    async def unlock_screen(self, client_id: str) -> dict[str, Any]:
        res = await self.send_command(client_id, "UNLOCK_SCREEN", timeout=10.0)
        if res.get("ok") and client_id in self.clients:
            self.clients[client_id].locked = False
            if self.on_client_updated:
                self.on_client_updated(self.clients[client_id])
        return res

    async def power_action(self, client_id: str, action: str) -> dict[str, Any]:
        logger.info("Audit: sending power action '%s' to %s", action, client_id)
        return await self.send_command(client_id, "POWER_ACTION", {"action": action}, timeout=10.0)

    async def show_message(self, client_id: str, title: str, text: str) -> dict[str, Any]:
        return await self.send_command(
            client_id,
            "SHOW_MESSAGE",
            {"title": title, "text": text},
            timeout=10.0,
        )

    async def set_screen_mode(
        self,
        client_id: str,
        mode: ScreenMode,
        fps: float,
        width: int,
        quality: int = 85,
        monitor: int | None = None,
        fast: bool | None = None,
    ) -> None:
        session = self.clients.get(client_id)
        if session is None:
            return
        session.screen_mode = mode
        if monitor is not None:
            session.active_monitor = int(monitor)
        use_fast = bool(fast) if fast is not None else (float(fps) >= 24.0)
        try:
            async with session.write_lock:
                await send_json(
                    session.writer,
                    MessageType.SCREEN_CONTROL,
                    {
                        "mode": int(mode),
                        "fps": float(fps),
                        "width": int(width),
                        "quality": int(quality),
                        "monitor": int(session.active_monitor),
                        "fast": use_fast,
                    },
                )
        except Exception as exc:
            logger.debug("Failed to send SCREEN_CONTROL to %s: %s", client_id, exc)

    async def cycle_student_monitor(self, client_id: str) -> int:
        """Switch a student's active monitor to the next display (1 -> 2 -> ... -> 1) and update stream."""
        session = self.clients.get(client_id)
        if session is None:
            return 1
        mon_indices = [int(m.get("index", i)) for i, m in enumerate(session.monitors, start=1)]
        if len(mon_indices) <= 1:
            return session.active_monitor

        if session.active_monitor in mon_indices:
            nxt = mon_indices[(mon_indices.index(session.active_monitor) + 1) % len(mon_indices)]
        else:
            nxt = mon_indices[0]

        session.active_monitor = nxt
        if self.on_client_updated:
            self.on_client_updated(session)

        if session.screen_mode == ScreenMode.LIVE:
            await self.set_screen_mode(
                client_id,
                ScreenMode.LIVE,
                fps=self.config.live_fps,
                width=self.config.live_width,
                quality=self.config.live_quality,
                monitor=nxt,
            )
        else:
            mode = ScreenMode.THUMB if self.config.thumb_fps > 0 else ScreenMode.OFF
            await self.set_screen_mode(
                client_id,
                mode,
                fps=max(0.5, self.config.thumb_fps),
                width=self.config.thumb_width,
                quality=72,
                monitor=nxt,
                fast=False,
            )
        return nxt

    async def send_remote_input(self, client_id: str, event_payload: dict[str, Any]) -> None:
        session = self.clients.get(client_id)
        if session is None:
            return
        try:
            async with session.write_lock:
                await send_json(session.writer, MessageType.REMOTE_INPUT, event_payload)
        except Exception as exc:
            logger.debug("Failed to send REMOTE_INPUT to %s: %s", client_id, exc)

    async def send_file(
        self,
        client_id: str,
        local_path: Path,
        dest_dir: str = "@desktop",
        overwrite: bool = True,
        open_after: bool = False,
        on_progress: Callable[[int, int], None] | None = None,
        timeout: float = 120.0,
    ) -> dict[str, Any]:
        """Stream a local file to a single student in 256 KiB chunks with SHA-256 verification."""
        session = self.clients.get(client_id)
        if session is None:
            return {"ok": False, "error": "Ученик не в сети"}
        if not local_path.is_file():
            return {"ok": False, "error": f"Файл не найден: {local_path}"}

        file_size = local_path.stat().st_size

        def _compute_sha256() -> str:
            h = hashlib.sha256()
            with local_path.open("rb") as f:
                while True:
                    block = f.read(1024 * 1024)
                    if not block:
                        break
                    h.update(block)
            return h.hexdigest()

        sha256_hex = await asyncio.to_thread(_compute_sha256)
        transfer_id = uuid.uuid4().hex
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        session.pending_transfers[transfer_id] = fut

        logger.info(
            "Audit: sending file '%s' (%d bytes) to %s -> %s",
            local_path.name,
            file_size,
            session.label,
            dest_dir,
        )

        chunk_size = 256 * 1024
        sent = 0
        try:
            async with session.write_lock:
                await send_json(
                    session.writer,
                    MessageType.FILE_START,
                    {
                        "transfer_id": transfer_id,
                        "filename": local_path.name,
                        "size": file_size,
                        "dest_dir": dest_dir,
                        "overwrite": overwrite,
                        "open_after": open_after,
                        "sha256": sha256_hex,
                    },
                )

            with local_path.open("rb") as f:
                while True:
                    if fut.done():
                        break
                    chunk = await asyncio.to_thread(f.read, chunk_size)
                    if not chunk:
                        break
                    packed = pack_file_chunk(transfer_id, chunk)
                    async with session.write_lock:
                        await send_raw(session.writer, MessageType.FILE_CHUNK, packed)
                    sent += len(chunk)
                    if on_progress:
                        on_progress(sent, file_size)

            if not fut.done():
                async with session.write_lock:
                    await send_json(session.writer, MessageType.FILE_END, {"transfer_id": transfer_id})

            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            session.pending_transfers.pop(transfer_id, None)
            return {"ok": False, "error": f"Таймаут передачи файла ({timeout:.0f} с)"}
        except Exception as exc:
            session.pending_transfers.pop(transfer_id, None)
            return {"ok": False, "error": str(exc)}

    async def broadcast_file(
        self,
        local_path: Path,
        dest_dir: str = "@desktop",
        overwrite: bool = True,
        open_after: bool = False,
        client_ids: list[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Send a file in parallel to multiple (or all) connected students."""
        targets = client_ids if client_ids is not None else list(self.clients.keys())
        if not targets:
            return {}
        results = await asyncio.gather(
            *(
                self.send_file(
                    cid,
                    local_path,
                    dest_dir=dest_dir,
                    overwrite=overwrite,
                    open_after=open_after,
                )
                for cid in targets
            )
        )
        return dict(zip(targets, results))

    async def _send_demo_control_all(self, active: bool) -> None:
        payload = {
            "active": active,
            "fullscreen": self._demo_fullscreen,
            "title": self._demo_title,
        }
        for session in list(self.clients.values()):
            try:
                async with session.write_lock:
                    await send_json(session.writer, MessageType.DEMO_CONTROL, payload)
            except Exception:
                pass

    async def start_demo_broadcast(
        self,
        fps: float | None = None,
        width: int | None = None,
        quality: int | None = None,
        fullscreen: bool = True,
        title: str | None = None,
        monitor: int = 1,
    ) -> None:
        """Broadcast the Teacher's own screen live in crisp HD to all connected students."""
        if self._demo_active:
            return
        self._demo_active = True
        self._demo_fullscreen = fullscreen
        self._demo_title = title or f"Демонстрация экрана учителя ({self.config.classroom_id})"
        rate = max(1.0, min(60.0, float(fps if fps is not None else self.config.demo_fps)))
        target_w = int(width if width is not None else self.config.demo_width)
        target_q = int(quality if quality is not None else self.config.demo_quality)

        logger.info(
            "Audit: started Teacher screen demo broadcast (%.1f FPS, %dpx, q=%d, mon=%d)",
            rate,
            target_w,
            target_q,
            monitor,
        )
        await self._send_demo_control_all(True)
        self._demo_task = asyncio.create_task(self._demo_broadcast_loop(rate, target_w, target_q, monitor))

    async def stop_demo_broadcast(self) -> None:
        """Stop Teacher screen demonstration on all connected students."""
        if not self._demo_active and self._demo_task is None:
            return
        self._demo_active = False
        if self._demo_task is not None:
            self._demo_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._demo_task
            self._demo_task = None
        await self._send_demo_control_all(False)
        logger.info("Audit: stopped Teacher screen demo broadcast")

    async def _demo_broadcast_loop(self, fps: float, width: int, quality: int, monitor: int = 1) -> None:
        interval = 1.0 / fps
        use_fast = fps >= 24.0
        while self._running and self._demo_active:
            t0 = time.perf_counter()
            sessions = list(self.clients.values())
            if sessions:
                try:
                    _w, _h, jpeg_bytes = await asyncio.to_thread(
                        capture_screen_jpeg, width, quality, monitor, use_fast
                    )

                    async def _push(sess: StudentSession) -> None:
                        try:
                            async with sess.write_lock:
                                await send_raw(sess.writer, MessageType.DEMO_FRAME, jpeg_bytes)
                        except Exception:
                            pass

                    await asyncio.gather(*(_push(s) for s in sessions))
                except Exception as exc:
                    logger.debug("Demo screen capture error: %s", exc)

            elapsed = time.perf_counter() - t0
            sleep_for = interval - elapsed
            await asyncio.sleep(sleep_for if sleep_for > 0.001 else 0)
