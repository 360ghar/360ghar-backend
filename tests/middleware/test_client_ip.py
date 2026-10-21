"""get_client_ip: X-Forwarded-For entries to the left of the trusted hop are client-supplied."""

from __future__ import annotations

import pytest
from fastapi import Request

from app.config import settings
from app.middleware.rate_limit import get_client_ip

PEER = ("10.0.0.1", 4000)


def _request(xff: str | None = None, real_ip: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if xff is not None:
        headers.append((b"x-forwarded-for", xff.encode()))
    if real_ip is not None:
        headers.append((b"x-real-ip", real_ip.encode()))
    return Request({"type": "http", "headers": headers, "client": PEER})


@pytest.fixture
def hops(monkeypatch):
    def set_hops(n: int) -> None:
        monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", n)

    set_hops(1)
    return set_hops


def test_single_entry_is_the_client(hops):
    assert get_client_ip(_request("5.6.7.8")) == "5.6.7.8"


def test_spoofed_first_entry_is_ignored_when_proxy_appends_client(hops):
    # The client sent "1.1.1.1"; the trusted proxy appended the address it saw, 9.9.9.9.
    assert get_client_ip(_request("1.1.1.1, 9.9.9.9")) == "9.9.9.9"


def test_rotating_spoofed_values_give_the_same_client(hops):
    first = get_client_ip(_request("1.1.1.1, 9.9.9.9"))
    second = get_client_ip(_request("2.2.2.2, 9.9.9.9"))
    assert first == second == "9.9.9.9"


def test_two_trusted_hops_use_the_entry_two_from_the_right(hops):
    hops(2)
    assert get_client_ip(_request("spoof, 9.9.9.9, 10.0.0.2")) == "9.9.9.9"


def test_zero_hops_ignores_the_header_and_uses_the_peer(hops):
    hops(0)
    assert get_client_ip(_request("1.1.1.1, 9.9.9.9")) == "10.0.0.1"


def test_empty_forwarded_header_falls_back_to_peer_without_error(hops):
    assert get_client_ip(_request(" , ")) == "10.0.0.1"


def test_real_ip_header_is_not_trusted_and_peer_is_used(hops):
    # A client can rotate X-Real-IP on every request, so the peer address is the key.
    assert get_client_ip(_request(real_ip="7.7.7.7")) == "10.0.0.1"
    assert get_client_ip(_request(real_ip="8.8.8.8")) == "10.0.0.1"
    assert get_client_ip(_request()) == "10.0.0.1"
