"""
WebSocket routing for notifications app.
"""

from django.urls import path
from . import consumers

websocket_urlpatterns = [
    path('ws/notifications/', consumers.NotificationConsumer.as_asgi()),
    path('ws/notifications/<str:user_id>/', consumers.UserNotificationConsumer.as_asgi()),
    path('ws/property-updates/<uuid:property_id>/', consumers.PropertyUpdateConsumer.as_asgi()),
    path('ws/chat/<uuid:room_id>/', consumers.ChatConsumer.as_asgi()),
] 