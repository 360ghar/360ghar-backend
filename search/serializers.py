"""
Serializers for search app.
Advanced search functionality serializers.
"""

from rest_framework import serializers
from django.utils import timezone
from .models import (
    SavedSearch, SearchAnalytics, PopularSearch, 
    SearchSuggestion, LocationTrend
)


class SavedSearchSerializer(serializers.ModelSerializer):
    """Serializer for SavedSearch model"""
    
    class Meta:
        model = SavedSearch
        fields = [
            'id', 'name', 'search_type', 'search_query', 'search_filters',
            'location', 'latitude', 'longitude', 'radius',
            'email_notifications', 'notification_frequency',
            'search_count', 'last_searched', 'total_results_found',
            'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'search_count', 'last_searched', 'total_results_found',
            'created_at', 'updated_at'
        ]
    
    def validate_search_filters(self, value):
        """Validate search filters format"""
        if not isinstance(value, dict):
            raise serializers.ValidationError("Search filters must be a valid JSON object")
        return value
    
    def validate_radius(self, value):
        """Validate search radius"""
        if value < 1 or value > 100:
            raise serializers.ValidationError("Radius must be between 1 and 100 kilometers")
        return value


class SavedSearchCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating saved searches"""
    
    class Meta:
        model = SavedSearch
        fields = [
            'name', 'search_type', 'search_query', 'search_filters',
            'location', 'latitude', 'longitude', 'radius',
            'email_notifications', 'notification_frequency'
        ]
    
    def create(self, validated_data):
        validated_data['user'] = self.context['request'].user
        return super().create(validated_data)


class SearchAnalyticsSerializer(serializers.ModelSerializer):
    """Serializer for SearchAnalytics model"""
    username = serializers.CharField(source='user.username', read_only=True)
    
    class Meta:
        model = SearchAnalytics
        fields = [
            'id', 'username', 'session_id', 'search_type', 'search_query',
            'search_filters', 'results_count', 'clicked_results', 'search_duration',
            'search_location', 'user_latitude', 'user_longitude',
            'device_type', 'time_on_results_page', 'pages_viewed',
            'properties_viewed', 'properties_liked', 'properties_shared',
            'inquiry_sent', 'contact_made', 'saved_search_created',
            'created_at'
        ]
        read_only_fields = ['id', 'username', 'created_at']


class PopularSearchSerializer(serializers.ModelSerializer):
    """Serializer for PopularSearch model"""
    
    class Meta:
        model = PopularSearch
        fields = [
            'search_term', 'search_type', 'search_count', 'unique_users_count',
            'this_week_count', 'this_month_count', 'trending_score', 'is_trending',
            'associated_locations', 'average_price_range', 'last_searched'
        ]
        read_only_fields = [
            'search_term', 'search_type', 'search_count', 'unique_users_count',
            'this_week_count', 'this_month_count', 'trending_score', 'is_trending',
            'associated_locations', 'average_price_range', 'last_searched'
        ]


class SearchSuggestionSerializer(serializers.ModelSerializer):
    """Serializer for SearchSuggestion model"""
    
    class Meta:
        model = SearchSuggestion
        fields = [
            'text', 'suggestion_type', 'popularity_score', 'click_count',
            'search_count', 'associated_locations', 'metadata', 'is_verified'
        ]
        read_only_fields = [
            'popularity_score', 'click_count', 'search_count', 'is_verified'
        ]


class LocationTrendSerializer(serializers.ModelSerializer):
    """Serializer for LocationTrend model"""
    price_change_indicator = serializers.SerializerMethodField()
    formatted_average_price = serializers.SerializerMethodField()
    
    class Meta:
        model = LocationTrend
        fields = [
            'location_name', 'city', 'state', 'latitude', 'longitude',
            'average_price', 'formatted_average_price', 'price_per_sqft', 
            'price_trend', 'price_change_indicator', 'search_volume',
            'property_count', 'active_listings', 'trend_score',
            'is_trending_up', 'is_hot_location', 'data_date'
        ]
        read_only_fields = [
            'location_name', 'city', 'state', 'latitude', 'longitude',
            'average_price', 'formatted_average_price', 'price_per_sqft', 
            'price_trend', 'price_change_indicator', 'search_volume',
            'property_count', 'active_listings', 'trend_score',
            'is_trending_up', 'is_hot_location', 'data_date'
        ]
    
    def get_price_change_indicator(self, obj):
        """Get price change indicator"""
        if obj.price_trend > 5:
            return 'strong_up'
        elif obj.price_trend > 0:
            return 'up'
        elif obj.price_trend < -5:
            return 'strong_down'
        elif obj.price_trend < 0:
            return 'down'
        return 'stable'
    
    def get_formatted_average_price(self, obj):
        """Format average price in Indian currency"""
        if not obj.average_price:
            return None
        
        price = float(obj.average_price)
        if price >= 10000000:  # 1 crore
            return f"₹ {price/10000000:.2f} Cr"
        elif price >= 100000:  # 1 lakh
            return f"₹ {price/100000:.2f} L"
        else:
            return f"₹ {price:,.0f}"


class AdvancedSearchSerializer(serializers.Serializer):
    """Serializer for advanced property search requests"""
    
    # Text search
    query = serializers.CharField(max_length=200, required=False, allow_blank=True)
    
    # Property filters
    property_type = serializers.MultipleChoiceField(
        choices=[
            ('apartment', 'Apartment'),
            ('house', 'House'),
            ('villa', 'Villa'),
            ('studio', 'Studio'),
            ('penthouse', 'Penthouse'),
            ('commercial', 'Commercial'),
            ('land', 'Land'),
        ],
        required=False
    )
    listing_type = serializers.ChoiceField(
        choices=[('sale', 'Sale'), ('rent', 'Rent')],
        required=False
    )
    
    # Price filters
    min_price = serializers.DecimalField(max_digits=15, decimal_places=2, required=False)
    max_price = serializers.DecimalField(max_digits=15, decimal_places=2, required=False)
    
    # Area filters
    min_area = serializers.IntegerField(required=False)
    max_area = serializers.IntegerField(required=False)
    
    # Bedroom/Bathroom filters
    bedrooms = serializers.MultipleChoiceField(
        choices=[(str(i), str(i)) for i in range(1, 6)] + [('6+', '6+')],
        required=False
    )
    bathrooms = serializers.MultipleChoiceField(
        choices=[(str(i), str(i)) for i in range(1, 6)] + [('6+', '6+')],
        required=False
    )
    
    # Location filters
    location = serializers.CharField(max_length=200, required=False)
    city = serializers.CharField(max_length=100, required=False)
    state = serializers.CharField(max_length=100, required=False)
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False)
    radius = serializers.IntegerField(min_value=1, max_value=100, required=False)
    
    # Amenities
    amenities = serializers.ListField(
        child=serializers.CharField(max_length=50),
        required=False
    )
    
    # Status filters
    status = serializers.MultipleChoiceField(
        choices=[
            ('available', 'Available'),
            ('sold', 'Sold'),
            ('rented', 'Rented'),
            ('under_offer', 'Under Offer'),
        ],
        required=False
    )
    
    # Age filters
    property_age = serializers.ChoiceField(
        choices=[
            ('new', 'Under Construction'),
            ('0-1', '0-1 Years'),
            ('1-5', '1-5 Years'),
            ('5-10', '5-10 Years'),
            ('10+', '10+ Years'),
        ],
        required=False
    )
    
    # Sorting
    sort_by = serializers.ChoiceField(
        choices=[
            ('relevance', 'Relevance'),
            ('price_low', 'Price: Low to High'),
            ('price_high', 'Price: High to Low'),
            ('area_low', 'Area: Low to High'),
            ('area_high', 'Area: High to Low'),
            ('date_new', 'Date: Newest First'),
            ('date_old', 'Date: Oldest First'),
            ('popularity', 'Most Popular'),
        ],
        default='relevance',
        required=False
    )
    
    # Pagination
    page = serializers.IntegerField(min_value=1, default=1, required=False)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=20, required=False)
    
    # Search analytics
    track_search = serializers.BooleanField(default=True, required=False)
    session_id = serializers.CharField(max_length=50, required=False)
    
    def validate(self, data):
        """Validate search parameters"""
        # Validate price range
        min_price = data.get('min_price')
        max_price = data.get('max_price')
        if min_price and max_price and min_price > max_price:
            raise serializers.ValidationError("Minimum price cannot be greater than maximum price")
        
        # Validate area range
        min_area = data.get('min_area')
        max_area = data.get('max_area')
        if min_area and max_area and min_area > max_area:
            raise serializers.ValidationError("Minimum area cannot be greater than maximum area")
        
        # Validate location radius (requires coordinates)
        radius = data.get('radius')
        latitude = data.get('latitude')
        longitude = data.get('longitude')
        if radius and not (latitude and longitude):
            raise serializers.ValidationError("Radius search requires latitude and longitude coordinates")
        
        return data


class SearchStatsSerializer(serializers.Serializer):
    """Serializer for search statistics"""
    total_searches = serializers.IntegerField()
    unique_users = serializers.IntegerField()
    popular_searches = PopularSearchSerializer(many=True)
    trending_locations = LocationTrendSerializer(many=True)
    search_volume_trend = serializers.DictField()
    top_amenities = serializers.ListField()
    average_price_trends = serializers.DictField()


class SearchResultsSerializer(serializers.Serializer):
    """Serializer for search results response"""
    results = serializers.ListField()
    total_count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    total_pages = serializers.IntegerField()
    has_next = serializers.BooleanField()
    has_previous = serializers.BooleanField()
    search_time = serializers.FloatField()
    suggestions = SearchSuggestionSerializer(many=True, required=False)
    filters_applied = serializers.DictField()
    similar_searches = PopularSearchSerializer(many=True, required=False) 