"""Deep link app registry — the single source of truth for every 360Ghar app.

Each :class:`AppLinkConfig` captures the *contract* a mobile app declares in its
native configuration (AndroidManifest intent-filters, iOS associated-domains and
``CFBundleURLSchemes``) together with the metadata needed to:

* emit that app's entry in ``assetlinks.json`` / ``apple-app-site-association``
* build the custom-scheme URL used by the smart fallback page
* generate the canonical HTTPS share link for each shareable entity

To onboard a new app: append an :class:`AppLinkConfig` to :data:`APP_REGISTRY`.
To add a shareable entity to an app: append an :class:`EntityPattern` to that
app's ``entities`` list. No other layer needs editing.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Platform(str, Enum):
    ANDROID = "android"
    IOS = "ios"
    OTHER = "other"


@dataclass(frozen=True)
class EntityPattern:
    """A shareable entity within an app.

    ``entity`` is the URL segment (e.g. ``property``). The canonical HTTPS path
    is ``/{path_prefix}/{entity}/{id}`` and the custom-scheme fallback is
    ``{scheme}://{entity}/{id}`` (matching how each app's DeepLinkService parses
    incoming links). ``public`` marks links that resolve without authentication.
    """

    entity: str
    description: str = ""
    public: bool = False


@dataclass(frozen=True)
class AppLinkConfig:
    """Deep link contract for one app."""

    key: str  # stable identifier: ghar / estate / flatmates / stays
    name: str  # human-readable name shown on fallback pages
    # Android
    android_packages: tuple[str, ...]  # primary first; extras = legacy aliases
    # iOS
    ios_bundle_id: str
    use_webcredentials: bool = False  # include in AASA webcredentials block
    # Custom URL scheme used as the fallback launch mechanism on the web page.
    custom_scheme: str = ""
    # HTTPS path prefix that namespaces this app's links (no leading/trailing /).
    # Empty string => links live at the domain root (used by the flagship app).
    path_prefix: str = ""
    # Shareable entities.
    entities: tuple[EntityPattern, ...] = ()
    # Store + web fallbacks shown when the app is not installed.
    play_store_url: str = ""
    app_store_url: str = ""
    web_fallback_url: str = ""
    # Cosmetic fallback-page branding.
    emoji: str = "🏠"
    gradient_from: str = "#667eea"
    gradient_to: str = "#764ba2"
    # Settings attribute holding comma-separated SHA-256 fingerprints for this app.
    fingerprint_setting: str = ""

    @property
    def primary_android_package(self) -> str:
        return self.android_packages[0]

    def https_path(self, entity: str, identifier: str) -> str:
        """Canonical HTTPS path for an entity, e.g. ``/estate/property/42``."""
        parts = [p for p in (self.path_prefix, entity, identifier) if p]
        return "/" + "/".join(parts)

    def scheme_url(self, entity: str, identifier: str) -> str:
        """Custom-scheme fallback URL, e.g. ``estate360://property/42``.

        Matches how each app's DeepLinkService parses the host as the first
        path segment (``estate360://property/42`` -> segments ``[property, 42]``).
        """
        return f"{self.custom_scheme}://{entity}/{identifier}"

    def aasa_paths(self) -> list[str]:
        """Path globs claimed by this app for the AASA ``paths`` array."""
        if self.path_prefix:
            return [f"/{self.path_prefix}/*"]
        # Flagship app claims one glob per top-level entity at the root.
        return [f"/{e.entity}/*" for e in self.entities]


# ---------------------------------------------------------------------------
# The registry. Order is irrelevant; ``key`` and ``path_prefix`` must be unique.
# ---------------------------------------------------------------------------

APP_REGISTRY: tuple[AppLinkConfig, ...] = (
    AppLinkConfig(
        key="ghar",
        name="360 Ghar",
        android_packages=("com.the360ghar.ghar360",),
        ios_bundle_id="com.the360ghar.ghar360",
        use_webcredentials=True,
        custom_scheme="ghar360",
        path_prefix="",  # flagship app: links at domain root (/p, /property, /tour)
        entities=(
            EntityPattern("p", "Property short link", public=True),
            EntityPattern("property", "Property detail", public=True),
            EntityPattern("tour", "Virtual tour", public=True),
        ),
        play_store_url="https://play.google.com/store/apps/details?id=com.the360ghar.ghar360",
        app_store_url="",
        web_fallback_url="https://the360ghar.com",
        emoji="🏠",
        gradient_from="#667eea",
        gradient_to="#764ba2",
        fingerprint_setting="DEEPLINK_GHAR_ANDROID_SHA256",
    ),
    AppLinkConfig(
        key="estate",
        name="360 Estate",
        android_packages=("com.the360ghar.estate_app",),
        ios_bundle_id="com.the360ghar.estateApp",
        custom_scheme="estate360",
        path_prefix="estate",
        entities=(
            EntityPattern("apply", "Rental application", public=True),
            EntityPattern("property", "Property detail"),
            EntityPattern("task", "Maintenance task"),
            EntityPattern("tenant", "Tenant detail"),
            EntityPattern("lease", "Lease detail"),
        ),
        play_store_url="https://play.google.com/store/apps/details?id=com.the360ghar.estate_app",
        app_store_url="",
        web_fallback_url="https://the360ghar.com",
        emoji="🏢",
        gradient_from="#059669",
        gradient_to="#0d9488",
        fingerprint_setting="DEEPLINK_ESTATE_ANDROID_SHA256",
    ),
    AppLinkConfig(
        key="flatmates",
        name="360 FlatMates",
        # android_packages[0] = current canonical package.
        # android_packages[1] = LEGACY COMPATIBILITY package. `com.the360ghar.flatmates`
        #   was previously published in Play Console before the migration to
        #   `com.the360ghar.flatmates360`. It is INTENTIONALLY RETAINED here so that
        #   App Links shared to installs of the old app continue to verify.
        #   DO NOT remove without product-owner sign-off.
        #   CAVEAT: it currently inherits the flatmates360 SHA-256 (shared
        #   `fingerprint_setting`). If the legacy app was signed with a DIFFERENT
        #   key, its App Links will only verify once its own app-signing SHA-256 is
        #   added (would require per-package fingerprints — see docs follow-up).
        android_packages=("com.the360ghar.flatmates360", "com.the360ghar.flatmates"),
        ios_bundle_id="com.the360ghar.flatmates360",
        use_webcredentials=True,
        custom_scheme="com.the360ghar.flatmates360",
        path_prefix="flatmates",
        entities=(
            EntityPattern("listing", "Flatmate listing", public=True),
            EntityPattern("chat", "Conversation"),
        ),
        play_store_url="https://play.google.com/store/apps/details?id=com.the360ghar.flatmates360",
        app_store_url="",
        web_fallback_url="https://the360ghar.com/flatmates",
        emoji="🏠",
        gradient_from="#f59e0b",
        gradient_to="#ef4444",
        fingerprint_setting="DEEPLINK_FLATMATES_ANDROID_SHA256",
    ),
    AppLinkConfig(
        key="stays",
        name="360 Stays",
        # Android package CONFIRMED from Play Console (canonical, matches the
        # house convention com.the360ghar.*). The source repo was realigned to
        # this id (was drifting on com.a360ghar.stays / com.example.stays_app).
        android_packages=("com.the360ghar.stays_app",),
        # AUDIT: iOS bundle id is UNVERIFIED — source still shows the Flutter
        # default ``com.example.staysApp``. Do NOT change until the real App
        # Store bundle id is confirmed. AASA targets the source value meanwhile.
        ios_bundle_id="com.example.staysApp",
        custom_scheme="stays360",
        path_prefix="stays",
        entities=(
            EntityPattern("listing", "Stay listing", public=True),
            EntityPattern("chat", "Conversation"),
        ),
        play_store_url="https://play.google.com/store/apps/details?id=com.the360ghar.stays_app",
        app_store_url="",
        web_fallback_url="https://the360ghar.com/stays",
        emoji="🏨",
        gradient_from="#2563eb",
        gradient_to="#7c3aed",
        fingerprint_setting="DEEPLINK_STAYS_ANDROID_SHA256",
    ),
)

# Fast lookups -------------------------------------------------------------
_BY_KEY: dict[str, AppLinkConfig] = {a.key: a for a in APP_REGISTRY}
# path_prefix -> app (only apps that namespace their links). Sorted longest-first
# so a more specific prefix wins when matching incoming request paths.
_PREFIXED_APPS: tuple[AppLinkConfig, ...] = tuple(
    sorted(
        (a for a in APP_REGISTRY if a.path_prefix),
        key=lambda a: len(a.path_prefix),
        reverse=True,
    )
)
# Root-level (flagship) apps keyed by their top-level entity segment.
_ROOT_ENTITY_INDEX: dict[str, AppLinkConfig] = {}
for _app in APP_REGISTRY:
    if not _app.path_prefix:
        for _entity in _app.entities:
            _ROOT_ENTITY_INDEX[_entity.entity] = _app


def get_app(key: str) -> AppLinkConfig | None:
    """Return the app config for ``key`` (ghar/estate/flatmates/stays)."""
    return _BY_KEY.get(key)


def get_app_for_path(path: str) -> tuple[AppLinkConfig, str, str] | None:
    """Resolve an incoming request path to ``(app, entity, identifier)``.

    Handles both namespaced apps (``/estate/property/42``) and the flagship
    root app (``/p/42``, ``/tour/abc``). Returns ``None`` when no app claims
    the path. ``identifier`` may be empty if the path stops at the entity.
    """
    segments = [s for s in path.split("/") if s]
    if not segments:
        return None

    # Namespaced apps: first segment is the path prefix.
    for app in _PREFIXED_APPS:
        if segments[0] == app.path_prefix:
            if len(segments) < 2:
                return None
            entity = segments[1]
            identifier = segments[2] if len(segments) >= 3 else ""
            if any(e.entity == entity for e in app.entities):
                return (app, entity, identifier)
            return None

    # Root flagship app: first segment is the entity itself.
    head = segments[0]
    app = _ROOT_ENTITY_INDEX.get(head)
    if app is not None:
        identifier = segments[1] if len(segments) >= 2 else ""
        return (app, head, identifier)

    return None
