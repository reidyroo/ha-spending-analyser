"""Security utilities for HA Spending Analyser."""
from __future__ import annotations

import ipaddress
import logging
import os
import re
import time
from collections import defaultdict
from typing import Any

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path validation
# ---------------------------------------------------------------------------

def validate_path_within(path: str, allowed_base: str) -> str:
    """Resolve path and confirm it stays inside allowed_base.

    Returns the resolved absolute path, or raises ValueError.
    This prevents directory traversal via '../' sequences.
    """
    resolved = os.path.realpath(os.path.abspath(path))
    base     = os.path.realpath(os.path.abspath(allowed_base))
    if not resolved.startswith(base + os.sep) and resolved != base:
        raise ValueError(
            f"Path '{path}' is outside the allowed directory '{allowed_base}'"
        )
    return resolved


# ---------------------------------------------------------------------------
# Host validation (SSRF / misconfiguration guard)
# ---------------------------------------------------------------------------

# Reject obviously dangerous hostnames / patterns
_BLOCKED_HOST_PATTERNS = re.compile(
    r"(localhost|127\.|0\.0\.0\.0|::1|metadata\.google"
    r"|169\.254\.|100\.64\.|fd[0-9a-f]{2}:)",
    re.IGNORECASE,
)


def validate_ollama_host(host: str) -> str:
    """Return the host if it looks reasonable, raise ValueError otherwise.

    Blocks loopback and link-local addresses that could be used to hit
    internal services. LAN private ranges (192.168.x.x, 10.x.x.x) are
    intentionally allowed because Ollama runs on the local network.
    """
    host = host.strip().lower()
    if not host:
        raise ValueError("Ollama host must not be empty")
    if len(host) > 253:
        raise ValueError("Ollama host name is too long")
    if _BLOCKED_HOST_PATTERNS.search(host):
        raise ValueError(
            f"Host '{host}' is not allowed. Use the Surface Pro's LAN IP address."
        )
    # If it looks like a raw IP, do a stricter parse
    try:
        addr = ipaddress.ip_address(host)
        if addr.is_loopback:
            raise ValueError(f"Loopback address '{host}' is not allowed")
    except ValueError as exc:
        # Not an IP address — hostname is fine (will be validated by DNS at connect time)
        if "not allowed" in str(exc) or "Loopback" in str(exc):
            raise
    return host


def validate_port(port: int | str) -> int:
    """Return port as int if in range 1–65535, else raise ValueError."""
    try:
        p = int(port)
    except (TypeError, ValueError):
        raise ValueError(f"Port must be an integer, got {port!r}")
    if not (1 <= p <= 65535):
        raise ValueError(f"Port {p} is out of range (1–65535)")
    return p


def validate_model_name(model: str) -> str:
    """Return model name if it contains only safe characters."""
    model = model.strip()
    if not model:
        raise ValueError("Model name must not be empty")
    if len(model) > 128:
        raise ValueError("Model name is too long (max 128 chars)")
    # Ollama model names: alphanumeric, hyphens, dots, colons, underscores, slashes
    if not re.fullmatch(r"[a-zA-Z0-9_.:\-/]+", model):
        raise ValueError(f"Model name '{model}' contains invalid characters")
    return model


# ---------------------------------------------------------------------------
# Prompt injection mitigation
# ---------------------------------------------------------------------------

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]")


def sanitize_prompt_input(text: str, max_len: int = 500) -> str:
    """Strip control characters and cap length before injecting into an AI prompt."""
    text = _CONTROL_CHARS.sub("", text)
    text = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    return text[:max_len].strip()


# ---------------------------------------------------------------------------
# Simple in-memory rate limiter (per remote IP)
# ---------------------------------------------------------------------------

class RateLimiter:
    """Sliding-window rate limiter stored in hass.data.

    Usage:
        limiter = RateLimiter.get(hass, "upload", max_calls=5, window_seconds=60)
        if not limiter.allow(remote_ip):
            return 429
    """

    def __init__(self, max_calls: int, window_seconds: float) -> None:
        self._max   = max_calls
        self._win   = window_seconds
        self._log: dict[str, list[float]] = defaultdict(list)

    @classmethod
    def get(
        cls,
        hass_data: dict[str, Any],
        key: str,
        max_calls: int,
        window_seconds: float,
    ) -> "RateLimiter":
        """Retrieve or create a limiter stored in hass.data."""
        store_key = f"_rate_limiter_{key}"
        if store_key not in hass_data:
            hass_data[store_key] = cls(max_calls, window_seconds)
        return hass_data[store_key]

    def allow(self, remote_ip: str) -> bool:
        now = time.monotonic()
        calls = self._log[remote_ip]
        # Prune old entries
        self._log[remote_ip] = [t for t in calls if now - t < self._win]
        if len(self._log[remote_ip]) >= self._max:
            _LOGGER.warning("Rate limit exceeded for %s", remote_ip)
            return False
        self._log[remote_ip].append(now)
        return True


# ---------------------------------------------------------------------------
# File content validation (magic bytes)
# ---------------------------------------------------------------------------

def validate_statement_content(content: bytes, filename: str) -> None:
    """Raise ValueError if content doesn't match expected statement formats.

    Catches cases where an attacker renames a non-statement file to .csv.
    We only reject binary content — text/CSV has no reliable magic bytes.
    """
    # Reject null bytes (binary file masquerading as text)
    if b"\x00" in content[:4096]:
        raise ValueError("File appears to be binary — only text-based statements are accepted")

    ext = os.path.splitext(filename)[1].lower()
    text_head = content[:256].lstrip(b"\xef\xbb\xbf")  # strip UTF-8 BOM

    if ext in (".ofx", ".qfx"):
        if not (text_head.startswith(b"OFXHEADER") or b"<OFX>" in text_head or b"<ofx>" in text_head):
            raise ValueError("File does not look like a valid OFX/QFX statement")

    if ext == ".qif":
        if not text_head.startswith(b"!Type:"):
            raise ValueError("File does not look like a valid QIF statement")

    # CSV — just check it's plausibly text (already covered by null-byte check above)
