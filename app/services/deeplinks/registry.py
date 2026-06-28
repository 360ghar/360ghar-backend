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
from urllib.parse import quote


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
    # Optional per-package fingerprint setting overrides. Each tuple maps an
    # Android package name to the Settings attribute holding ITS OWN
    # comma-separated SHA-256 fingerprints. Used for legacy packages signed with
    # a different key than the current canonical package. Packages not listed
    # here fall back to ``fingerprint_setting``.
    package_fingerprint_overrides: tuple[tuple[str, str], ...] = ()

    @property
    def primary_android_package(self) -> str:
        return self.android_packages[0]

    def fingerprint_setting_for(self, package: str) -> str:
        """Return the Settings attribute holding ``package``'s fingerprints.

        Honours :attr:`package_fingerprint_overrides` (e.g. a legacy package
        signed with a different key) before falling back to the app-level
        :attr:`fingerprint_setting`.
        """
        for pkg, setting in self.package_fingerprint_overrides:
            if pkg == package:
                return setting
        return self.fingerprint_setting

    def https_path(self, entity: str, identifier: str) -> str:
        """Canonical HTTPS path for an entity, e.g. ``/estate/property/42``.

        Each path segment is percent-encoded so identifiers containing
        reserved characters (e.g. ``?``, ``#``, ``+``, spaces) produce a
        URL that iOS, Android, and intermediate caches will not re-parse
        as query strings or fragments. ``quote(s, safe="")`` is the
        strict RFC 3986 unreserved-only encoder.
        """
        parts = [quote(p, safe="") for p in (self.path_prefix, entity, identifier) if p]
        return "/" + "/".join(parts)

    def scheme_url(self, entity: str, identifier: str) -> str:
        """Custom-scheme fallback URL, e.g. ``estate360://property/42``.

        Matches how each app's DeepLinkService parses the host as the first
        path segment (``estate360://property/42`` -> segments ``[property, 42]``).
        Identifier is percent-encoded for the same reason as :meth:`https_path`.
        """
        return f"{self.custom_scheme}://{quote(entity, safe='')}/{quote(identifier, safe='')}"

    def aasa_paths(self) -> list[str]:
        """Path globs claimed by this app for the AASA ``paths`` array.

        Emits one glob per registered entity, not a single ``/{prefix}/*``
        wildcard. iOS Universal Link resolution is opt-in per path glob; a
        broad wildcard would cause the OS to open the app for paths the
        registry does not actually serve (e.g. ``/estate/unknown``), where
        the backend would 404.
        """
        if self.path_prefix:
            return [f"/{self.path_prefix}/{e.entity}/*" for e in self.entities]
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
        path_prefix="",  # flagship app: links at domain root (/p, /property)
        # NOTE: no `tour` entity. The ghar app's tour UX is "tap a tour badge
        # on a property card" — `TourView` consumes a tour *URL* (not an id)
        # via Get.arguments, and there is no deep-link entry point that maps
        # a tour id to its URL. The /tour/* surface belongs to the dedicated
        # Virtual Tours module on the web; do not advertise it for ghar.
        entities=(
            EntityPattern("p", "Property short link", public=True),
            EntityPattern("property", "Property detail", public=True),
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
        use_webcredentials=True,
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
        #   The legacy package reads its OWN fingerprints from
        #   `DEEPLINK_FLATMATES_LEGACY_ANDROID_SHA256` (see package_fingerprint_overrides).
        #   Until that is set its assetlinks entry carries an EMPTY fingerprint
        #   list, so it can never verify against the wrong key — set the legacy
        #   app-signing SHA-256 to activate verification for old installs.
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
        package_fingerprint_overrides=(
            ("com.the360ghar.flatmates", "DEEPLINK_FLATMATES_LEGACY_ANDROID_SHA256"),
        ),
    ),
    AppLinkConfig(
        key="stays",
        name="360 Stays",
        # Android package CONFIRMED from Play Console (canonical, matches the
        # house convention com.the360ghar.*). The source repo was realigned to
        # this id (was drifting on com.a360ghar.stays / com.example.stays_app).
        # iOS bundle id mirrors the same canonical id (was ``com.example.staysApp``
        # when the source still used the Flutter default; corrected in tandem
        # with the Android rename so the AASA ``appID`` matches the installed
        # binary's signing identity).
        android_packages=("com.the360ghar.stays_app",),
        ios_bundle_id="com.the360ghar.stays_app",
        use_webcredentials=True,
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
    root app (``/p/42``). Returns ``None`` when no app claims the path or
    when the path stops at the entity without an identifier
    (``/property/`` is NOT a valid deep link).
    """
    segments = [s for s in path.split("/") if s]
    if not segments:
        return None

    # Namespaced apps: first segment is the path prefix.
    for app in _PREFIXED_APPS:
        if segments[0] == app.path_prefix:
            if len(segments) < 3:
                # Need at least prefix/entity/identifier. /estate/ and
                # /estate/foo (unknown entity) both return None.
                return None
            entity = segments[1]
            if not any(e.entity == entity for e in app.entities):
                return None
            # Preserve multi-segment identifiers (e.g. slugs containing "/").
            # Strip surrounding whitespace so ``/estate/property/  `` is
            # treated the same as an empty identifier (None) — matches
            # generate_link()'s behaviour.
            identifier = "/".join(segments[2:]).strip()
            if not identifier:
                return None
            return (app, entity, identifier)

    # Root flagship app: first segment is the entity itself.
    head = segments[0]
    app = _ROOT_ENTITY_INDEX.get(head)
    if app is not None:
        if len(segments) < 2:
            # /p and /property without an identifier are not valid deep links.
            return None
        # Preserve multi-segment identifiers (e.g. slugs containing "/").
        identifier = "/".join(segments[1:]).strip()
        if not identifier:
            return None
        return (app, head, identifier)

    return None
