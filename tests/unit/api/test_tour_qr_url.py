"""
Unit tests for tour QR URL construction.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.api.api_v1.endpoints.tours import _build_tour_qr_url


class TestBuildTourQrUrl:
    def test_prefers_short_code_path(self):
        tour = SimpleNamespace(id="tour-uuid", short_code="abc234")
        url = _build_tour_qr_url(
            tour,
            public_base_url="https://360ghar.com",
            public_app_url="https://app.360ghar.com",
        )
        assert url == "https://360ghar.com/v/abc234"

    def test_falls_back_to_viewer_path_without_short_code(self):
        tour = SimpleNamespace(id="tour-uuid", short_code=None)
        url = _build_tour_qr_url(
            tour,
            public_base_url="https://360ghar.com",
            public_app_url="https://app.360ghar.com",
        )
        assert url == "https://app.360ghar.com/view/tour-uuid"

    def test_viewer_fallback_uses_base_url_when_app_url_missing(self):
        tour = SimpleNamespace(id="tour-uuid", short_code=None)
        url = _build_tour_qr_url(
            tour,
            public_base_url="https://360ghar.com",
            public_app_url=None,
        )
        assert url == "https://360ghar.com/view/tour-uuid"
