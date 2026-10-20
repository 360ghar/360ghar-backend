"""Notifications package — re-exports all public names for backward compatibility.

The original ``app.services.notifications`` module has been decomposed into:

- :mod:`crud`   — CRUD operations (create, list, mark opened)
- :mod:`fcm`    — FCM access token, message building, and HTTP send
- :mod:`push`   — Supabase push notification dispatch & device token management
- :mod:`helpers` — Shared helpers (thread pool, Supabase client, type config, meta augmentation)

All public names are re-exported here so that existing ``from app.services.notifications import X``
statements continue to work without changes.
"""

from app.services.notifications.crud import (
    _record_notification,
    list_deliveries_for_user,
    list_notifications_for_user,
    mark_delivery_opened,
    record_in_app_notification,
)
from app.services.notifications.fcm import (
    APP_CHANNEL_IDS,
    FCM_SCOPE,
    _access_token,
    _fcm_credentials,
    _fcm_token_expiry,
    build_message,
    send_message,
)
from app.services.notifications.helpers import (
    _NOTIFICATION_EXECUTOR,
    _augment_data_with_meta,
    _get_type_config,
    _run_sync,
    _supa,
)
from app.services.notifications.push import (
    fcm_error_to_api_error,
    register_device_token,
    send_to_token,
    send_to_user,
    unregister_device_token,
)

__all__ = [
    # crud
    "_record_notification",
    "list_deliveries_for_user",
    "list_notifications_for_user",
    "mark_delivery_opened",
    "record_in_app_notification",
    # fcm
    "APP_CHANNEL_IDS",
    "FCM_SCOPE",
    "_access_token",
    "_fcm_credentials",
    "_fcm_token_expiry",
    "build_message",
    "send_message",
    # helpers
    "_NOTIFICATION_EXECUTOR",
    "_augment_data_with_meta",
    "_get_type_config",
    "_run_sync",
    "_supa",
    # push
    "fcm_error_to_api_error",
    "register_device_token",
    "send_to_token",
    "send_to_user",
    "unregister_device_token",
]
