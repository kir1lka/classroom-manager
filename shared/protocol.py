"""Binary-framed async network protocol and UDP LAN discovery packet helpers."""

from __future__ import annotations

import asyncio
import json
import struct
from enum import IntEnum
from typing import Any

PROTOCOL_VERSION = 1
HEADER_STRUCT = struct.Struct("!IB")  # 4-byte length + 1-byte message type
SCREEN_HEADER_STRUCT = struct.Struct("!HHB")  # width, height, mode_flag
MAX_FRAME_SIZE = 16 * 1024 * 1024  # 16 MiB safety limit
DISCOVERY_MAGIC = b"CLRMGR1"


class ProtocolError(Exception):
    """Raised when a malformed or oversized frame is received."""


class MessageType(IntEnum):
    # Authentication & handshake
    AUTH_CHALLENGE = 1
    AUTH_RESPONSE = 2
    AUTH_RESULT = 3

    # Session health
    HEARTBEAT = 10
    HEARTBEAT_ACK = 11

    # Command RPC (PING, SYS_INFO, POWERSHELL, LOCK_SCREEN, UNLOCK_SCREEN, POWER_ACTION, MESSAGE)
    CMD_REQUEST = 20
    CMD_RESPONSE = 21

    # Screen streaming
    SCREEN_CONTROL = 30
    SCREEN_FRAME = 31

    # Remote mouse/keyboard control
    REMOTE_INPUT = 40

    # Chunked file transfer (Teacher -> Student)
    FILE_START = 50
    FILE_CHUNK = 51
    FILE_END = 52
    FILE_RESULT = 53

    # Teacher screen demonstration broadcast (Teacher -> Students)
    DEMO_CONTROL = 60
    DEMO_FRAME = 61


class ScreenMode(IntEnum):
    OFF = 0
    THUMB = 1
    LIVE = 2


async def send_raw(writer: asyncio.StreamWriter, msg_type: MessageType, payload: bytes) -> None:
    """Send a length-prefixed binary frame."""
    if len(payload) > MAX_FRAME_SIZE:
        raise ProtocolError(f"Outgoing frame too large: {len(payload)} bytes")
    header = HEADER_STRUCT.pack(len(payload), int(msg_type))
    writer.write(header + payload)
    await writer.drain()


async def send_json(
    writer: asyncio.StreamWriter,
    msg_type: MessageType,
    data: dict[str, Any],
) -> None:
    """Encode a JSON object as UTF-8 and send it as a binary frame."""
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    await send_raw(writer, msg_type, payload)


async def read_frame(reader: asyncio.StreamReader) -> tuple[MessageType, bytes]:
    """Read a single length-prefixed frame from an asyncio stream."""
    header_bytes = await reader.readexactly(HEADER_STRUCT.size)
    length, raw_type = HEADER_STRUCT.unpack(header_bytes)
    if length > MAX_FRAME_SIZE:
        raise ProtocolError(f"Incoming frame exceeds max size: {length} bytes")
    try:
        msg_type = MessageType(raw_type)
    except ValueError as exc:
        raise ProtocolError(f"Unknown message type: {raw_type}") from exc
    payload = await reader.readexactly(length) if length > 0 else b""
    return msg_type, payload


def decode_json(payload: bytes) -> dict[str, Any]:
    """Decode a UTF-8 JSON payload."""
    try:
        obj = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"Invalid JSON payload: {exc}") from exc
    if not isinstance(obj, dict):
        raise ProtocolError("Expected JSON object payload")
    return obj


def pack_screen_frame(width: int, height: int, mode: ScreenMode, jpeg_bytes: bytes) -> bytes:
    """Pack screen dimensions, stream mode, and JPEG bytes into a single frame payload."""
    return SCREEN_HEADER_STRUCT.pack(width, height, int(mode)) + jpeg_bytes


def unpack_screen_frame(payload: bytes) -> tuple[int, int, ScreenMode, bytes]:
    """Unpack screen dimensions, mode, and JPEG bytes from a SCREEN_FRAME payload."""
    if len(payload) < SCREEN_HEADER_STRUCT.size:
        raise ProtocolError("Screen frame payload too short")
    width, height, raw_mode = SCREEN_HEADER_STRUCT.unpack_from(payload, 0)
    try:
        mode = ScreenMode(raw_mode)
    except ValueError as exc:
        raise ProtocolError(f"Invalid screen mode: {raw_mode}") from exc
    return width, height, mode, payload[SCREEN_HEADER_STRUCT.size :]


FILE_ID_LEN = 32


def pack_file_chunk(transfer_id: str, chunk: bytes) -> bytes:
    """Pack a 32-char hex transfer_id and raw file chunk bytes."""
    tid_bytes = transfer_id.encode("ascii")
    if len(tid_bytes) != FILE_ID_LEN:
        raise ProtocolError(f"transfer_id must be {FILE_ID_LEN} ASCII chars")
    return tid_bytes + chunk


def unpack_file_chunk(payload: bytes) -> tuple[str, bytes]:
    """Unpack a FILE_CHUNK payload into (transfer_id, chunk_bytes)."""
    if len(payload) < FILE_ID_LEN:
        raise ProtocolError("File chunk payload too short")
    transfer_id = payload[:FILE_ID_LEN].decode("ascii", errors="strict")
    return transfer_id, payload[FILE_ID_LEN:]


def encode_discovery_packet(data: dict[str, Any]) -> bytes:
    """Encode a UDP LAN discovery packet with magic header."""
    return DISCOVERY_MAGIC + json.dumps(data, separators=(",", ":")).encode("utf-8")


def decode_discovery_packet(raw: bytes) -> dict[str, Any] | None:
    """Decode a UDP LAN discovery packet; returns None if magic header does not match."""
    if not raw.startswith(DISCOVERY_MAGIC):
        return None
    try:
        obj = json.loads(raw[len(DISCOVERY_MAGIC) :].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return obj if isinstance(obj, dict) else None
