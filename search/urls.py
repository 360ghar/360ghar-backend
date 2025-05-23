"""
URL patterns for search app.
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

app_name = 'search'

# Create router for ViewSets
router = DefaultRouter()
router.register(r'saved', views.SavedSearchViewSet, basename='saved-search')

urlpatterns = [
    # Include router URLs (saved searches ViewSet)
    path('', include(router.urls)),
    
    # Main Search Endpoints
    path('advanced/', views.AdvancedPropertySearchView.as_view(), name='advanced-property-search'),
    path('autocomplete/', views.AutocompleteView.as_view(), name='autocomplete'),
    path('nearby/', views.NearbySearchView.as_view(), name='nearby-search'),
    path('map/', views.MapSearchView.as_view(), name='map-search'),
    path('natural-language/', views.NaturalLanguageSearchView.as_view(), name='natural-language-search'),
    
    # Search Information & Analytics
    path('popular/', views.PopularSearchesView.as_view(), name='popular-searches'),
    path('suggestions/', views.SearchSuggestionsView.as_view(), name='search-suggestions'),
    path('trends/', views.SearchTrendsView.as_view(), name='search-trends'),
    path('analytics/', views.SearchAnalyticsView.as_view(), name='search-analytics'),
    
    # Search Utilities
    path('filters/', views.SearchFiltersView.as_view(), name='search-filters'),
    path('localities/', views.LocalitySearchView.as_view(), name='locality-search'),
    path('export/', views.ExportSearchResultsView.as_view(), name='export-search-results'),
    
    # Saved Search Results
    path('saved/<uuid:saved_search_id>/results/', views.SavedSearchResultsView.as_view(), name='saved-search-results'),
    
    # Admin Management Endpoints
    path('admin/generate-suggestions/', views.GenerateSearchSuggestionsView.as_view(), name='generate-suggestions'),
    path('admin/update-trends/', views.UpdateLocationTrendsView.as_view(), name='update-trends'),
    
    # Deprecated/Redirected Endpoints (for backward compatibility)
    path('properties/', views.PropertySearchView.as_view(), name='property-search'),
    path('radius/', views.RadiusSearchView.as_view(), name='radius-search'),
    path('facets/', views.SearchFacetsView.as_view(), name='search-facets'),
    
    # Future Features
    path('commute-time/', views.CommuteTimeSearchView.as_view(), name='commute-time-search'),
] 