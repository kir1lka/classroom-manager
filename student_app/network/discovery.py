"""3-tier Smart LAN Discovery so Student finds Teacher with dynamic DHCP IPs."""

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
    # Loopback fallback makes local single-PC testing work seamlessly too
    targets.append("127.0.0.1")
    return targets


class _ProbeProtocol(asyncio.DatagramProtocol):
    def __init__(
        self,
        expected_room: str,
        expected_tag: str,
        expected_nonce: str,
        result_future: asyncio.Future[DiscoveredEndpoint],
    ) -> None:
        self._expected_room = expected_room.strip().lower()
        self._expected_tag = expected_tag
        self._expected_nonce = expected_nonce
        self._result_future = result_future

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if self._result_future.done():
            return
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
        endpoint = DiscoveredEndpoint(
            host=addr[0],
            port=port,
            server_name=str(packet.get("server_name", "")),
            cert_fingerprint=str(packet.get("cert_fingerprint", "")),
            source="udp_broadcast",
        )
        self._result_future.set_result(endpoint)


async def discover_teacher_udp(
    classroom_id: str,
    class_secret: str,
    discovery_port: int,
    timeout: float = 2.0,
) -> DiscoveredEndpoint | None:
    """Tier 1: Broadcast UDP probe on LAN to find Teacher's current dynamic IP."""
    loop = asyncio.get_running_loop()
    result_future: asyncio.Future[DiscoveredEndpoint] = loop.create_future()
    tag = compute_discovery_tag(classroom_id, class_secret)
    nonce = generate_nonce(8)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(("0.0.0.0", 0))
    sock.setblocking(False)

    transport, _ = await loop.create_datagram_endpoint(
        lambda: _ProbeProtocol(classroom_id, tag, nonce, result_future),
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

        return await asyncio.wait_for(result_future, timeout=timeout)
    except asyncio.TimeoutError:
        return None
    finally:
        transport.close()


async def resolve_teacher_candidates(config: StudentConfig, udp_timeout: float = 2.0) -> list[DiscoveredEndpoint]:
    """Return ordered Teacher connection candidates across all 3 discovery tiers."""
    candidates: list[DiscoveredEndpoint] = []
    seen: set[tuple[str, int]] = set()

    def _add(ep: DiscoveredEndpoint) -> None:
        key = (ep.host, ep.port)
        if ep.host and key not in seen:
            seen.add(key)
            candidates.append(ep)

    # Tier 1: UDP Broadcast Discovery (handles dynamic DHCP IP changes automatically)
    if config.discovery_enabled and config.class_secret:
        found = await discover_teacher_udp(
            classroom_id=config.classroom_id,
            class_secret=config.class_secret,
            discovery_port=config.discovery_port,
            timeout=udp_timeout,
        )
        if found:
            logger.info("UDP Discovery found teacher at %s:%d (%s)", found.host, found.port, found.server_name)
            _add(found)

    # Tier 2: Manual host (IP or hostname) if configured
    if config.manual_host.strip():
        _add(
            DiscoveredEndpoint(
                host=config.manual_host.strip(),
                port=int(config.manual_port or 45455),
                source="manual",
            )
        )

    # Tier 3: Cached last server hostname (DNS/NetBIOS) and last known IP
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
