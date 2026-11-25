"""Unit and end-to-end tests for protocol, TLS security, UDP discovery, PowerShell, and streaming."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from shared.config import StudentConfig, TeacherConfig, load_config, save_config
from shared.protocol import (
    MessageType,
    ProtocolError,
    ScreenMode,
    decode_discovery_packet,
    decode_json,
    encode_discovery_packet,
    pack_screen_frame,
    read_frame,
    send_json,
    unpack_screen_frame,
)
from shared.security import (
    compute_discovery_tag,
    compute_session_hmac,
    ensure_tls_certificate,
    generate_class_secret,
    hash_password,
    verify_password,
    verify_session_hmac,
)
from student_app.handlers.router import CommandRouter
from student_app.handlers.screen_capture import capture_screen_jpeg, list_monitors
from student_app.network.client import StudentClient
from student_app.network.discovery import discover_teacher_udp
from student_app.ui.hotkey import parse_hotkey_string
from teacher_app.network.mcp_server import ClassroomMCPServer, build_mcp_client_config
from teacher_app.network.server import TeacherServer
from teacher_app.ui.theme import get_stylesheet


def test_password_hashing_and_verification() -> None:
    hashed = hash_password("TeacherPass!2026")
    assert hashed.startswith("scrypt$")
    assert verify_password("TeacherPass!2026", hashed) is True
    assert verify_password("WrongPass", hashed) is False
    assert verify_password("", hashed) is False


def test_hmac_and_discovery_tag() -> None:
    secret = generate_class_secret()
    mac = compute_session_hmac(secret, "Cab-204", "nonce123")
    assert verify_session_hmac(secret, "cab-204", "nonce123", mac) is True
    assert verify_session_hmac(secret, "cab-204", "other_nonce", mac) is False
    assert verify_session_hmac("wrong-secret", "cab-204", "nonce123", mac) is False

    tag1 = compute_discovery_tag("Cab-204", secret)
    tag2 = compute_discovery_tag("cab-204", secret)
    assert tag1 == tag2
    assert secret not in tag1


def test_protocol_helpers_and_hotkey_parser() -> None:
    packed = pack_screen_frame(1920, 1080, ScreenMode.LIVE, b"\xff\xd8JPEGDATA\xff\xd9")
    w, h, mode, jpg = unpack_screen_frame(packed)
    assert (w, h, mode) == (1920, 1080, ScreenMode.LIVE)
    assert jpg == b"\xff\xd8JPEGDATA\xff\xd9"

    raw = encode_discovery_packet({"type": "DISCOVER", "classroom_id": "Cab-101"})
    decoded = decode_discovery_packet(raw)
    assert decoded == {"type": "DISCOVER", "classroom_id": "Cab-101"}
    assert decode_discovery_packet(b"GARBAGE") is None

    parsed = parse_hotkey_string("Ctrl+Alt+Shift+M")
    assert parsed is not None
    assert parsed[1] == ord("M")
    assert parse_hotkey_string("Ctrl+F12") is not None
    assert parse_hotkey_string("InvalidKeyName") is None


def test_config_roundtrip(tmp_path: Path) -> None:
    t_path = tmp_path / "teacher.json"
    t_cfg = TeacherConfig(
        initialized=True,
        classroom_id="Lab-3",
        class_secret="AAAA-BBBB-CCCC",
        tcp_port=50123,
        theme="light",
    )
    t_cfg.saved_commands.append({"name": "Тест", "script": "Get-Date"})
    save_config(t_path, t_cfg)
    loaded = load_config(t_path, TeacherConfig)
    assert loaded.initialized is True
    assert loaded.classroom_id == "Lab-3"
    assert loaded.tcp_port == 50123
    assert loaded.theme == "light"
    assert any(c["name"] == "Тест" for c in loaded.saved_commands)


def test_multi_classroom_config_management() -> None:
    cfg = TeacherConfig(classroom_id="Cab-101", class_secret="KEY1-AAAA-1111")
    rooms = cfg.ensure_classrooms()
    assert len(rooms) == 1
    assert rooms[0]["id"] == "Cab-101"

    cfg.add_or_update_classroom("Cab-204", "KEY2-BBBB-2222")
    assert len(cfg.classrooms) == 2
    assert cfg.set_active_classroom("Cab-204") is True
    assert cfg.classroom_id == "Cab-204"
    assert cfg.class_secret == "KEY2-BBBB-2222"

    assert cfg.remove_classroom("Cab-204") is True
    assert len(cfg.classrooms) == 1
    assert cfg.classroom_id == "Cab-101"
    # Cannot remove the last remaining classroom
    assert cfg.remove_classroom("Cab-101") is False


@pytest.mark.asyncio
async def test_mcp_server_http_jsonrpc(tmp_path: Path) -> None:
    import json
    import urllib.error
    import urllib.request

    cfg = TeacherConfig(
        initialized=True,
        classroom_id="Cab-101",
        class_secret="MCP-TEST-KEY1",
        classrooms=[
            {"id": "Cab-101", "secret": "MCP-TEST-KEY1"},
            {"id": "Cab-204", "secret": "MCP-TEST-KEY2"},
        ],
        tcp_port=0,
        discovery_enabled=False,
    )
    server = TeacherServer(config=cfg, data_dir=tmp_path / "teacher")
    mcp = ClassroomMCPServer(teacher_server=server, port=0, token="cm_test_secret_token")
    await mcp.start()
    try:
        assert mcp.is_running is True
        cfg_json = json.loads(build_mcp_client_config(mcp.bound_port, "cm_test_secret_token"))
        url = cfg_json["mcpServers"]["classroom-manager"]["url"]
        headers = cfg_json["mcpServers"]["classroom-manager"]["headers"]

        def _post(body: dict, hdrs: dict[str, str]) -> tuple[int, dict]:
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json", **hdrs},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    return resp.status, json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as err:
                return err.code, json.loads(err.read().decode("utf-8"))

        # 1. Unauthorized request must be rejected with 401
        code, _ = await asyncio.to_thread(_post, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, {})
        assert code == 401

        # 2. Initialize & tools/list succeed with Bearer token
        code, init_res = await asyncio.to_thread(_post, {"jsonrpc": "2.0", "id": 1, "method": "initialize"}, headers)
        assert code == 200
        assert init_res["result"]["serverInfo"]["name"] == "classroom-manager"

        code, tools_res = await asyncio.to_thread(_post, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers)
        assert code == 200
        tool_names = {t["name"] for t in tools_res["result"]["tools"]}
        assert {
            "list_classrooms",
            "list_students",
            "run_powershell",
            "run_powershell_all",
            "send_file",
            "write_remote_file",
            "browse_local_files",
        } <= tool_names

        # 3. Call list_classrooms & browse_local_files tools
        code, call_res = await asyncio.to_thread(
            _post,
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "list_classrooms", "arguments": {}}},
            headers,
        )
        assert code == 200
        assert call_res["result"]["isError"] is False
        parsed = json.loads(call_res["result"]["content"][0]["text"])
        assert parsed["active_classroom"] == "Cab-101"
        assert len(parsed["classrooms"]) == 2

        sample_file = tmp_path / "lesson_demo.py"
        sample_file.write_text("print('hi')", encoding="utf-8")
        code, browse_res = await asyncio.to_thread(
            _post,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "browse_local_files", "arguments": {"directory": str(tmp_path), "pattern": "*.py"}},
            },
            headers,
        )
        assert code == 200
        browsed = json.loads(browse_res["result"]["content"][0]["text"])
        assert any(e["name"] == "lesson_demo.py" for e in browsed["entries"])
    finally:
        await mcp.stop()


def test_multimonitor_hd_capture_and_themes() -> None:
    mons = list_monitors()
    assert len(mons) >= 1
    assert mons[0]["index"] == 1
    w, h, jpg = capture_screen_jpeg(target_width=1920, quality=88, monitor_index=1)
    assert w > 0 and h > 0
    assert jpg.startswith(b"\xff\xd8")

    dark_qss = get_stylesheet("dark")
    light_qss = get_stylesheet("light")
    assert "#121212" in dark_qss
    assert "#F5F5F7" in light_qss


@pytest.mark.asyncio
async def test_fragmented_frame_reading() -> None:
    reader = asyncio.StreamReader()
    # Feed a valid frame 1 byte at a time to verify stream framing resilience
    payload = b'{"hello":"world"}'
    from shared.protocol import HEADER_STRUCT

    raw = HEADER_STRUCT.pack(len(payload), int(MessageType.HEARTBEAT)) + payload
    for byte in raw:
        reader.feed_data(bytes([byte]))
    reader.feed_eof()

    msg_type, data = await read_frame(reader)
    assert msg_type == MessageType.HEARTBEAT
    assert decode_json(data) == {"hello": "world"}


@pytest.mark.asyncio
async def test_end_to_end_tls_discovery_commands_and_stream(tmp_path: Path) -> None:
    teacher_dir = tmp_path / "teacher"
    student_dir = tmp_path / "student"
    secret = "TEST-KEY1-9999"
    udp_port = 47891

    t_cfg = TeacherConfig(
        initialized=True,
        password_hash=hash_password("1234"),
        classroom_id="Cab-Test",
        class_secret=secret,
        bind_host="0.0.0.0",
        tcp_port=0,  # OS assigns a free ephemeral port
        discovery_port=udp_port,
        discovery_enabled=True,
        thumb_fps=2.0,
        thumb_width=240,
    )

    connected_evt = asyncio.Event()
    frame_evt = asyncio.Event()
    received_frames: list[bytes] = []

    server = TeacherServer(
        config=t_cfg,
        data_dir=teacher_dir,
        on_client_connected=lambda _s: connected_evt.set(),
        on_screen_frame=lambda _cid, _w, _h, _m, jpg: (received_frames.append(jpg), frame_evt.set()),
    )
    await server.start()

    try:
        # 1. Verify UDP LAN discovery finds the teacher's dynamic port automatically
        found = await discover_teacher_udp("Cab-Test", secret, udp_port, timeout=2.0)
        assert found is not None
        assert found.port == server.bound_port
        assert found.cert_fingerprint == server.cert_fingerprint

        # Wrong room or secret should NOT be answered
        wrong = await discover_teacher_udp("Cab-Test", "WRONG-KEY", udp_port, timeout=0.4)
        assert wrong is None

        # 2. Start StudentClient relying ONLY on UDP auto-discovery (no manual IP!)
        locked_messages: list[str] = []
        unlocked_flag = False

        def _on_unlock() -> None:
            nonlocal unlocked_flag
            unlocked_flag = True

        s_cfg = StudentConfig(
            initialized=True,
            admin_password_hash=hash_password("1234"),
            classroom_id="Cab-Test",
            class_secret=secret,
            discovery_enabled=True,
            discovery_port=udp_port,
            manual_host="",
            pinned_fingerprint=server.cert_fingerprint,
            display_name="Парта-07",
        )
        router = CommandRouter(
            on_lock_screen=locked_messages.append,
            on_unlock_screen=_on_unlock,
        )
        demo_states: list[bool] = []
        demo_frames: list[bytes] = []
        demo_frame_evt = asyncio.Event()

        client = StudentClient(
            s_cfg,
            student_dir / "config.json",
            router,
            on_demo_control=lambda active, _t, _fs: demo_states.append(active),
            on_demo_frame=lambda jpg: (demo_frames.append(jpg), demo_frame_evt.set()),
        )
        client.start()

        try:
            await asyncio.wait_for(connected_evt.wait(), timeout=6.0)
            assert len(server.clients) == 1
            cid = next(iter(server.clients.keys()))
            assert server.clients[cid].label == "Парта-07"

            # 3. PING & System Info
            ping_res = await server.ping_client(cid)
            assert ping_res["ok"] is True
            assert "rtt_ms" in ping_res["data"]

            info_res = await server.send_command(cid, "GET_SYSTEM_INFO")
            assert info_res["ok"] is True
            assert info_res["data"]["hostname"]

            # 4. Screen Lock / Unlock
            lock_res = await server.lock_screen(cid, "Внимание на доску!")
            assert lock_res["ok"] is True
            assert locked_messages == ["Внимание на доску!"]
            assert server.clients[cid].locked is True

            unlock_res = await server.unlock_screen(cid)
            assert unlock_res["ok"] is True
            assert unlocked_flag is True
            assert server.clients[cid].locked is False

            # 5. PowerShell execution with Russian UTF-8 output
            ps_res = await server.run_powershell(cid, "Write-Output 'Привет класс 2026'", timeout=15.0)
            assert ps_res["ok"] is True
            assert ps_res["data"]["returncode"] == 0
            assert "Привет класс 2026" in ps_res["data"]["stdout"]

            # 6. Verify thumbnail JPEG stream arrives automatically
            await asyncio.wait_for(frame_evt.wait(), timeout=5.0)
            assert len(received_frames) >= 1
            assert received_frames[0].startswith(b"\xff\xd8")  # valid JPEG magic header

            # 6b. Verify chunked encrypted file transfer with custom destination & SHA-256 check
            src_file = tmp_path / "Задание_Урок_1.bin"
            sample_payload = (b"ClassroomManagerFileData2026-" * 25000)  # ~725 KB (>2 chunks)
            src_file.write_bytes(sample_payload)
            dest_folder = tmp_path / "student_received" / "Урок_1"

            ft_res = await server.send_file(
                cid,
                src_file,
                dest_dir=str(dest_folder),
                overwrite=True,
                open_after=False,
            )
            assert ft_res["ok"] is True
            saved = Path(ft_res["saved_path"])
            assert saved.exists()
            assert saved.read_bytes() == sample_payload

            # Non-overwrite mode should create a deduplicated copy "(1)"
            ft_res2 = await server.send_file(
                cid,
                src_file,
                dest_dir=str(dest_folder),
                overwrite=False,
                open_after=False,
            )
            assert ft_res2["ok"] is True
            saved2 = Path(ft_res2["saved_path"])
            assert saved2 != saved
            assert "(1)" in saved2.name
            assert saved2.read_bytes() == sample_payload

            # 6c. Verify Teacher Screen Demonstration broadcast to student
            await server.start_demo_broadcast(fps=5.0, width=320, quality=50)
            await asyncio.wait_for(demo_frame_evt.wait(), timeout=5.0)
            assert True in demo_states
            assert len(demo_frames) >= 1
            assert demo_frames[0].startswith(b"\xff\xd8")
            await server.stop_demo_broadcast()
            for _ in range(20):
                if demo_states and demo_states[-1] is False:
                    break
                await asyncio.sleep(0.05)
            assert demo_states[-1] is False

            # 7. Verify unauthenticated client with wrong secret is rejected
            bad_cfg = StudentConfig(
                initialized=True,
                admin_password_hash=hash_password("1234"),
                classroom_id="Cab-Test",
                class_secret="BAD-SECRET-0000",
                discovery_enabled=False,
                manual_host="127.0.0.1",
                manual_port=server.bound_port,
            )
            bad_states: list[str] = []
            bad_client = StudentClient(
                bad_cfg,
                tmp_path / "bad_student" / "config.json",
                CommandRouter(),
                on_state_changed=lambda st, _d: bad_states.append(st),
            )
            bad_client.start()
            try:
                for _ in range(30):
                    if "AUTH_ERROR" in bad_states:
                        break
                    await asyncio.sleep(0.1)
                assert "AUTH_ERROR" in bad_states
                assert len(server.clients) == 1  # still only the legitimate student
            finally:
                await bad_client.stop()
        finally:
            await client.stop()
    finally:
        await server.stop()


def test_grid_sorting_and_custom_order(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from teacher_app.network.server import StudentSession
    from teacher_app.ui.main_window import sort_sessions

    def _sess(cid: str, label: str, ip: str, locked: bool = False, ts: float = 0.0) -> StudentSession:
        return StudentSession(
            client_id=cid,
            hostname=label,
            display_name=label,
            username="VR.AR",
            os_info="Windows 11",
            ip=ip,
            screen_width=1920,
            screen_height=1080,
            writer=SimpleNamespace(),  # type: ignore[arg-type]
            locked=locked,
            connected_at=ts,
        )

    items = [
        _sess("c5", "PC5", "192.168.0.46", locked=False, ts=1.0),
        _sess("c10", "PC10", "192.168.0.4", locked=True, ts=2.0),
        _sess("c1", "PC1", "192.168.0.5", locked=False, ts=3.0),
        _sess("c2", "PC2", "192.168.0.27", locked=False, ts=4.0),
    ]

    assert [s.label for s in sort_sessions(items, "natural_asc")] == ["PC1", "PC2", "PC5", "PC10"]
    assert [s.label for s in sort_sessions(items, "natural_desc")] == ["PC10", "PC5", "PC2", "PC1"]
    assert [s.label for s in sort_sessions(items, "ip_asc")] == ["PC10", "PC1", "PC2", "PC5"]
    assert [s.label for s in sort_sessions(items, "locked_first")] == ["PC10", "PC1", "PC2", "PC5"]
    assert [s.label for s in sort_sessions(items, "connected_at")] == ["PC5", "PC10", "PC1", "PC2"]
    assert [s.label for s in sort_sessions(items, "custom", ["c2", "c10", "c1", "c5"])] == [
        "PC2",
        "PC10",
        "PC1",
        "PC5",
    ]

    cfg_path = tmp_path / "teacher_grid.json"
    cfg = TeacherConfig(
        initialized=True,
        grid_sort_mode="custom",
        grid_card_width=420,
        grid_custom_order={"vr1": ["c2", "c10"]},
    )
    save_config(cfg_path, cfg)
    loaded = load_config(cfg_path, TeacherConfig)
    assert loaded.grid_sort_mode == "custom"
    assert loaded.grid_card_width == 420
    assert loaded.grid_custom_order == {"vr1": ["c2", "c10"]}
