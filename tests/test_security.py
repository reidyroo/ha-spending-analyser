"""Tests for security utilities."""
import os
import time
import pytest

from custom_components.spending_analyser.security import (
    RateLimiter,
    sanitize_prompt_input,
    validate_model_name,
    validate_ollama_host,
    validate_path_within,
    validate_port,
    validate_statement_content,
)


# ── validate_path_within ──────────────────────────────────────────────────────

def test_valid_path_within_allowed(tmp_path):
    target = tmp_path / "statements" / "file.csv"
    target.parent.mkdir()
    target.touch()
    result = validate_path_within(str(target), str(tmp_path))
    assert result == str(target.resolve())


def test_path_traversal_rejected(tmp_path):
    evil = str(tmp_path / ".." / "etc" / "passwd")
    with pytest.raises(ValueError, match="outside"):
        validate_path_within(evil, str(tmp_path))


def test_exact_base_path_rejected(tmp_path):
    # The base dir itself is not a valid file target
    with pytest.raises(ValueError):
        validate_path_within(str(tmp_path) + "/../other", str(tmp_path))


# ── validate_ollama_host ──────────────────────────────────────────────────────

def test_valid_lan_ip_allowed():
    assert validate_ollama_host("192.168.1.50") == "192.168.1.50"


def test_valid_hostname_allowed():
    assert validate_ollama_host("surface-pro.local") == "surface-pro.local"


def test_loopback_ip_rejected():
    with pytest.raises(ValueError):
        validate_ollama_host("127.0.0.1")


def test_localhost_string_rejected():
    with pytest.raises(ValueError):
        validate_ollama_host("localhost")


def test_link_local_rejected():
    with pytest.raises(ValueError):
        validate_ollama_host("169.254.0.1")


def test_empty_host_rejected():
    with pytest.raises(ValueError):
        validate_ollama_host("")


# ── validate_port ─────────────────────────────────────────────────────────────

def test_valid_port():
    assert validate_port(11434) == 11434


def test_port_1_valid():
    assert validate_port(1) == 1


def test_port_65535_valid():
    assert validate_port(65535) == 65535


def test_port_0_rejected():
    with pytest.raises(ValueError):
        validate_port(0)


def test_port_65536_rejected():
    with pytest.raises(ValueError):
        validate_port(65536)


def test_port_string_converted():
    assert validate_port("11434") == 11434


def test_port_non_numeric_rejected():
    with pytest.raises(ValueError):
        validate_port("abc")


# ── validate_model_name ───────────────────────────────────────────────────────

def test_valid_model_name():
    assert validate_model_name("phi3:mini") == "phi3:mini"


def test_model_with_tag():
    assert validate_model_name("llama3.2:3b") == "llama3.2:3b"


def test_model_with_namespace():
    assert validate_model_name("library/phi3:latest") == "library/phi3:latest"


def test_model_empty_rejected():
    with pytest.raises(ValueError):
        validate_model_name("")


def test_model_shell_injection_rejected():
    with pytest.raises(ValueError):
        validate_model_name("phi3; rm -rf /")


def test_model_too_long_rejected():
    with pytest.raises(ValueError):
        validate_model_name("a" * 129)


# ── sanitize_prompt_input ─────────────────────────────────────────────────────

def test_normal_text_unchanged():
    assert sanitize_prompt_input("Costa Coffee Reading") == "Costa Coffee Reading"


def test_null_bytes_stripped():
    assert "\x00" not in sanitize_prompt_input("Costa\x00Coffee")


def test_control_chars_stripped():
    result = sanitize_prompt_input("Coffee\x01\x02\x1fShop")
    assert "\x01" not in result
    assert "\x1f" not in result


def test_newlines_collapsed():
    result = sanitize_prompt_input("Line1\nLine2\r\nLine3")
    assert "\n" not in result
    assert "\r" not in result


def test_truncated_to_max_len():
    long = "A" * 600
    assert len(sanitize_prompt_input(long, max_len=500)) == 500


def test_custom_max_len():
    assert len(sanitize_prompt_input("Hello World", max_len=5)) == 5


# ── RateLimiter ───────────────────────────────────────────────────────────────

def test_allows_within_limit():
    store = {}
    limiter = RateLimiter.get(store, "test", max_calls=3, window_seconds=60)
    assert limiter.allow("1.2.3.4") is True
    assert limiter.allow("1.2.3.4") is True
    assert limiter.allow("1.2.3.4") is True


def test_blocks_after_limit():
    store = {}
    limiter = RateLimiter.get(store, "test2", max_calls=2, window_seconds=60)
    limiter.allow("10.0.0.1")
    limiter.allow("10.0.0.1")
    assert limiter.allow("10.0.0.1") is False


def test_different_ips_independent():
    store = {}
    limiter = RateLimiter.get(store, "test3", max_calls=1, window_seconds=60)
    assert limiter.allow("1.1.1.1") is True
    assert limiter.allow("2.2.2.2") is True  # different IP, not blocked


def test_window_expiry():
    store = {}
    limiter = RateLimiter.get(store, "test4", max_calls=1, window_seconds=0.05)
    limiter.allow("5.5.5.5")
    time.sleep(0.1)
    assert limiter.allow("5.5.5.5") is True  # window expired


def test_get_returns_same_instance():
    store = {}
    a = RateLimiter.get(store, "shared", max_calls=5, window_seconds=60)
    b = RateLimiter.get(store, "shared", max_calls=5, window_seconds=60)
    assert a is b


# ── validate_statement_content ────────────────────────────────────────────────

def test_valid_csv_passes():
    validate_statement_content(b"Date,Amount,Description\n01/01/2026,-5.00,Coffee\n", "test.csv")


def test_binary_file_rejected():
    with pytest.raises(ValueError, match="binary"):
        validate_statement_content(b"MZ\x90\x00\x03\x00\x00\x00", "evil.csv")


def test_valid_ofx_passes():
    validate_statement_content(b"OFXHEADER:100\nDATA:OFXSGML\n", "bank.ofx")


def test_ofx_extension_wrong_content_rejected():
    with pytest.raises(ValueError):
        validate_statement_content(b"Date,Amount\n01/01/2026,-5.00\n", "bank.ofx")


def test_valid_qif_passes():
    validate_statement_content(b"!Type:Bank\nD01/01/2026\nT-5.00\n^\n", "bank.qif")


def test_qif_extension_wrong_content_rejected():
    with pytest.raises(ValueError):
        validate_statement_content(b"Date,Amount\n01/01/2026,-5.00\n", "bank.qif")


def test_utf8_bom_stripped_before_check():
    # OFX with BOM should still pass
    content = b"\xef\xbb\xbfOFXHEADER:100\nDATA:OFXSGML\n"
    validate_statement_content(content, "bank.ofx")
