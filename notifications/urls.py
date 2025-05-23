"""
URL patterns for notifications app.
"""

from django.urls import path
from . import views

app_name = 'notifications'

urlpatterns = [
    # Notification Management
    path('', views.NotificationListView.as_view(), name='notification-list'),
    path('<uuid:pk>/', views.NotificationDetailView.as_view(), name='notification-detail'),
    path('<uuid:pk>/read/', views.MarkNotificationReadView.as_view(), name='mark-read'),
    path('mark-all-read/', views.MarkAllReadView.as_view(), name='mark-all-read'),
    path('<uuid:pk>/delete/', views.DeleteNotificationView.as_view(), name='delete-notification'),
    
    # Notification Preferences
    path('preferences/', views.NotificationPreferencesView.as_view(), name='notification-preferences'),
    path('preferences/update/', views.UpdateNotificationPreferencesView.as_view(), name='update-preferences'),
    
    # Push Notifications
    path('push/subscribe/', views.PushSubscriptionView.as_view(), name='push-subscribe'),
    path('push/unsubscribe/', views.PushUnsubscribeView.as_view(), name='push-unsubscribe'),
    path('push/test/', views.TestPushNotificationView.as_view(), name='test-push'),
    
    # Email Notifications
    path('email/unsubscribe/<str:token>/', views.EmailUnsubscribeView.as_view(), name='email-unsubscribe'),
    path('email/preferences/', views.EmailPreferencesView.as_view(), name='email-preferences'),
    
    # Property Alerts
    path('alerts/', views.PropertyAlertListView.as_view(), name='property-alert-list'),
    path('alerts/create/', views.CreatePropertyAlertView.as_view(), name='create-property-alert'),
    path('alerts/<uuid:pk>/', views.PropertyAlertDetailView.as_view(), name='property-alert-detail'),
    path('alerts/<uuid:pk>/update/', views.UpdatePropertyAlertView.as_view(), name='update-property-alert'),
    path('alerts/<uuid:pk>/delete/', views.DeletePropertyAlertView.as_view(), name='delete-property-alert'),
    
    # Saved Search Alerts
    path('search-alerts/', views.SavedSearchAlertListView.as_view(), name='search-alert-list'),
    path('search-alerts/<uuid:search_id>/toggle/', views.ToggleSearchAlertView.as_view(), name='toggle-search-alert'),
    
    # Admin Notifications
    path('admin/send/', views.SendAdminNotificationView.as_view(), name='send-admin-notification'),
    path('admin/broadcast/', views.BroadcastNotificationView.as_view(), name='broadcast-notification'),
    
    # Statistics
    path('stats/', views.NotificationStatsView.as_view(), name='notification-stats'),
    path('delivery-status/', views.DeliveryStatusView.as_view(), name='delivery-status'),
] 