import django_filters
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import Distance
from .models import Property


class PropertyFilter(django_filters.FilterSet):
    """
    Comprehensive filter for Property model with geospatial support
    """
    
    # Price filters
    min_price = django_filters.NumberFilter(field_name='price', lookup_expr='gte')
    max_price = django_filters.NumberFilter(field_name='price', lookup_expr='lte')
    price_range = django_filters.RangeFilter(field_name='price')
    
    # Area filters
    min_area = django_filters.NumberFilter(field_name='total_area', lookup_expr='gte')
    max_area = django_filters.NumberFilter(field_name='total_area', lookup_expr='lte')
    area_range = django_filters.RangeFilter(field_name='total_area')
    
    # Bedroom filters
    min_bedrooms = django_filters.NumberFilter(field_name='bedrooms', lookup_expr='gte')
    max_bedrooms = django_filters.NumberFilter(field_name='bedrooms', lookup_expr='lte')
    bedrooms_exact = django_filters.NumberFilter(field_name='bedrooms', lookup_expr='exact')
    
    # Bathroom filters
    min_bathrooms = django_filters.NumberFilter(field_name='bathrooms', lookup_expr='gte')
    max_bathrooms = django_filters.NumberFilter(field_name='bathrooms', lookup_expr='lte')
    bathrooms_exact = django_filters.NumberFilter(field_name='bathrooms', lookup_expr='exact')
    
    # Location filters
    city = django_filters.CharFilter(field_name='city', lookup_expr='icontains')
    state = django_filters.CharFilter(field_name='state', lookup_expr='icontains')
    neighborhood = django_filters.CharFilter(field_name='neighborhood', lookup_expr='icontains')
    zip_code = django_filters.CharFilter(field_name='zip_code', lookup_expr='exact')
    
    # Property characteristics
    property_type = django_filters.ChoiceFilter(choices=Property.PROPERTY_TYPES)
    listing_type = django_filters.ChoiceFilter(choices=Property.LISTING_TYPES)
    status = django_filters.ChoiceFilter(choices=Property.STATUS_CHOICES)
    
    # Year built filters
    min_year_built = django_filters.NumberFilter(field_name='year_built', lookup_expr='gte')
    max_year_built = django_filters.NumberFilter(field_name='year_built', lookup_expr='lte')
    year_built_range = django_filters.RangeFilter(field_name='year_built')
    
    # Parking and garage
    min_parking_spaces = django_filters.NumberFilter(field_name='parking_spaces', lookup_expr='gte')
    garage_type = django_filters.CharFilter(field_name='garage_type', lookup_expr='icontains')
    
    # Property features (JSON field searches)
    has_amenity = django_filters.CharFilter(method='filter_amenities')
    has_feature = django_filters.CharFilter(method='filter_features')
    has_interior_feature = django_filters.CharFilter(method='filter_interior_features')
    has_exterior_feature = django_filters.CharFilter(method='filter_exterior_features')
    
    # Utilities and systems
    heating_type = django_filters.CharFilter(field_name='heating_type', lookup_expr='icontains')
    cooling_type = django_filters.CharFilter(field_name='cooling_type', lookup_expr='icontains')
    flooring_type = django_filters.CharFilter(field_name='flooring_type', lookup_expr='icontains')
    
    # Financial filters
    max_hoa_fee = django_filters.NumberFilter(field_name='hoa_fee', lookup_expr='lte')
    max_property_tax = django_filters.NumberFilter(field_name='property_tax', lookup_expr='lte')
    min_rental_income = django_filters.NumberFilter(field_name='rental_income', lookup_expr='gte')
    
    # Boolean filters
    is_featured = django_filters.BooleanFilter(field_name='is_featured')
    furnishing_status = django_filters.ChoiceFilter(choices=Property.FURNISHING_STATUS)
    
    # Date filters
    created_after = django_filters.DateFilter(field_name='created_at', lookup_expr='gte')
    created_before = django_filters.DateFilter(field_name='created_at', lookup_expr='lte')
    updated_after = django_filters.DateFilter(field_name='updated_at', lookup_expr='gte')
    updated_before = django_filters.DateFilter(field_name='updated_at', lookup_expr='lte')
    
    # Geospatial filters
    near_latitude = django_filters.NumberFilter(method='filter_near_location')
    near_longitude = django_filters.NumberFilter(method='filter_near_location')
    radius_km = django_filters.NumberFilter(method='filter_radius')
    
    class Meta:
        model = Property
        fields = {
            'title': ['icontains', 'exact'],
            'description': ['icontains'],
            'address': ['icontains'],
            'owner': ['exact'],
            'property_type': ['exact'],
            'listing_type': ['exact'],
            'status': ['exact'],
            'price': ['exact', 'gte', 'lte'],
            'bedrooms': ['exact', 'gte', 'lte'],
            'bathrooms': ['exact', 'gte', 'lte'],
            'total_area': ['exact', 'gte', 'lte'],
            'year_built': ['exact', 'gte', 'lte'],
            'parking_spaces': ['exact', 'gte', 'lte'],
            'is_featured': ['exact'],
            'furnishing_status': ['exact'],
        }
    
    def filter_amenities(self, queryset, name, value):
        """Filter by amenities in JSON field"""
        if value:
            return queryset.filter(amenities__icontains=value)
        return queryset
    
    def filter_features(self, queryset, name, value):
        """Filter by features in JSON field"""
        if value:
            return queryset.filter(features__icontains=value)
        return queryset
    
    def filter_interior_features(self, queryset, name, value):
        """Filter by interior features in JSON field"""
        if value:
            return queryset.filter(interior_features__icontains=value)
        return queryset
    
    def filter_exterior_features(self, queryset, name, value):
        """Filter by exterior features in JSON field"""
        if value:
            return queryset.filter(exterior_features__icontains=value)
        return queryset
    
    def filter_near_location(self, queryset, name, value):
        """Filter properties near a specific location"""
        # This method is called for both latitude and longitude
        # We need to check if both are provided in the request
        request = self.request
        if hasattr(request, 'GET'):
            latitude = request.GET.get('near_latitude')
            longitude = request.GET.get('near_longitude')
            radius = request.GET.get('radius_km', 10)  # Default 10 km
            
            if latitude and longitude:
                try:
                    lat = float(latitude)
                    lng = float(longitude)
                    radius_km = float(radius)
                    
                    point = Point(lng, lat)
                    return queryset.filter(
                        location__distance_lte=(point, Distance(km=radius_km))
                    ).annotate(
                        distance=Distance('location', point)
                    ).order_by('distance')
                except (ValueError, TypeError):
                    pass
        
        return queryset
    
    def filter_radius(self, queryset, name, value):
        """Filter by radius - used in conjunction with near_location"""
        # This is handled in filter_near_location method
        return queryset


class PropertySearchFilter(django_filters.FilterSet):
    """
    Simplified filter for property search with text search capabilities
    """
    
    # Text search across multiple fields
    search = django_filters.CharFilter(method='filter_search')
    
    # Quick filters
    property_type = django_filters.ChoiceFilter(choices=Property.PROPERTY_TYPES)
    listing_type = django_filters.ChoiceFilter(choices=Property.LISTING_TYPES)
    min_price = django_filters.NumberFilter(field_name='price', lookup_expr='gte')
    max_price = django_filters.NumberFilter(field_name='price', lookup_expr='lte')
    bedrooms = django_filters.NumberFilter(field_name='bedrooms', lookup_expr='exact')
    bathrooms = django_filters.NumberFilter(field_name='bathrooms', lookup_expr='gte')
    
    # Location
    city = django_filters.CharFilter(field_name='city', lookup_expr='icontains')
    state = django_filters.CharFilter(field_name='state', lookup_expr='icontains')
    
    class Meta:
        model = Property
        fields = ['search', 'property_type', 'listing_type', 'min_price', 'max_price', 
                 'bedrooms', 'bathrooms', 'city', 'state']
    
    def filter_search(self, queryset, name, value):
        """Full text search across multiple fields"""
        if value:
            from django.db.models import Q
            return queryset.filter(
                Q(title__icontains=value) |
                Q(description__icontains=value) |
                Q(address__icontains=value) |
                Q(city__icontains=value) |
                Q(neighborhood__icontains=value) |
                Q(amenities__icontains=value) |
                Q(features__icontains=value)
            )
        return queryset 