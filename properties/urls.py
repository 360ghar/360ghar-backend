"""
URL patterns for properties app.
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

app_name = 'properties'

# Create a router and register our viewsets with it
router = DefaultRouter()
router.register(r'', views.PropertyViewSet, basename='property')

urlpatterns = [
    # Custom endpoints (should come before router to avoid conflicts)
    path('featured/', views.FeaturedPropertiesView.as_view(), name='featured-properties'),
    path('my-properties/', views.MyPropertiesView.as_view(), name='my-properties'),
    
    # Property-related nested resources (manual routing)
    path('<uuid:property_pk>/media/', views.PropertyMediaViewSet.as_view({
        'get': 'list',
        'post': 'create'
    }), name='property-media-list'),
    path('<uuid:property_pk>/media/<uuid:pk>/', views.PropertyMediaViewSet.as_view({
        'get': 'retrieve',
        'put': 'update',
        'patch': 'partial_update',
        'delete': 'destroy'
    }), name='property-media-detail'),
    
    path('<uuid:property_pk>/materials/', views.BuildingMaterialViewSet.as_view({
        'get': 'list',
        'post': 'create'
    }), name='property-materials-list'),
    path('<uuid:property_pk>/materials/<uuid:pk>/', views.BuildingMaterialViewSet.as_view({
        'get': 'retrieve',
        'put': 'update',
        'patch': 'partial_update',
        'delete': 'destroy'
    }), name='property-materials-detail'),
    
    path('<uuid:property_pk>/appliances/', views.ApplianceViewSet.as_view({
        'get': 'list',
        'post': 'create'
    }), name='property-appliances-list'),
    path('<uuid:property_pk>/appliances/<uuid:pk>/', views.ApplianceViewSet.as_view({
        'get': 'retrieve',
        'put': 'update',
        'patch': 'partial_update',
        'delete': 'destroy'
    }), name='property-appliances-detail'),
    
    path('<uuid:property_pk>/inquiries/', views.PropertyInquiryViewSet.as_view({
        'get': 'list',
        'post': 'create'
    }), name='property-inquiries-list'),
    path('<uuid:property_pk>/inquiries/<uuid:pk>/', views.PropertyInquiryViewSet.as_view({
        'get': 'retrieve',
        'put': 'update',
        'patch': 'partial_update',
        'delete': 'destroy'
    }), name='property-inquiries-detail'),
    path('<uuid:property_pk>/inquiries/<uuid:pk>/respond/', views.PropertyInquiryViewSet.as_view({
        'post': 'respond'
    }), name='property-inquiry-respond'),
    
    # Analytics endpoint
    path('<uuid:property_id>/analytics/', views.PropertyAnalyticsView.as_view(), name='property-analytics'),
    
    # Include the router URLs for properties (comes last)
    path('', include(router.urls)),
] 