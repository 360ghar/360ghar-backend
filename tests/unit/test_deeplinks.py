"""Unit + route tests for the backend-driven deep linking module.

Scope (all STATELESS — no database, no Postgres fixtures):
* ``app/services/deeplinks/registry.py``  — registry + path resolution
* ``app/services/deeplinks/service.py``   — assetlinks / AASA / generate / fallback
* ``app/api/deeplinks.py``                 — well-known, generate API, fallback pages

These tests deliberately do NOT use the shared ``client`` / ``db`` fixtures from
``tests/conftest.py`` (those require a live Postgres). API tests build their own
app via ``create_app(testing=True)`` and drive it with a local ``TestClient``
fixture, so the session-scoped DB engine fixture is never triggered.

The deep-link settings these tests assert against (notably
``DEEPLINK_APPLE_TEAM_ID == ABCDE12345``) are seeded by the autouse
``_seed_deeplink_settings`` fixture below, so the suite is self-contained and
does NOT depend on any ambient env var being exported before pytest runs.
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


@pytest.fixture(autouse=True)
def _seed_deeplink_settings(monkeypatch):
    """Seed the deep-link settings this module asserts against, so the suite no
    longer depends on the caller exporting ``DEEPLINK_APPLE_TEAM_ID`` before
    pytest. Individual tests can still override via their own ``monkeypatch``
    (those setattrs run after this fixture and win)."""
    monkeypatch.setattr(settings, "DEEPLINK_APPLE_TEAM_ID", EXPECTED_TEAM_ID)
    monkeypatch.setattr(settings, "DEEPLINK_FAIL_ON_PLACEHOLDER", False)


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


def test_get_app_for_path_rejects_empty_identifier():
    """A path that stops at the entity (no identifier) is not a valid deep
    link. ``/property/`` and ``/estate/property/`` both return None so the
    fallback page never renders with an empty identifier.
    """
    assert get_app_for_path("/property/") is None
    assert get_app_for_path("/p/") is None
    assert get_app_for_path("/estate/property/") is None
    assert get_app_for_path("/estate/listing/") is None
    # Identifiers with only whitespace are also rejected (the registry
    # strips before checking emptiness, matching the service layer).
    assert get_app_for_path("/property/  ") is None
    assert get_app_for_path("/estate/listing/  ") is None


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
    assert ghar.scheme_url("property", "42") == "ghar360://property/42"


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


def test_build_assetlinks_legacy_flatmates_isolated_fingerprints(monkeypatch):
    """The legacy flatmates package must NOT inherit the canonical key.

    Force the legacy fingerprint setting empty (independent of the ambient env)
    so the assertions always run: the legacy entry must carry an empty
    fingerprint list and never reuse the canonical package's fingerprints.
    """
    monkeypatch.setattr(settings, "DEEPLINK_FLATMATES_LEGACY_ANDROID_SHA256", "")
    statements = build_assetlinks()
    legacy = _statement_for(statements, "com.the360ghar.flatmates")
    canonical = _statement_for(statements, "com.the360ghar.flatmates360")
    assert legacy is not None and canonical is not None
    assert legacy["target"]["sha256_cert_fingerprints"] == []
    # The canonical package keeps its own (seeded) fingerprints.
    assert (
        legacy["target"]["sha256_cert_fingerprints"]
        != canonical["target"]["sha256_cert_fingerprints"]
    )


def test_build_assetlinks_legacy_flatmates_uses_own_fingerprint_when_set(monkeypatch):
    """When the legacy fingerprint setting is populated it is used verbatim."""
    legacy_fp = "AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99"
    monkeypatch.setattr(
        settings, "DEEPLINK_FLATMATES_LEGACY_ANDROID_SHA256", legacy_fp
    )
    statements = build_assetlinks()
    legacy = _statement_for(statements, "com.the360ghar.flatmates")
    assert legacy is not None
    assert legacy["target"]["sha256_cert_fingerprints"] == [legacy_fp]


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
    # ghar flagships /p and /property at the domain root. `/tour/*` is
    # intentionally NOT advertised — the ghar app's tour view takes a tour
    # URL (not an id) and has no deep-link entry point for `/tour/{id}`.
    assert set(_paths_for_bundle(aasa, "com.the360ghar.ghar360")) == {"/p/*", "/property/*"}
    # Namespaced apps claim one glob per registered entity, NOT a broad
    # ``/{prefix}/*`` wildcard. A broad wildcard would cause iOS to open the
    # app for paths the backend does not actually serve (e.g. /estate/foo),
    # where the fallback route would 404.
    assert set(_paths_for_bundle(aasa, "com.the360ghar.estateApp")) == {
        "/estate/apply/*",
        "/estate/property/*",
        "/estate/task/*",
        "/estate/tenant/*",
        "/estate/lease/*",
    }
    assert set(_paths_for_bundle(aasa, "com.the360ghar.flatmates360")) == {
        "/flatmates/listing/*",
        "/flatmates/chat/*",
    }
    assert set(_paths_for_bundle(aasa, "com.the360ghar.stays_app")) == {
        "/stays/listing/*",
        "/stays/chat/*",
    }


def test_aasa_webcredentials_includes_all_apps():
    aasa = build_apple_app_site_association()
    apps = aasa["webcredentials"]["apps"]
    # Every app's iOS bundle id is registered in the webcredentials block so
    # iOS Password AutoFill / Sign in with Apple can pair the native app with
    # the web domain the entitlements file declares.
    assert set(apps) == {
        f"{EXPECTED_TEAM_ID}.com.the360ghar.ghar360",
        f"{EXPECTED_TEAM_ID}.com.the360ghar.estateApp",
        f"{EXPECTED_TEAM_ID}.com.the360ghar.flatmates360",
        f"{EXPECTED_TEAM_ID}.com.the360ghar.stays_app",
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


def test_generate_link_identifier_too_long():
    # The service layer enforces the same cap as the request schema so the GET
    # path and POST body reject oversized identifiers consistently.
    with pytest.raises(ValueError):
        generate_link("estate", "property", "x" * 257)


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

    Two layers of defence:

    1. The identifier is URL-encoded by ``AppLinkConfig.https_path`` /
       ``scheme_url`` so the literal ``</script>`` substring never appears
       in any path or scheme URL emitted by the fallback page.
    2. ``service.py _js`` additionally neutralises ``</`` inside JS-context
       strings as a belt-and-braces guard.

    This test verifies layer 1: the percent-encoded form is what appears
    in the rendered HTML, not the raw payload.
    """
    stays = get_app("stays")
    payload = "abc</script><script>alert(1)</script>"
    html_out = render_fallback_page(stays, "listing", payload)
    # The raw closing-script breakout sequence must not appear unescaped.
    assert "</script><script>alert(1)</script>" not in html_out
    # The percent-encoded form is what the path / scheme URL contains.
    assert "abc%3C%2Fscript%3E%3Cscript%3Ealert%281%29%3C%2Fscript%3E" in html_out


def test_https_path_url_encodes_identifier():
    """Reserved characters in identifiers must be percent-encoded so the
    generated URL is not re-parsed as a query string or fragment by the OS
    or intermediate caches. Regression test for the
    raw-identifier-in-https_path defect.
    """
    ghar = get_app("ghar")
    # ?, #, &, +, space — all must be percent-encoded.
    assert ghar.https_path("p", "a?b&c d#e+f") == "/p/a%3Fb%26c%20d%23e%2Bf"
    # Custom-scheme URL: entity AND identifier encoded (host parsing
    # requires the entity not to be percent-encoded, but here we keep the
    # entity safe by encoding it too — the Dart consumer only cares about
    # path segments after the host).
    assert ghar.scheme_url("p", "a?b") == "ghar360://p/a%3Fb"


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


def test_api_generate_get_path_multisegment_identifier(test_client):
    """Regression test for the {identifier:path} route fix.

    The GET convenience endpoint must accept identifiers containing
    slashes (e.g. /2024/spring/unit-5) without 404'ing, matching the
    service's MAX_IDENTIFIER_LENGTH design and the POST endpoint.
    """
    resp = test_client.get("/api/v1/deeplinks/estate/apply/2024/spring/unit-5")
    assert resp.status_code == 200
    data = resp.json()
    assert data["app"] == "estate"
    assert data["entity"] == "apply"
    assert data["identifier"] == "2024/spring/unit-5"
    # Slashes inside the identifier are percent-encoded in the emitted URL
    # (the identifier field is the raw decoded value the caller passed in).
    assert data["url"] == (
        f"https://{settings.DEEPLINK_DOMAIN}/estate/apply/2024%2Fspring%2Funit-5"
    )


def test_api_generate_get_path_unknown_entity_404(test_client):
    resp = test_client.get("/api/v1/deeplinks/estate/bogus/1")
    assert resp.status_code == 400  # service raises ValueError -> 400


def test_fallback_page_rejects_empty_identifier(test_client):
    """/property/ and /p/ must NOT resolve to a fallback page (empty
    identifier). The redirect handler now 404s these.
    """
    assert test_client.get("/property/").status_code == 404
    assert test_client.get("/p/").status_code == 404
    assert test_client.get("/estate/property/").status_code == 404
    assert test_client.get("/flatmates/listing/").status_code == 404


def test_fallback_page_estate(test_client):
    resp = test_client.get("/estate/property/42")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "360 Estate" in resp.text


def test_fallback_page_unknown_entity_404(test_client):
    resp = test_client.get("/estate/bogus/1")
    assert resp.status_code == 404


# ===========================================================================
# G. Startup-time config validation
# ===========================================================================

def test_validate_deeplink_config_passes_with_valid_team_id(monkeypatch):
    """A real Apple Team ID passes validation."""
    from app.services.deeplinks.validation import validate_deeplink_config

    monkeypatch.setattr(settings, "DEEPLINK_APPLE_TEAM_ID", "ABCDE12345")
    monkeypatch.setattr(settings, "DEEPLINK_FAIL_ON_PLACEHOLDER", True)
    # Must not raise.
    validate_deeplink_config()


def test_validate_deeplink_config_warns_on_placeholder(monkeypatch, caplog):
    """The placeholder 'TEAMID' is logged as a warning when the fail-fast
    flag is off (default — local dev / CI must still boot)."""
    from app.services.deeplinks.validation import validate_deeplink_config

    monkeypatch.setattr(settings, "DEEPLINK_APPLE_TEAM_ID", "TEAMID")
    monkeypatch.setattr(settings, "DEEPLINK_FAIL_ON_PLACEHOLDER", False)
    with caplog.at_level("WARNING", logger="app.services.deeplinks.validation"):
        validate_deeplink_config()
    assert any("DEEPLINK_APPLE_TEAM_ID" in rec.message for rec in caplog.records)


def test_validate_deeplink_config_raises_in_production(monkeypatch):
    """When DEEPLINK_FAIL_ON_PLACEHOLDER is True, a placeholder Team ID
    must abort startup with a RuntimeError so a misconfigured production
    deploy fails fast rather than shipping an unverifiable AASA.
    """
    from app.services.deeplinks.validation import validate_deeplink_config

    monkeypatch.setattr(settings, "DEEPLINK_APPLE_TEAM_ID", "TEAMID")
    monkeypatch.setattr(settings, "DEEPLINK_FAIL_ON_PLACEHOLDER", True)
    try:
        validate_deeplink_config()
    except RuntimeError as exc:
        assert "DEEPLINK_APPLE_TEAM_ID" in str(exc)
    else:
        raise AssertionError("expected RuntimeError when team id is the placeholder")


def test_validate_deeplink_config_raises_on_malformed_team_id(monkeypatch):
    """Wrong length, lowercase, or non-alphanumeric Team IDs also fail
    the strict validation."""
    from app.services.deeplinks.validation import validate_deeplink_config

    monkeypatch.setattr(settings, "DEEPLINK_FAIL_ON_PLACEHOLDER", True)
    for bad in ("SHORT", "WAY_TOO_LONG_FOR_TEAM_ID", "abcde12345", "12345678 9"):
        monkeypatch.setattr(settings, "DEEPLINK_APPLE_TEAM_ID", bad)
        try:
            validate_deeplink_config()
        except RuntimeError:
            continue
        raise AssertionError(f"expected RuntimeError for team id {bad!r}")
