"""
URL patterns for locations app.
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

app_name = 'locations'

# Create a router and register our viewsets with it
router = DefaultRouter()
router.register(r'neighborhoods', views.NeighborhoodViewSet, basename='neighborhood')
router.register(r'schools', views.SchoolViewSet, basename='school')
router.register(r'pois', views.PointOfInterestViewSet, basename='poi')
router.register(r'transport-hubs', views.TransportHubViewSet, basename='transport-hub')

urlpatterns = [
    # Include the router URLs
    path('', include(router.urls)),
    
    # Neighborhood specific endpoints
    path('neighborhoods/<uuid:neighborhood_id>/insights/', views.NeighborhoodInsightsView.as_view(), name='neighborhood-insights'),
    path('neighborhoods/<uuid:neighborhood_id>/reviews/', views.NeighborhoodReviewsView.as_view(), name='neighborhood-reviews'),
    path('neighborhoods/<uuid:neighborhood_id>/properties/', views.NeighborhoodPropertiesView.as_view(), name='neighborhood-properties'),
    path('neighborhoods/<uuid:neighborhood_id>/analytics/', views.NeighborhoodAnalyticsView.as_view(), name='neighborhood-analytics'),
    
    # School specific endpoints
    path('schools/search/', views.SchoolSearchView.as_view(), name='school-search'),
    path('schools/<uuid:school_id>/catchment/', views.SchoolCatchmentView.as_view(), name='school-catchment'),
    path('schools/nearby/', views.NearbySchoolsView.as_view(), name='nearby-schools'),
    
    # POI specific endpoints
    path('pois/nearby/', views.NearbyPOIsView.as_view(), name='nearby-pois'),
    path('pois/category/<str:category>/', views.POIByCategoryView.as_view(), name='pois-by-category'),
    
    # Property-related location services
    path('properties/<uuid:property_id>/nearby-pois/', views.PropertyNearbyPOIsView.as_view(), name='property-nearby-pois'),
    path('properties/<uuid:property_id>/schools/', views.PropertyNearbySchoolsView.as_view(), name='property-nearby-schools'),
    path('properties/<uuid:property_id>/commute/', views.PropertyCommuteAnalysisView.as_view(), name='property-commute-analysis'),
    
    # Location intelligence
    path('commute/calculate/', views.CommuteCalculatorView.as_view(), name='commute-calculator'),
    path('walkability/', views.WalkabilityScoreView.as_view(), name='walkability-score'),
    path('connectivity/', views.ConnectivityScoreView.as_view(), name='connectivity-score'),
    
    # Map services
    path('map/bounds/', views.MapBoundsView.as_view(), name='map-bounds'),
    path('map/clusters/', views.MapClustersView.as_view(), name='map-clusters'),
    
    # Reviews and ratings
    path('reviews/neighborhood/', views.CreateNeighborhoodReviewView.as_view(), name='create-neighborhood-review'),
    path('reviews/property-visit/', views.CreatePropertyVisitReviewView.as_view(), name='create-property-visit-review'),
] 