"""UDP LAN discovery responder so students find the teacher PC without static IPs."""

from __future__ import annotations

import asyncio
import logging
import socket
from typing import Callable

from shared.protocol import decode_discovery_packet, encode_discovery_packet
from shared.security import compute_discovery_tag

logger = logging.getLogger("classroom_manager.teacher.discovery")


def get_local_ipv4_addresses() -> list[str]:
    """Return non-loopback local IPv4 addresses of this machine."""
    addrs: list[str] = []
    try:
        # Primary outbound interface IP (no packets are actually transmitted for UDP connect)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            primary = s.getsockname()[0]
            if primary and not primary.startswith("127."):
                addrs.append(primary)
    except OSError:
        pass

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127.") and ip not in addrs:
                addrs.append(ip)
    except OSError:
        pass

    return addrs or ["127.0.0.1"]


class _DiscoveryProtocol(asyncio.DatagramProtocol):
    def __init__(
        self,
        get_classroom_id: Callable[[], str],
        get_class_secret: Callable[[], str],
        get_tcp_port: Callable[[], int],
        get_cert_fingerprint: Callable[[], str],
        get_classrooms: Callable[[], list[dict[str, str]]] | None = None,
    ) -> None:
        self._get_classroom_id = get_classroom_id
        self._get_class_secret = get_class_secret
        self._get_tcp_port = get_tcp_port
        self._get_cert_fingerprint = get_cert_fingerprint
        self._get_classrooms = get_classrooms
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        packet = decode_discovery_packet(data)
        if not packet or packet.get("type") != "DISCOVER":
            return

        req_room = str(packet.get("classroom_id", "")).strip().lower()
        req_tag = str(packet.get("secret_tag", ""))

        candidates = (
            self._get_classrooms()
            if self._get_classrooms is not None
            else [{"id": self._get_classroom_id(), "secret": self._get_class_secret()}]
        )

        matched_room = ""
        matched_tag = ""
        for room in candidates:
            rid = str(room.get("id", "")).strip()
            sec = str(room.get("secret", "")).strip()
            if not rid or not sec:
                continue
            expected_tag = compute_discovery_tag(rid, sec)
            if req_room == rid.lower() and req_tag == expected_tag:
                matched_room = rid
                matched_tag = expected_tag
                break

        if not matched_room:
            return

        offer = {
            "type": "OFFER",
            "classroom_id": matched_room,
            "secret_tag": matched_tag,
            "tcp_port": self._get_tcp_port(),
            "server_name": socket.gethostname(),
            "cert_fingerprint": self._get_cert_fingerprint(),
            "nonce": str(packet.get("nonce", "")),
        }
        if self.transport is not None:
            self.transport.sendto(encode_discovery_packet(offer), addr)
            logger.debug("Replied to LAN discovery probe for room=%s from %s:%s", matched_room, addr[0], addr[1])


class DiscoveryResponder:
    """Listens for student UDP broadcast probes and replies with current Teacher endpoint."""

    def __init__(
        self,
        discovery_port: int,
        get_classroom_id: Callable[[], str],
        get_class_secret: Callable[[], str],
        get_tcp_port: Callable[[], int],
        get_cert_fingerprint: Callable[[], str],
        get_classrooms: Callable[[], list[dict[str, str]]] | None = None,
    ) -> None:
        self.discovery_port = discovery_port
        self._get_classroom_id = get_classroom_id
        self._get_class_secret = get_class_secret
        self._get_tcp_port = get_tcp_port
        self._get_cert_fingerprint = get_cert_fingerprint
        self._get_classrooms = get_classrooms
        self._transport: asyncio.DatagramTransport | None = None

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(("0.0.0.0", self.discovery_port))
        sock.setblocking(False)

        self._transport, _ = await loop.create_datagram_endpoint(
            lambda: _DiscoveryProtocol(
                self._get_classroom_id,
                self._get_class_secret,
                self._get_tcp_port,
                self._get_cert_fingerprint,
                self._get_classrooms,
            ),
            sock=sock,
        )
        logger.info("UDP LAN Discovery Responder listening on port %d", self.discovery_port)

    async def stop(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None
            logger.info("UDP LAN Discovery Responder stopped")
