"""
Search views for 360ghar platform.
Comprehensive search functionality with analytics and advanced features.
"""

import uuid
from rest_framework import status, viewsets, filters
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone
from django.db.models import Q
from django.http import HttpResponse
import csv
import json

from .models import (
    SavedSearch, SearchAnalytics, PopularSearch, 
    SearchSuggestion, LocationTrend
)
from .serializers import (
    SavedSearchSerializer, SavedSearchCreateSerializer, SearchAnalyticsSerializer,
    PopularSearchSerializer, SearchSuggestionSerializer, LocationTrendSerializer,
    AdvancedSearchSerializer, SearchStatsSerializer, SearchResultsSerializer
)
from .services import SearchService, SearchAutoCompleteService, LocationTrendService


class AdvancedPropertySearchView(APIView):
    """Advanced property search with comprehensive filters and analytics"""
    permission_classes = [AllowAny]
    
    def post(self, request):
        """Perform advanced property search"""
        search_service = SearchService()
        
        # Get search parameters from request
        search_data = request.data.copy()
        
        # Add session tracking
        if not search_data.get('session_id'):
            search_data['session_id'] = str(uuid.uuid4())
        
        # Perform search
        results = search_service.advanced_search(
            request_data=search_data,
            user=request.user if request.user.is_authenticated else None,
            request=request
        )
        
        if 'error' in results:
            return Response(results, status=status.HTTP_400_BAD_REQUEST)
        
        return Response(results, status=status.HTTP_200_OK)
    
    def get(self, request):
        """Get search with query parameters"""
        search_data = dict(request.query_params)
        
        # Convert single-item lists to values
        for key, value in search_data.items():
            if isinstance(value, list) and len(value) == 1:
                search_data[key] = value[0]
        
        search_service = SearchService()
        results = search_service.advanced_search(
            request_data=search_data,
            user=request.user if request.user.is_authenticated else None,
            request=request
        )
        
        if 'error' in results:
            return Response(results, status=status.HTTP_400_BAD_REQUEST)
        
        return Response(results, status=status.HTTP_200_OK)


class AutocompleteView(APIView):
    """Search autocomplete and suggestions"""
    permission_classes = [AllowAny]
    
    def get(self, request):
        """Get autocomplete suggestions"""
        query = request.query_params.get('q', '').strip()
        suggestion_type = request.query_params.get('type', None)
        limit = int(request.query_params.get('limit', 10))
        
        if len(query) < 2:
            return Response({
                'suggestions': [],
                'message': 'Query must be at least 2 characters'
            })
        
        autocomplete_service = SearchAutoCompleteService()
        suggestions = autocomplete_service.get_suggestions(
            query=query,
            suggestion_type=suggestion_type,
            limit=limit
        )
        
        return Response({
            'suggestions': suggestions,
            'query': query,
            'total_suggestions': len(suggestions)
        })
    
    def post(self, request):
        """Record suggestion click"""
        suggestion_text = request.data.get('suggestion')
        if suggestion_text:
            autocomplete_service = SearchAutoCompleteService()
            autocomplete_service.record_suggestion_click(suggestion_text)
            
            return Response({'message': 'Click recorded'})
        
        return Response(
            {'error': 'Suggestion text required'}, 
            status=status.HTTP_400_BAD_REQUEST
        )


class PopularSearchesView(APIView):
    """Get popular and trending searches"""
    permission_classes = [AllowAny]
    
    def get(self, request):
        """Get popular searches"""
        limit = int(request.query_params.get('limit', 10))
        search_type = request.query_params.get('type', 'property')
        trending_only = request.query_params.get('trending', 'false').lower() == 'true'
        
        queryset = PopularSearch.objects.filter(search_type=search_type)
        
        if trending_only:
            queryset = queryset.filter(is_trending=True)
        
        popular_searches = queryset.order_by('-trending_score')[:limit]
        serializer = PopularSearchSerializer(popular_searches, many=True)
        
        return Response({
            'popular_searches': serializer.data,
            'total_count': len(serializer.data),
            'filters': {
                'type': search_type,
                'trending_only': trending_only
            }
        })


class SearchSuggestionsView(APIView):
    """Manage search suggestions"""
    permission_classes = [AllowAny]
    
    def get(self, request):
        """Get search suggestions"""
        suggestion_type = request.query_params.get('type')
        limit = int(request.query_params.get('limit', 20))
        verified_only = request.query_params.get('verified', 'false').lower() == 'true'
        
        queryset = SearchSuggestion.objects.filter(is_active=True)
        
        if suggestion_type:
            queryset = queryset.filter(suggestion_type=suggestion_type)
        
        if verified_only:
            queryset = queryset.filter(is_verified=True)
        
        suggestions = queryset.order_by('-popularity_score')[:limit]
        serializer = SearchSuggestionSerializer(suggestions, many=True)
        
        return Response({
            'suggestions': serializer.data,
            'total_count': len(serializer.data),
            'filters': {
                'type': suggestion_type,
                'verified_only': verified_only
            }
        })


class SearchTrendsView(APIView):
    """Get search trends and analytics"""
    permission_classes = [AllowAny]
    
    def get(self, request):
        """Get search trends"""
        search_service = SearchService()
        
        # Get trending searches
        trending_searches = search_service.get_trending_searches(limit=10)
        trending_serializer = PopularSearchSerializer(trending_searches, many=True)
        
        # Get popular locations
        popular_locations = search_service.get_popular_locations(limit=10)
        location_serializer = LocationTrendSerializer(popular_locations, many=True)
        
        # Get general statistics
        days = int(request.query_params.get('days', 30))
        stats = search_service.get_search_statistics(days=days)
        
        # Serialize the model objects in stats
        if 'popular_searches' in stats:
            popular_search_serializer = PopularSearchSerializer(stats['popular_searches'], many=True)
            stats['popular_searches'] = popular_search_serializer.data
        
        if 'trending_locations' in stats:
            location_trend_serializer = LocationTrendSerializer(stats['trending_locations'], many=True)
            stats['trending_locations'] = location_trend_serializer.data
        
        return Response({
            'trending_searches': trending_serializer.data,
            'popular_locations': location_serializer.data,
            'statistics': stats,
            'period_days': days
        })


class SavedSearchViewSet(viewsets.ModelViewSet):
    """Saved search management viewset"""
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        return SavedSearch.objects.filter(user=self.request.user, is_active=True)
    
    def get_serializer_class(self):
        if self.action == 'create':
            return SavedSearchCreateSerializer
        return SavedSearchSerializer
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
    
    def perform_destroy(self, instance):
        # Soft delete
        instance.is_active = False
        instance.save()


class SavedSearchResultsView(APIView):
    """Execute saved search and get results"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request, saved_search_id):
        """Execute saved search and return results"""
        try:
            saved_search = SavedSearch.objects.get(
                id=saved_search_id,
                user=request.user,
                is_active=True
            )
        except SavedSearch.DoesNotExist:
            return Response(
                {'error': 'Saved search not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        search_service = SearchService()
        results = search_service.execute_saved_search(saved_search)
        
        return Response({
            'saved_search': SavedSearchSerializer(saved_search).data,
            'results': results,
            'executed_at': timezone.now()
        })


class MapSearchView(APIView):
    """Map-based property search"""
    permission_classes = [AllowAny]
    
    def post(self, request):
        """Search properties within map bounds"""
        bounds = request.data.get('bounds', {})
        
        if not all(key in bounds for key in ['north', 'south', 'east', 'west']):
            return Response(
                {'error': 'Map bounds required (north, south, east, west)'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Convert bounds to center point and radius (simplified)
        center_lat = (bounds['north'] + bounds['south']) / 2
        center_lng = (bounds['east'] + bounds['west']) / 2
        
        # Calculate approximate radius (simplified)
        import math
        lat_diff = abs(bounds['north'] - bounds['south'])
        lng_diff = abs(bounds['east'] - bounds['west'])
        radius = max(lat_diff, lng_diff) * 111  # Approximate km per degree
        
        search_data = request.data.copy()
        search_data.update({
            'latitude': center_lat,
            'longitude': center_lng,
            'radius': min(radius, 100)  # Cap at 100km
        })
        
        search_service = SearchService()
        results = search_service.advanced_search(
            request_data=search_data,
            user=request.user if request.user.is_authenticated else None,
            request=request
        )
        
        if 'error' in results:
            return Response(results, status=status.HTTP_400_BAD_REQUEST)
        
        return Response(results)


class NearbySearchView(APIView):
    """Search properties near a specific location"""
    permission_classes = [AllowAny]
    
    def post(self, request):
        """Search properties near a location"""
        latitude = request.data.get('latitude')
        longitude = request.data.get('longitude')
        radius = request.data.get('radius', 10)
        
        if not latitude or not longitude:
            return Response(
                {'error': 'Latitude and longitude are required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        search_data = request.data.copy()
        search_data.update({
            'latitude': float(latitude),
            'longitude': float(longitude),
            'radius': min(int(radius), 100)
        })
        
        search_service = SearchService()
        results = search_service.advanced_search(
            request_data=search_data,
            user=request.user if request.user.is_authenticated else None,
            request=request
        )
        
        if 'error' in results:
            return Response(results, status=status.HTTP_400_BAD_REQUEST)
        
        return Response(results)


class LocalitySearchView(APIView):
    """Search properties by locality/area"""
    permission_classes = [AllowAny]
    
    def get(self, request):
        """Get localities with property counts"""
        from properties.models import Property
        from django.db.models import Count
        
        city = request.query_params.get('city')
        state = request.query_params.get('state')
        
        queryset = Property.objects.filter(is_active=True)
        
        if city:
            queryset = queryset.filter(city__icontains=city)
        if state:
            queryset = queryset.filter(state__icontains=state)
        
        localities = queryset.values('locality', 'city', 'state').annotate(
            property_count=Count('id')
        ).order_by('-property_count')[:50]
        
        return Response({
            'localities': list(localities),
            'total_localities': len(localities),
            'filters': {'city': city, 'state': state}
        })


class SearchAnalyticsView(APIView):
    """Search analytics and insights"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get user's search analytics"""
        if not request.user.is_staff:
            # Regular users only see their own analytics
            analytics = SearchAnalytics.objects.filter(
                user=request.user
            ).order_by('-created_at')[:50]
        else:
            # Staff can see all analytics
            analytics = SearchAnalytics.objects.all().order_by('-created_at')[:100]
        
        serializer = SearchAnalyticsSerializer(analytics, many=True)
        
        return Response({
            'analytics': serializer.data,
            'total_count': len(serializer.data)
        })


class SearchFiltersView(APIView):
    """Get available search filters and facets"""
    permission_classes = [AllowAny]
    
    def get(self, request):
        """Get available filter options"""
        from properties.models import Property
        
        # Get unique values for filter options
        property_types = Property.objects.values_list('property_type', flat=True).distinct()
        cities = Property.objects.values_list('city', flat=True).distinct()
        locations = Property.objects.values_list('locality', flat=True).distinct()
        
        # Price ranges (simplified)
        price_ranges = [
            {'label': 'Under ₹10L', 'min': 0, 'max': 1000000},
            {'label': '₹10L - ₹25L', 'min': 1000000, 'max': 2500000},
            {'label': '₹25L - ₹50L', 'min': 2500000, 'max': 5000000},
            {'label': '₹50L - ₹1Cr', 'min': 5000000, 'max': 10000000},
            {'label': 'Above ₹1Cr', 'min': 10000000, 'max': None},
        ]
        
        return Response({
            'property_types': [pt for pt in property_types if pt],
            'cities': [city for city in cities if city][:20],  # Limit cities
            'locations': [loc for loc in locations if loc][:30],  # Limit locations
            'price_ranges': price_ranges,
            'bedroom_options': ['1', '2', '3', '4', '5', '6+'],
            'bathroom_options': ['1', '2', '3', '4', '5', '6+'],
            'property_ages': [
                {'value': 'new', 'label': 'Under Construction'},
                {'value': '0-1', 'label': '0-1 Years'},
                {'value': '1-5', 'label': '1-5 Years'},
                {'value': '5-10', 'label': '5-10 Years'},
                {'value': '10+', 'label': '10+ Years'},
            ]
        })


class ExportSearchResultsView(APIView):
    """Export search results to CSV/Excel"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        """Export search results"""
        search_data = request.data.get('search_data', {})
        export_format = request.data.get('format', 'csv')
        
        search_service = SearchService()
        search_data['page_size'] = 1000  # Increase for export
        search_data['track_search'] = False  # Don't track export searches
        
        results = search_service.advanced_search(
            request_data=search_data,
            user=request.user,
            request=request
        )
        
        if 'error' in results:
            return Response(results, status=status.HTTP_400_BAD_REQUEST)
        
        if export_format.lower() == 'csv':
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = 'attachment; filename="search_results.csv"'
            
            writer = csv.writer(response)
            writer.writerow([
                'Title', 'Property Type', 'Price', 'Area', 'Bedrooms', 
                'Bathrooms', 'Location', 'City', 'Status'
            ])
            
            for property_data in results['results']:
                writer.writerow([
                    property_data.get('title', ''),
                    property_data.get('property_type', ''),
                    property_data.get('price', ''),
                    property_data.get('area', ''),
                    property_data.get('bedrooms', ''),
                    property_data.get('bathrooms', ''),
                    property_data.get('location', ''),
                    property_data.get('city', ''),
                    property_data.get('status', ''),
                ])
            
            return response
        
        return Response(
            {'error': 'Unsupported export format'}, 
            status=status.HTTP_400_BAD_REQUEST
        )


class NaturalLanguageSearchView(APIView):
    """Natural language search (basic implementation)"""
    permission_classes = [AllowAny]
    
    def post(self, request):
        """Process natural language search query"""
        query = request.data.get('query', '').strip()
        
        if not query:
            return Response(
                {'error': 'Search query required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Basic natural language processing (simplified)
        search_data = self._parse_natural_language(query)
        search_data['query'] = query
        
        search_service = SearchService()
        results = search_service.advanced_search(
            request_data=search_data,
            user=request.user if request.user.is_authenticated else None,
            request=request
        )
        
        if 'error' in results:
            return Response(results, status=status.HTTP_400_BAD_REQUEST)
        
        return Response({
            'original_query': query,
            'parsed_filters': search_data,
            'results': results
        })
    
    def _parse_natural_language(self, query):
        """Basic natural language parsing"""
        search_data = {}
        query_lower = query.lower()
        
        # Extract property type
        property_types = ['apartment', 'house', 'villa', 'studio', 'penthouse']
        for prop_type in property_types:
            if prop_type in query_lower:
                search_data['property_type'] = [prop_type]
                break
        
        # Extract bedrooms
        import re
        bedroom_match = re.search(r'(\d+)\s*(?:bed|bedroom)', query_lower)
        if bedroom_match:
            search_data['bedrooms'] = [bedroom_match.group(1)]
        
        # Extract price range
        price_match = re.search(r'(?:under|below)\s*₹?(\d+)(?:\s*(?:lakh|l|crore|cr))?', query_lower)
        if price_match:
            amount = int(price_match.group(1))
            if 'crore' in query_lower or 'cr' in query_lower:
                search_data['max_price'] = amount * 10000000
            elif 'lakh' in query_lower or 'l' in query_lower:
                search_data['max_price'] = amount * 100000
        
        # Extract location
        location_keywords = ['in', 'at', 'near']
        for keyword in location_keywords:
            if keyword in query_lower:
                parts = query_lower.split(keyword)
                if len(parts) > 1:
                    location = parts[-1].strip()
                    # Remove common words
                    location = re.sub(r'\b(the|a|an|with|having)\b', '', location).strip()
                    if location:
                        search_data['location'] = location
                break
        
        return search_data


# Management command views (for admin use)
class GenerateSearchSuggestionsView(APIView):
    """Generate search suggestions from existing data"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        """Generate suggestions from property data"""
        if not request.user.is_staff:
            return Response(
                {'error': 'Admin access required'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        autocomplete_service = SearchAutoCompleteService()
        autocomplete_service.create_suggestions_from_properties()
        
        return Response({'message': 'Search suggestions generated successfully'})


class UpdateLocationTrendsView(APIView):
    """Update location trends data"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        """Update location trends"""
        if not request.user.is_staff:
            return Response(
                {'error': 'Admin access required'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        trend_service = LocationTrendService()
        trend_service.update_location_trends()
        
        return Response({'message': 'Location trends updated successfully'})


# Deprecated/Placeholder views (for backward compatibility)
class PropertySearchView(APIView):
    """Redirect to advanced search"""
    permission_classes = [AllowAny]
    
    def get(self, request, *args, **kwargs):
        return Response({
            "message": "This endpoint has been deprecated. Please use /api/v1/search/advanced/ instead"
        }, status=status.HTTP_301_MOVED_PERMANENTLY)


class RadiusSearchView(APIView):
    """Redirect to nearby search"""
    permission_classes = [AllowAny]
    
    def get(self, request, *args, **kwargs):
        return Response({
            "message": "This endpoint has been deprecated. Please use /api/v1/search/nearby/ instead"
        }, status=status.HTTP_301_MOVED_PERMANENTLY)


class CommuteTimeSearchView(APIView):
    """Commute time search - to be implemented"""
    permission_classes = [AllowAny]
    
    def post(self, request):
        return Response({
            'message': 'Commute time search will be implemented in a future update',
            'suggestion': 'Use nearby search with specific coordinates for now'
        }, status=status.HTTP_501_NOT_IMPLEMENTED)


class SearchFacetsView(APIView):
    """Redirect to search filters"""
    permission_classes = [AllowAny]
    
    def get(self, request, *args, **kwargs):
        return Response({
            "message": "This endpoint has been deprecated. Please use /api/v1/search/filters/ instead"
        }, status=status.HTTP_301_MOVED_PERMANENTLY)
