"""Small trusted-side ClamAV INSTREAM client."""

from __future__ import annotations

import socket
import struct


class ClamAVUnavailable(RuntimeError):
    """The scanner could not return a trustworthy verdict."""


class ClamAVScanner:
    """Scan exact bytes through clamd without exposing paths or credentials."""

    version = "clamd-instream-v1"

    def __init__(self, host: str = "clamav", port: int = 3310, timeout: float = 15.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    def scan(self, content: bytes) -> bool:
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as connection:
                connection.settimeout(self.timeout)
                connection.sendall(b"zINSTREAM\0")
                for offset in range(0, len(content), 1024 * 1024):
                    chunk = content[offset:offset + 1024 * 1024]
                    connection.sendall(struct.pack("!I", len(chunk)))
                    connection.sendall(chunk)
                connection.sendall(struct.pack("!I", 0))
                response = connection.recv(4096)
        except OSError as error:
            raise ClamAVUnavailable from error
        verdict = response.decode("utf-8", errors="replace").strip("\x00 \r\n")
        if verdict.endswith("OK"):
            return True
        if verdict.endswith("FOUND"):
            return False
        raise ClamAVUnavailable


__all__ = ["ClamAVScanner", "ClamAVUnavailable"]
