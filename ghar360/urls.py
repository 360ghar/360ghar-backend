"""
URL configuration for ghar360 project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework.routers import DefaultRouter

# API v1 URLs
api_v1_patterns = [
    path('auth/', include('authentication.urls')),
    path('users/', include('users.urls')),
    path('properties/', include('properties.urls')),
    path('media/', include('media.urls')),
    path('search/', include('search.urls')),
    path('analytics/', include('analytics.urls')),
    path('notifications/', include('notifications.urls')),
    path('locations/', include('locations.urls')),
]

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/', include(api_v1_patterns)),
    path('o/', include('oauth2_provider.urls', namespace='oauth2_provider')),
    path('api-auth/', include('rest_framework.urls', namespace='rest_framework')),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

# Admin site configuration
admin.site.site_header = "360Ghar Administration"
admin.site.site_title = "360Ghar Admin Portal"
admin.site.index_title = "Welcome to 360Ghar Administration"
