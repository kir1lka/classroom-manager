"""3-tier Smart LAN Discovery supporting multiple simultaneous Teacher servers."""

from __future__ import annotations

import asyncio
import logging
import socket
from dataclasses import dataclass

from shared.config import StudentConfig
from shared.protocol import decode_discovery_packet, encode_discovery_packet
from shared.security import compute_discovery_tag, generate_nonce

logger = logging.getLogger("classroom_manager.student.discovery")


@dataclass
class DiscoveredEndpoint:
    host: str
    port: int
    server_name: str = ""
    cert_fingerprint: str = ""
    source: str = "udp_broadcast"


def _candidate_broadcast_targets() -> list[str]:
    targets = ["255.255.255.255"]
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127."):
                parts = ip.split(".")
                if len(parts) == 4:
                    bcast = f"{parts[0]}.{parts[1]}.{parts[2]}.255"
                    if bcast not in targets:
                        targets.append(bcast)
    except OSError:
        pass
    targets.append("127.0.0.1")
    return targets


class _MultiProbeProtocol(asyncio.DatagramProtocol):
    """Collects OFFER packets from ALL matching Teacher servers on the LAN."""

    def __init__(
        self,
        expected_room: str,
        expected_tag: str,
        expected_nonce: str,
        found_map: dict[tuple[str, int], DiscoveredEndpoint],
        first_event: asyncio.Event | None = None,
    ) -> None:
        self._expected_room = expected_room.strip().lower()
        self._expected_tag = expected_tag
        self._expected_nonce = expected_nonce
        self._found_map = found_map
        self._first_event = first_event

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        packet = decode_discovery_packet(data)
        if not packet or packet.get("type") != "OFFER":
            return
        if str(packet.get("classroom_id", "")).strip().lower() != self._expected_room:
            return
        if str(packet.get("secret_tag", "")) != self._expected_tag:
            return
        if str(packet.get("nonce", "")) != self._expected_nonce:
            return

        port = int(packet.get("tcp_port", 45455))
        fp = str(packet.get("cert_fingerprint", ""))
        key = (addr[0], port)
        # Deduplicate multi-NIC replies from the same Teacher server by TLS cert fingerprint
        if fp and any(ep.cert_fingerprint == fp for ep in self._found_map.values()):
            return
        if key not in self._found_map:
            self._found_map[key] = DiscoveredEndpoint(
                host=addr[0],
                port=port,
                server_name=str(packet.get("server_name", "")),
                cert_fingerprint=fp,
                source="udp_broadcast",
            )
            if self._first_event is not None:
                self._first_event.set()


async def discover_all_teachers_udp(
    classroom_id: str,
    class_secret: str,
    discovery_port: int,
    timeout: float = 1.2,
) -> list[DiscoveredEndpoint]:
    """Tier 1: Broadcast UDP probe on LAN and collect ALL matching Teacher servers."""
    loop = asyncio.get_running_loop()
    found_map: dict[tuple[str, int], DiscoveredEndpoint] = {}
    tag = compute_discovery_tag(classroom_id, class_secret)
    nonce = generate_nonce(8)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(("0.0.0.0", 0))
    sock.setblocking(False)

    transport, _ = await loop.create_datagram_endpoint(
        lambda: _MultiProbeProtocol(classroom_id, tag, nonce, found_map),
        sock=sock,
    )
    try:
        probe = encode_discovery_packet(
            {
                "type": "DISCOVER",
                "classroom_id": classroom_id,
                "secret_tag": tag,
                "nonce": nonce,
            }
        )
        for target in _candidate_broadcast_targets():
            try:
                transport.sendto(probe, (target, discovery_port))
            except OSError:
                continue

        await asyncio.sleep(max(0.2, timeout))
        return list(found_map.values())
    finally:
        transport.close()


async def discover_teacher_udp(
    classroom_id: str,
    class_secret: str,
    discovery_port: int,
    timeout: float = 2.0,
) -> DiscoveredEndpoint | None:
    """Return the first matching Teacher server found via UDP Broadcast."""
    loop = asyncio.get_running_loop()
    found_map: dict[tuple[str, int], DiscoveredEndpoint] = {}
    first_evt = asyncio.Event()
    tag = compute_discovery_tag(classroom_id, class_secret)
    nonce = generate_nonce(8)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(("0.0.0.0", 0))
    sock.setblocking(False)

    transport, _ = await loop.create_datagram_endpoint(
        lambda: _MultiProbeProtocol(classroom_id, tag, nonce, found_map, first_event=first_evt),
        sock=sock,
    )
    try:
        probe = encode_discovery_packet(
            {
                "type": "DISCOVER",
                "classroom_id": classroom_id,
                "secret_tag": tag,
                "nonce": nonce,
            }
        )
        for target in _candidate_broadcast_targets():
            try:
                transport.sendto(probe, (target, discovery_port))
            except OSError:
                continue

        try:
            await asyncio.wait_for(first_evt.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        return next(iter(found_map.values()), None)
    finally:
        transport.close()


async def resolve_teacher_candidates(config: StudentConfig, udp_timeout: float = 1.2) -> list[DiscoveredEndpoint]:
    """Return ordered Teacher connection candidates across all 3 discovery tiers (supports multiple teachers)."""
    candidates: list[DiscoveredEndpoint] = []
    seen: set[tuple[str, int]] = set()

    def _add(ep: DiscoveredEndpoint) -> None:
        key = (ep.host, ep.port)
        if ep.host and key not in seen:
            seen.add(key)
            candidates.append(ep)

    # Tier 1: UDP Broadcast Discovery (collects ALL teachers managing this classroom)
    if config.discovery_enabled and config.class_secret:
        found_list = await discover_all_teachers_udp(
            classroom_id=config.classroom_id,
            class_secret=config.class_secret,
            discovery_port=config.discovery_port,
            timeout=udp_timeout,
        )
        for found in found_list:
            logger.info("UDP Discovery found teacher at %s:%d (%s)", found.host, found.port, found.server_name)
            _add(found)

    # Tier 2: Manual host(s) — supports comma-separated hosts too (e.g. "192.168.0.2, 192.168.0.3")
    if config.manual_host.strip():
        for raw_host in config.manual_host.split(","):
            host_clean = raw_host.strip()
            if not host_clean:
                continue
            port = int(config.manual_port or 45455)
            if ":" in host_clean and host_clean.count(":") == 1:
                h_part, p_part = host_clean.split(":", 1)
                if p_part.isdigit():
                    host_clean = h_part.strip()
                    port = int(p_part)
            _add(DiscoveredEndpoint(host=host_clean, port=port, source="manual"))

    # Tier 3: Cached last server hostname & IP (only when no live UDP/manual found yet)
    if not candidates:
        if config.last_server_name.strip():
            _add(
                DiscoveredEndpoint(
                    host=config.last_server_name.strip(),
                    port=int(config.last_server_port or 45455),
                    server_name=config.last_server_name.strip(),
                    source="cached_hostname",
                )
            )
        if config.last_server_host.strip():
            _add(
                DiscoveredEndpoint(
                    host=config.last_server_host.strip(),
                    port=int(config.last_server_port or 45455),
                    server_name=config.last_server_name.strip(),
                    source="cached_ip",
                )
            )

    return candidates
