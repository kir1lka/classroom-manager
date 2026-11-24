"""Cryptographic primitives: password hashing, HMAC session auth, and TLS certificates."""

from __future__ import annotations

import datetime
import hashlib
import hmac
import ipaddress
import os
import secrets
import socket
import ssl
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32


def hash_password(password: str) -> str:
    """Hash a password with scrypt and a random 16-byte salt."""
    if not password:
        raise ValueError("Password must not be empty")
    salt = os.urandom(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
    )
    return f"scrypt${salt.hex()}${derived.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a plaintext password against a stored scrypt hash."""
    if not password or not stored_hash:
        return False
    parts = stored_hash.split("$")
    if len(parts) != 3 or parts[0] != "scrypt":
        return False
    try:
        salt = bytes.fromhex(parts[1])
        expected = bytes.fromhex(parts[2])
    except ValueError:
        return False
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=len(expected),
    )
    return hmac.compare_digest(derived, expected)


def generate_nonce(num_bytes: int = 24) -> str:
    """Generate a cryptographically secure random hex nonce."""
    return secrets.token_hex(num_bytes)


def generate_class_secret() -> str:
    """Generate a human-readable default class secret key (e.g. ABCD-1234-EFGH)."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    groups = ["".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3)]
    return "-".join(groups)


def compute_discovery_tag(classroom_id: str, class_secret: str) -> str:
    """Derive a non-reversible tag for UDP LAN discovery so the secret is never broadcast."""
    raw = f"discover:{classroom_id.strip().lower()}:{class_secret}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def compute_session_hmac(class_secret: str, classroom_id: str, nonce: str) -> str:
    """Compute HMAC-SHA256 challenge response for mutual session authentication."""
    key = class_secret.encode("utf-8")
    msg = f"{classroom_id.strip().lower()}:{nonce}".encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def verify_session_hmac(
    class_secret: str,
    classroom_id: str,
    nonce: str,
    candidate_hmac: str,
) -> bool:
    """Verify a client's challenge-response HMAC in constant time."""
    if not candidate_hmac:
        return False
    expected = compute_session_hmac(class_secret, classroom_id, nonce)
    return hmac.compare_digest(expected, candidate_hmac)


def _format_fingerprint(digest_bytes: bytes) -> str:
    return ":".join(f"{b:02X}" for b in digest_bytes)


def get_cert_fingerprint(cert_path: Path) -> str:
    """Return the SHA-256 fingerprint of a PEM X.509 certificate."""
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    return _format_fingerprint(cert.fingerprint(hashes.SHA256()))


def get_peer_cert_fingerprint(ssl_object: ssl.SSLObject | None) -> str:
    """Return the SHA-256 fingerprint of the remote peer's DER certificate."""
    if ssl_object is None:
        return ""
    der = ssl_object.getpeercert(binary_form=True)
    if not der:
        return ""
    return _format_fingerprint(hashlib.sha256(der).digest())


def ensure_tls_certificate(
    cert_path: Path,
    key_path: Path,
    common_name: str | None = None,
) -> str:
    """Generate a self-signed RSA-2048 TLS certificate if missing; return SHA-256 fingerprint."""
    if cert_path.exists() and key_path.exists():
        return get_cert_fingerprint(cert_path)

    cert_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.parent.mkdir(parents=True, exist_ok=True)

    cn = common_name or socket.gethostname() or "ClassroomTeacher"
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ClassroomManager LAN"),
            x509.NameAttribute(NameOID.COMMON_NAME, cn),
        ]
    )

    now = datetime.datetime.now(datetime.timezone.utc)
    san_entries: list[x509.GeneralName] = [
        x509.DNSName(cn),
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
    ]

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1825))
        .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(private_key, hashes.SHA256())
    )

    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return _format_fingerprint(cert.fingerprint(hashes.SHA256()))


def create_server_ssl_context(cert_path: Path, key_path: Path) -> ssl.SSLContext:
    """Create a hardened TLS 1.2+ server SSLContext."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    return ctx


def create_client_ssl_context() -> ssl.SSLContext:
    """Create a TLS 1.2+ client SSLContext for LAN self-signed certs.

    Peer authenticity is verified via SHA-256 certificate pinning + HMAC challenge-response.
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx
