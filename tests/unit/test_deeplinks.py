"""Unit + route tests for the backend-driven deep linking module.

Scope (all STATELESS — no database, no Postgres fixtures):
* ``app/services/deeplinks/registry.py``  — registry + path resolution
* ``app/services/deeplinks/service.py``   — assetlinks / AASA / generate / fallback
* ``app/api/deeplinks.py``                 — well-known, generate API, fallback pages

These tests deliberately do NOT use the shared ``client`` / ``db`` fixtures from
``tests/conftest.py`` (those require a live Postgres). API tests build their own
app via ``create_app(testing=True)`` and drive it with a local ``TestClient``
fixture, so the session-scoped DB engine fixture is never triggered.

Env vars required to import ``app.config.settings`` must be set BEFORE running
pytest (see the module docstring of the task / the command used in the report).
``DEEPLINK_APPLE_TEAM_ID`` is expected to be ``ABCDE12345`` for the AASA tests.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.factory import create_app
from app.services.deeplinks import (
    APP_REGISTRY,
    build_apple_app_site_association,
    build_assetlinks,
    generate_link,
    get_app,
    get_app_for_path,
    render_fallback_page,
)

EXPECTED_TEAM_ID = "ABCDE12345"


# ---------------------------------------------------------------------------
# Local fixtures (no DB). Built fresh; TestClient is NOT entered as a context
# manager so the app lifespan (and any engine wiring) never runs.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app():
    return create_app(testing=True)


@pytest.fixture(scope="module")
def test_client(app):
    return TestClient(app)


# ===========================================================================
# A. registry — get_app / get_app_for_path / https_path / scheme_url
# ===========================================================================

@pytest.mark.parametrize(
    "key, name, prefix, scheme",
    [
        ("ghar", "360 Ghar", "", "ghar360"),
        ("estate", "360 Estate", "estate", "estate360"),
        ("flatmates", "360 FlatMates", "flatmates", "com.the360ghar.flatmates360"),
        ("stays", "360 Stays", "stays", "stays360"),
    ],
)
def test_get_app_known_keys(key, name, prefix, scheme):
    app = get_app(key)
    assert app is not None
    assert app.key == key
    assert app.name == name
    assert app.path_prefix == prefix
    assert app.custom_scheme == scheme


def test_get_app_unknown_returns_none():
    assert get_app("does-not-exist") is None
    assert get_app("") is None


@pytest.mark.parametrize(
    "path, exp_key, exp_entity, exp_id",
    [
        ("/p/5", "ghar", "p", "5"),
        ("/property/9", "ghar", "property", "9"),
        ("/tour/abc", "ghar", "tour", "abc"),
        ("/estate/property/42", "estate", "property", "42"),
        ("/estate/apply/some-slug", "estate", "apply", "some-slug"),
        ("/flatmates/listing/7", "flatmates", "listing", "7"),
        ("/flatmates/chat/3", "flatmates", "chat", "3"),
        ("/stays/listing/x", "stays", "listing", "x"),
    ],
)
def test_get_app_for_path_resolves(path, exp_key, exp_entity, exp_id):
    resolved = get_app_for_path(path)
    assert resolved is not None
    app, entity, identifier = resolved
    assert app.key == exp_key
    assert entity == exp_entity
    assert identifier == exp_id
    # Cross-check the derived HTTPS path and custom-scheme URL.
    assert app.https_path(entity, identifier) == path
    assert app.scheme_url(entity, identifier) == f"{app.custom_scheme}://{entity}/{identifier}"


def test_get_app_for_path_unknown_path():
    assert get_app_for_path("/nope/1") is None


def test_get_app_for_path_prefix_without_entity():
    # A known prefix with no entity segment must resolve to None.
    assert get_app_for_path("/estate") is None


@pytest.mark.parametrize(
    "path, exp_key, exp_entity, exp_id",
    [
        # Namespaced app with a multi-segment identifier (slug containing "/").
        ("/estate/apply/2024/spring/unit-5", "estate", "apply", "2024/spring/unit-5"),
        # Flagship root app with a multi-segment identifier.
        ("/property/city/mumbai/42", "ghar", "property", "city/mumbai/42"),
    ],
)
def test_get_app_for_path_preserves_multisegment_identifier(path, exp_key, exp_entity, exp_id):
    resolved = get_app_for_path(path)
    assert resolved is not None
    app, entity, identifier = resolved
    assert app.key == exp_key
    assert entity == exp_entity
    assert identifier == exp_id


def test_https_path_and_scheme_url_examples():
    estate = get_app("estate")
    assert estate.https_path("property", "42") == "/estate/property/42"
    assert estate.scheme_url("property", "42") == "estate360://property/42"

    ghar = get_app("ghar")
    # Flagship app has empty prefix => path lives at root.
    assert ghar.https_path("p", "5") == "/p/5"
    assert ghar.scheme_url("tour", "abc") == "ghar360://tour/abc"


# ===========================================================================
# B. build_assetlinks()
# ===========================================================================

def test_build_assetlinks_one_statement_per_package():
    statements = build_assetlinks()
    expected_packages = [pkg for app in APP_REGISTRY for pkg in app.android_packages]
    assert len(statements) == len(expected_packages)

    for stmt in statements:
        assert stmt["relation"] == ["delegate_permission/common.handle_all_urls"]
        assert stmt["target"]["namespace"] == "android_app"
        assert "package_name" in stmt["target"]
        assert "sha256_cert_fingerprints" in stmt["target"]


def _statement_for(statements, package):
    for s in statements:
        if s["target"]["package_name"] == package:
            return s
    return None


def test_build_assetlinks_ghar_has_seeded_fingerprints():
    statements = build_assetlinks()
    ghar = _statement_for(statements, "com.the360ghar.ghar360")
    assert ghar is not None, "ghar package missing from assetlinks"
    # Defaults are seeded, so fingerprints must be non-empty.
    fps = ghar["target"]["sha256_cert_fingerprints"]
    assert isinstance(fps, list)
    assert len(fps) >= 1
    assert all(isinstance(fp, str) and fp for fp in fps)


def test_build_assetlinks_includes_legacy_flatmates_package():
    statements = build_assetlinks()
    legacy = _statement_for(statements, "com.the360ghar.flatmates")
    assert legacy is not None, "legacy com.the360ghar.flatmates package must be present"
    assert legacy["target"]["namespace"] == "android_app"


def test_build_assetlinks_legacy_flatmates_isolated_fingerprints():
    """The legacy flatmates package must NOT inherit the canonical key.

    With ``DEEPLINK_FLATMATES_LEGACY_ANDROID_SHA256`` unset (default), the legacy
    entry carries an empty fingerprint list so it can never verify against the
    wrong key — independent of the current canonical package's fingerprints.
    """
    statements = build_assetlinks()
    legacy = _statement_for(statements, "com.the360ghar.flatmates")
    canonical = _statement_for(statements, "com.the360ghar.flatmates360")
    assert legacy is not None and canonical is not None
    if not settings.DEEPLINK_FLATMATES_LEGACY_ANDROID_SHA256.strip():
        assert legacy["target"]["sha256_cert_fingerprints"] == []
        # The canonical package keeps its own (seeded) fingerprints.
        assert (
            legacy["target"]["sha256_cert_fingerprints"]
            != canonical["target"]["sha256_cert_fingerprints"]
        )


# ===========================================================================
# C. build_apple_app_site_association()
# ===========================================================================

def test_aasa_details_structure_and_team_id():
    aasa = build_apple_app_site_association()
    details = aasa["applinks"]["details"]
    assert len(details) == 4
    for d in details:
        assert d["appID"].startswith(f"{EXPECTED_TEAM_ID}.")
        assert isinstance(d["paths"], list) and d["paths"]


def _paths_for_bundle(aasa, bundle_id):
    app_id = f"{EXPECTED_TEAM_ID}.{bundle_id}"
    for d in aasa["applinks"]["details"]:
        if d["appID"] == app_id:
            return d["paths"]
    return None


def test_aasa_paths_match_expected_globs():
    aasa = build_apple_app_site_association()
    assert set(_paths_for_bundle(aasa, "com.the360ghar.ghar360")) == {"/p/*", "/property/*", "/tour/*"}
    assert _paths_for_bundle(aasa, "com.the360ghar.estateApp") == ["/estate/*"]
    assert _paths_for_bundle(aasa, "com.the360ghar.flatmates360") == ["/flatmates/*"]
    # NOTE: Stays iOS bundle id is the unconfirmed source default; update when
    # the real App Store bundle id is verified (see registry audit comment).
    assert _paths_for_bundle(aasa, "com.example.staysApp") == ["/stays/*"]


def test_aasa_webcredentials_ghar_and_flatmates_only():
    aasa = build_apple_app_site_association()
    apps = aasa["webcredentials"]["apps"]
    assert set(apps) == {
        f"{EXPECTED_TEAM_ID}.com.the360ghar.ghar360",
        f"{EXPECTED_TEAM_ID}.com.the360ghar.flatmates360",
    }


# ===========================================================================
# D. generate_link()
# ===========================================================================

def test_generate_link_valid():
    link = generate_link("estate", "property", "42")
    assert link.app == "estate"
    assert link.entity == "property"
    assert link.identifier == "42"
    assert link.url == f"https://{settings.DEEPLINK_DOMAIN}/estate/property/42"
    assert link.scheme_url == "estate360://property/42"
    # estate has an explicit web_fallback_url configured.
    assert link.web_fallback_url == "https://the360ghar.com"


def test_generate_link_ghar_root():
    link = generate_link("ghar", "p", "99")
    assert link.url == f"https://{settings.DEEPLINK_DOMAIN}/p/99"
    assert link.scheme_url == "ghar360://p/99"


def test_generate_link_invalid_app():
    with pytest.raises(ValueError):
        generate_link("nope", "property", "1")


def test_generate_link_invalid_entity():
    with pytest.raises(ValueError):
        generate_link("estate", "bogus", "1")


def test_generate_link_empty_identifier():
    with pytest.raises(ValueError):
        generate_link("estate", "property", "")
    with pytest.raises(ValueError):
        generate_link("estate", "property", "   ")


# ===========================================================================
# E. render_fallback_page()
# ===========================================================================

def test_render_fallback_page_contains_name_and_scheme():
    estate = get_app("estate")
    html_out = render_fallback_page(estate, "property", "42")
    assert "360 Estate" in html_out
    # Custom scheme URL appears in the inline launch script.
    assert "estate360://property/42" in html_out
    assert "<!doctype html>" in html_out


def test_render_fallback_page_html_escapes_name():
    """A name with HTML metacharacters must be HTML-escaped in HTML context."""
    from app.services.deeplinks.registry import AppLinkConfig, EntityPattern

    evil = AppLinkConfig(
        key="evil",
        name='<b>Pwn</b> & "co"',
        android_packages=("com.evil.app",),
        ios_bundle_id="com.evil.app",
        custom_scheme="evil",
        path_prefix="evil",
        entities=(EntityPattern("listing"),),
    )
    html_out = render_fallback_page(evil, "listing", "1")
    # Raw tag must not survive; escaped form must be present.
    assert "<b>Pwn</b>" not in html_out
    assert "&lt;b&gt;Pwn&lt;/b&gt;" in html_out
    assert "&amp;" in html_out


def test_render_fallback_page_no_script_breakout_xss():
    """A crafted identifier must not break out of the inline <script> block.

    Regression test for the previously-present reflected-XSS defect where
    json.dumps() alone did not escape '</script>'. The fix neutralises '</' in
    JS-context values (service.py ``_js``).
    """
    stays = get_app("stays")
    payload = "abc</script><script>alert(1)</script>"
    html_out = render_fallback_page(stays, "listing", payload)
    # The raw closing-script breakout sequence must not appear.
    assert "</script><script>alert(1)</script>" not in html_out
    # The escaped form (<\/script>) is what should be emitted instead.
    assert "<\\/script>" in html_out


# ===========================================================================
# F. API via TestClient (no DB)
# ===========================================================================

def test_wellknown_assetlinks(test_client):
    resp = test_client.get("/.well-known/assetlinks.json")
    assert resp.status_code == 200
    assert "application/json" in resp.headers["content-type"]
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == len([p for a in APP_REGISTRY for p in a.android_packages])


def test_wellknown_aasa(test_client):
    resp = test_client.get("/.well-known/apple-app-site-association")
    assert resp.status_code == 200
    assert "application/json" in resp.headers["content-type"]
    data = resp.json()
    assert "applinks" in data
    assert len(data["applinks"]["details"]) == 4


def test_api_list_apps(test_client):
    resp = test_client.get("/api/v1/deeplinks/apps")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 4
    keys = {a["key"] for a in data}
    assert keys == {"ghar", "estate", "flatmates", "stays"}


def test_api_generate_post(test_client):
    resp = test_client.post(
        "/api/v1/deeplinks/generate",
        json={"app": "estate", "entity": "property", "identifier": "42"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["url"] == f"https://{settings.DEEPLINK_DOMAIN}/estate/property/42"
    assert data["scheme_url"] == "estate360://property/42"


def test_api_generate_post_invalid_entity(test_client):
    resp = test_client.post(
        "/api/v1/deeplinks/generate",
        json={"app": "estate", "entity": "bogus", "identifier": "1"},
    )
    assert resp.status_code == 400


def test_api_generate_get_path(test_client):
    resp = test_client.get("/api/v1/deeplinks/ghar/p/99")
    assert resp.status_code == 200
    data = resp.json()
    assert data["url"] == f"https://{settings.DEEPLINK_DOMAIN}/p/99"


def test_fallback_page_estate(test_client):
    resp = test_client.get("/estate/property/42")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "360 Estate" in resp.text


def test_fallback_page_unknown_entity_404(test_client):
    resp = test_client.get("/estate/bogus/1")
    assert resp.status_code == 404
