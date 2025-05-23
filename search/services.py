"""
Search services for 360ghar platform.
Advanced search functionality with analytics and optimization.
"""

import time
import uuid
from django.db.models import Q, Count, Avg, F
from django.utils import timezone
from django.core.paginator import Paginator
# Removed PostGIS imports for SQLite compatibility
from datetime import timedelta
import math

from properties.models import Property
from .models import (
    SavedSearch, SearchAnalytics, PopularSearch, 
    SearchSuggestion, LocationTrend
)
from .serializers import AdvancedSearchSerializer
from properties.serializers import PropertyListSerializer


class SearchService:
    """
    Comprehensive search service for properties with analytics.
    """
    
    def __init__(self):
        self.search_start_time = None
    
    def advanced_search(self, request_data, user=None, request=None):
        """
        Perform advanced property search with filters and analytics.
        """
        self.search_start_time = time.time()
        
        # Validate search parameters
        serializer = AdvancedSearchSerializer(data=request_data)
        if not serializer.is_valid():
            return {
                'error': 'Invalid search parameters',
                'details': serializer.errors
            }
        
        search_params = serializer.validated_data
        
        # Build base query
        queryset = self._build_search_query(search_params)
        
        # Apply sorting
        queryset = self._apply_sorting(queryset, search_params.get('sort_by', 'relevance'))
        
        # Paginate results
        page = search_params.get('page', 1)
        page_size = search_params.get('page_size', 20)
        paginator = Paginator(queryset, page_size)
        page_obj = paginator.get_page(page)
        
        # Serialize results
        properties = PropertyListSerializer(page_obj.object_list, many=True, context={'request': request}).data
        
        # Calculate search time
        search_time = time.time() - self.search_start_time
        
        # Track search analytics
        if search_params.get('track_search', True):
            self._track_search_analytics(search_params, user, request, len(properties), queryset.count())
        
        # Get suggestions and related searches
        suggestions = self._get_search_suggestions(search_params.get('query', ''))
        similar_searches = self._get_similar_searches(search_params)
        
        return {
            'results': properties,
            'total_count': paginator.count,
            'page': page,
            'page_size': page_size,
            'total_pages': paginator.num_pages,
            'has_next': page_obj.has_next(),
            'has_previous': page_obj.has_previous(),
            'search_time': round(search_time, 3),
            'suggestions': suggestions,
            'filters_applied': self._get_applied_filters(search_params),
            'similar_searches': similar_searches
        }
    
    def _build_search_query(self, search_params):
        """Build Django ORM query from search parameters."""
        queryset = Property.objects.filter(is_active=True)
        
        # Text search
        query = search_params.get('query', '').strip()
        if query:
            queryset = queryset.filter(
                Q(title__icontains=query) |
                Q(description__icontains=query) |
                Q(locality__icontains=query) |
                Q(city__icontains=query) |
                Q(address__icontains=query)
            )
            # Track popular search term
            PopularSearch.increment_search(query, 'property')
        
        # Property type filter
        property_types = search_params.get('property_type')
        if property_types:
            queryset = queryset.filter(property_type__in=property_types)
        
        # Listing type filter
        listing_type = search_params.get('listing_type')
        if listing_type:
            queryset = queryset.filter(listing_type=listing_type)
        
        # Price filters
        min_price = search_params.get('min_price')
        max_price = search_params.get('max_price')
        if min_price:
            queryset = queryset.filter(price__gte=min_price)
        if max_price:
            queryset = queryset.filter(price__lte=max_price)
        
        # Area filters
        min_area = search_params.get('min_area')
        max_area = search_params.get('max_area')
        if min_area:
            queryset = queryset.filter(total_area__gte=min_area)
        if max_area:
            queryset = queryset.filter(total_area__lte=max_area)
        
        # Bedroom filters
        bedrooms = search_params.get('bedrooms')
        if bedrooms:
            bedroom_conditions = Q()
            for bedroom in bedrooms:
                if bedroom == '6+':
                    bedroom_conditions |= Q(bedrooms__gte=6)
                else:
                    bedroom_conditions |= Q(bedrooms=int(bedroom))
            queryset = queryset.filter(bedroom_conditions)
        
        # Bathroom filters
        bathrooms = search_params.get('bathrooms')
        if bathrooms:
            bathroom_conditions = Q()
            for bathroom in bathrooms:
                if bathroom == '6+':
                    bathroom_conditions |= Q(bathrooms__gte=6)
                else:
                    bathroom_conditions |= Q(bathrooms=int(bathroom))
            queryset = queryset.filter(bathroom_conditions)
        
        # Location filters
        city = search_params.get('city')
        if city:
            queryset = queryset.filter(city__icontains=city)
        
        state = search_params.get('state')
        if state:
            queryset = queryset.filter(state__icontains=state)
        
        location = search_params.get('location')
        if location:
            queryset = queryset.filter(
                Q(locality__icontains=location) |
                Q(address__icontains=location)
            )
        
        # Geographic radius search (simplified for SQLite)
        latitude = search_params.get('latitude')
        longitude = search_params.get('longitude')
        radius = search_params.get('radius', 10)
        
        if latitude and longitude:
            # Simplified bounding box search for SQLite
            # Convert radius from km to degrees (rough approximation)
            lat_delta = radius / 111.0  # 1 degree ≈ 111 km
            lng_delta = radius / (111.0 * abs(math.cos(math.radians(float(latitude)))))
            
            min_lat = float(latitude) - lat_delta
            max_lat = float(latitude) + lat_delta
            min_lng = float(longitude) - lng_delta
            max_lng = float(longitude) + lng_delta
            
            queryset = queryset.filter(
                latitude__gte=min_lat,
                latitude__lte=max_lat,
                longitude__gte=min_lng,
                longitude__lte=max_lng
            )
        
        # Amenities filter
        amenities = search_params.get('amenities')
        if amenities:
            for amenity in amenities:
                queryset = queryset.filter(amenities__icontains=amenity)
        
        # Status filter
        statuses = search_params.get('status')
        if statuses:
            queryset = queryset.filter(status__in=statuses)
        else:
            # Default to available properties
            queryset = queryset.filter(status='available')
        
        # Property age filter
        property_age = search_params.get('property_age')
        if property_age:
            current_year = timezone.now().year
            if property_age == 'new':
                queryset = queryset.filter(year_built__isnull=True)  # Under construction
            elif property_age == '0-1':
                queryset = queryset.filter(year_built__gte=current_year - 1)
            elif property_age == '1-5':
                queryset = queryset.filter(year_built__gte=current_year - 5, year_built__lt=current_year - 1)
            elif property_age == '5-10':
                queryset = queryset.filter(year_built__gte=current_year - 10, year_built__lt=current_year - 5)
            elif property_age == '10+':
                queryset = queryset.filter(year_built__lt=current_year - 10)
        
        return queryset.distinct()
    
    def _apply_sorting(self, queryset, sort_by):
        """Apply sorting to the queryset."""
        sort_options = {
            'relevance': ['-is_featured', '-created_at'],  # Featured first, then newest
            'price_low': ['price'],
            'price_high': ['-price'],
            'area_low': ['total_area'],
            'area_high': ['-total_area'],
            'date_new': ['-created_at'],
            'date_old': ['created_at'],
            'popularity': ['-views_count', '-likes_count'],
        }
        
        sort_fields = sort_options.get(sort_by, ['-created_at'])
        return queryset.order_by(*sort_fields)
    
    def _track_search_analytics(self, search_params, user, request, results_count, total_count):
        """Track search analytics."""
        try:
            analytics_data = {
                'user': user if user and user.is_authenticated else None,
                'session_id': search_params.get('session_id', ''),
                'search_type': 'property',
                'search_query': search_params.get('query', ''),
                'search_filters': {k: v for k, v in search_params.items() 
                                 if k not in ['track_search', 'session_id', 'page', 'page_size']},
                'results_count': total_count,
                'search_location': search_params.get('location', ''),
                'user_latitude': search_params.get('latitude'),
                'user_longitude': search_params.get('longitude'),
            }
            
            if request:
                analytics_data.update({
                    'ip_address': self._get_client_ip(request),
                    'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                    'device_type': self._get_device_type(request),
                })
            
            SearchAnalytics.objects.create(**analytics_data)
            
        except Exception as e:
            # Log error but don't fail the search
            print(f"Analytics tracking error: {e}")
    
    def _get_search_suggestions(self, query, limit=10):
        """Get search suggestions based on query."""
        if not query or len(query) < 2:
            return []
        
        suggestions = SearchSuggestion.objects.filter(
            text__icontains=query,
            is_active=True
        ).order_by('-popularity_score')[:limit]
        
        return [{'text': s.text, 'type': s.suggestion_type} for s in suggestions]
    
    def _get_similar_searches(self, search_params, limit=5):
        """Get similar popular searches."""
        query = search_params.get('query', '')
        if not query:
            return []
        
        # Find searches with similar terms
        similar = PopularSearch.objects.filter(
            search_term__icontains=query,
            search_type='property'
        ).exclude(search_term=query.lower().strip()).order_by('-trending_score')[:limit]
        
        return [{'search_term': s.search_term, 'search_count': s.search_count} for s in similar]
    
    def _get_applied_filters(self, search_params):
        """Get summary of applied filters."""
        filters = {}
        
        filter_mapping = {
            'property_type': 'Property Types',
            'listing_type': 'Listing Type',
            'min_price': 'Min Price',
            'max_price': 'Max Price',
            'min_area': 'Min Area',
            'max_area': 'Max Area',
            'bedrooms': 'Bedrooms',
            'bathrooms': 'Bathrooms',
            'city': 'City',
            'location': 'Location',
            'amenities': 'Amenities',
            'property_age': 'Property Age',
        }
        
        for param, label in filter_mapping.items():
            value = search_params.get(param)
            if value:
                if isinstance(value, list):
                    filters[label] = ', '.join(map(str, value))
                else:
                    filters[label] = str(value)
        
        return filters
    
    def execute_saved_search(self, saved_search):
        """Execute a saved search and return results."""
        search_params = saved_search.search_filters.copy()
        search_params['query'] = saved_search.search_query
        search_params['track_search'] = False  # Don't track saved search executions
        
        # Add location data
        if saved_search.location:
            search_params['location'] = saved_search.location
        if saved_search.latitude and saved_search.longitude:
            search_params['latitude'] = float(saved_search.latitude)
            search_params['longitude'] = float(saved_search.longitude)
            search_params['radius'] = saved_search.radius
        
        results = self.advanced_search(search_params)
        
        # Update saved search statistics
        saved_search.total_results_found = results['total_count']
        saved_search.increment_search_count()
        
        return results
    
    def get_trending_searches(self, limit=10):
        """Get trending search terms."""
        return PopularSearch.objects.filter(
            is_trending=True
        ).order_by('-trending_score')[:limit]
    
    def get_popular_locations(self, limit=10):
        """Get popular/trending locations."""
        return LocationTrend.objects.filter(
            is_trending_up=True
        ).order_by('-trend_score')[:limit]
    
    def get_search_statistics(self, user=None, days=30):
        """Get comprehensive search statistics."""
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)
        
        base_query = SearchAnalytics.objects.filter(
            created_at__gte=start_date
        )
        
        if user:
            base_query = base_query.filter(user=user)
        
        stats = {
            'total_searches': base_query.count(),
            'unique_users': base_query.exclude(user__isnull=True).values('user').distinct().count(),
            'popular_searches': list(PopularSearch.objects.filter(
                last_searched__gte=start_date
            ).order_by('-search_count')[:10]),
            'trending_locations': list(LocationTrend.objects.filter(
                is_trending_up=True
            ).order_by('-trend_score')[:10]),
        }
        
        # Search volume trend (daily)
        daily_searches = base_query.extra(
            select={'day': 'date(created_at)'}
        ).values('day').annotate(
            count=Count('id')
        ).order_by('day')
        
        stats['search_volume_trend'] = {
            item['day'].strftime('%Y-%m-%d'): item['count'] 
            for item in daily_searches
        }
        
        # Top amenities searched
        amenity_searches = base_query.exclude(
            search_filters__amenities__isnull=True
        ).values_list('search_filters__amenities', flat=True)
        
        amenity_counts = {}
        for search_amenities in amenity_searches:
            if isinstance(search_amenities, list):
                for amenity in search_amenities:
                    amenity_counts[amenity] = amenity_counts.get(amenity, 0) + 1
        
        stats['top_amenities'] = sorted(
            [{'name': k, 'count': v} for k, v in amenity_counts.items()],
            key=lambda x: x['count'],
            reverse=True
        )[:10]
        
        return stats
    
    def _get_client_ip(self, request):
        """Get client IP address."""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', '')
    
    def _get_device_type(self, request):
        """Determine device type from user agent."""
        user_agent = request.META.get('HTTP_USER_AGENT', '').lower()
        
        if any(mobile in user_agent for mobile in ['mobile', 'android', 'iphone']):
            return 'mobile'
        elif 'tablet' in user_agent or 'ipad' in user_agent:
            return 'tablet'
        else:
            return 'desktop'


class SearchAutoCompleteService:
    """
    Service for handling search autocomplete and suggestions.
    """
    
    def get_suggestions(self, query, suggestion_type=None, limit=10):
        """Get autocomplete suggestions for a query."""
        if len(query) < 2:
            return []
        
        filters = {
            'text__icontains': query,
            'is_active': True
        }
        
        if suggestion_type:
            filters['suggestion_type'] = suggestion_type
        
        suggestions = SearchSuggestion.objects.filter(
            **filters
        ).order_by('-popularity_score')[:limit]
        
        return [
            {
                'text': s.text,
                'type': s.suggestion_type,
                'metadata': s.metadata
            }
            for s in suggestions
        ]
    
    def record_suggestion_click(self, suggestion_text):
        """Record when a user clicks on a suggestion."""
        try:
            suggestion = SearchSuggestion.objects.get(text=suggestion_text)
            suggestion.increment_usage('click')
        except SearchSuggestion.DoesNotExist:
            pass
    
    def create_suggestions_from_properties(self):
        """Create search suggestions from existing property data."""
        from properties.models import Property
        
        # Location suggestions
        locations = Property.objects.values_list('locality', flat=True).distinct()
        for location in locations:
            if location and len(location.strip()) > 2:
                SearchSuggestion.objects.get_or_create(
                    text=location.strip(),
                    defaults={
                        'suggestion_type': 'location',
                        'is_verified': True
                    }
                )
        
        # City suggestions
        cities = Property.objects.values_list('city', flat=True).distinct()
        for city in cities:
            if city and len(city.strip()) > 2:
                SearchSuggestion.objects.get_or_create(
                    text=city.strip(),
                    defaults={
                        'suggestion_type': 'location',
                        'is_verified': True
                    }
                )
        
        print("Search suggestions created from property data.")


class LocationTrendService:
    """
    Service for analyzing location trends and market data.
    """
    
    def update_location_trends(self):
        """Update location trends based on recent activity."""
        from properties.models import Property
        
        # Get all unique locations
        locations = Property.objects.values(
            'locality', 'city', 'state'
        ).annotate(
            property_count=Count('id'),
            avg_price=Avg('price'),
            active_count=Count('id', filter=Q(status='available'))
        ).filter(property_count__gt=0)
        
        for loc_data in locations:
            location_name = loc_data['locality']
            city = loc_data['city']
            state = loc_data['state']
            
            if not location_name or not city:
                continue
            
            # Get or create location trend
            trend, created = LocationTrend.objects.get_or_create(
                location_name=location_name,
                city=city,
                data_date=timezone.now().date(),
                defaults={
                    'state': state or '',
                    'property_count': loc_data['property_count'],
                    'average_price': loc_data['avg_price'],
                    'active_listings': loc_data['active_count'],
                }
            )
            
            if not created:
                # Update existing trend
                trend.property_count = loc_data['property_count']
                trend.average_price = loc_data['avg_price']
                trend.active_listings = loc_data['active_count']
            
            # Calculate search volume from analytics
            search_volume = SearchAnalytics.objects.filter(
                search_location__icontains=location_name,
                created_at__gte=timezone.now() - timedelta(days=7)
            ).count()
            
            trend.search_volume = search_volume
            
            # Calculate trend score (simplified)
            trend.trend_score = (
                search_volume * 2 + 
                trend.active_listings * 1.5 + 
                (trend.property_count / 10)
            )
            
            trend.is_trending_up = trend.trend_score > 50
            trend.is_hot_location = trend.trend_score > 100
            
            trend.save()
        
        print("Location trends updated successfully.") 