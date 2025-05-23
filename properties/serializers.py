"""
Serializers for properties app.
"""

from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import (
    Property, PropertyMedia, BuildingMaterial, Appliance,
    PropertyLike, PropertyView, PropertyInquiry
)

User = get_user_model()


class PropertyMediaSerializer(serializers.ModelSerializer):
    """Serializer for property media"""
    
    class Meta:
        model = PropertyMedia
        fields = [
            'id', 'media_type', 'file', 'thumbnail', 'title', 'description',
            'alt_text', 'file_size', 'dimensions', 'duration', 'order',
            'is_primary', 'is_featured', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class BuildingMaterialSerializer(serializers.ModelSerializer):
    """Serializer for building materials"""
    
    class Meta:
        model = BuildingMaterial
        fields = [
            'id', 'component', 'material_type', 'brand', 'quality_score',
            'installation_date', 'warranty_period', 'maintenance_notes',
            'last_updated'
        ]
        read_only_fields = ['id', 'last_updated']


class ApplianceSerializer(serializers.ModelSerializer):
    """Serializer for appliances"""
    
    class Meta:
        model = Appliance
        fields = [
            'id', 'appliance_type', 'brand', 'model', 'age_years',
            'condition', 'warranty_status', 'warranty_expires',
            'specifications', 'energy_rating', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class PropertyOwnerSerializer(serializers.ModelSerializer):
    """Minimal serializer for property owner"""
    
    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name', 'user_type', 'phone_number']


class PropertyListSerializer(serializers.ModelSerializer):
    """Serializer for property list view"""
    owner = PropertyOwnerSerializer(read_only=True)
    agent = PropertyOwnerSerializer(read_only=True)
    primary_image = serializers.SerializerMethodField()
    price_formatted = serializers.ReadOnlyField()
    
    class Meta:
        model = Property
        fields = [
            'id', 'title', 'slug', 'property_type', 'listing_type', 'status',
            'address', 'locality', 'city', 'state', 'pincode',
            'latitude', 'longitude', 'price', 'price_formatted', 'price_per_sqft',
            'bedrooms', 'bathrooms', 'balconies', 'total_area', 'carpet_area',
            'furnishing_status', 'parking_spaces', 'property_age',
            'is_featured', 'is_premium', 'is_verified',
            'primary_image', 'views_count', 'likes_count', 'inquiries_count',
            'owner', 'agent', 'created_at', 'updated_at'
        ]
    
    def get_primary_image(self, obj):
        primary_media = obj.media.filter(is_primary=True).first()
        if primary_media and primary_media.file:
            return self.context['request'].build_absolute_uri(primary_media.file.url)
        return None


class PropertyDetailSerializer(serializers.ModelSerializer):
    """Serializer for property detail view"""
    owner = PropertyOwnerSerializer(read_only=True)
    agent = PropertyOwnerSerializer(read_only=True)
    verified_by = PropertyOwnerSerializer(read_only=True)
    media = PropertyMediaSerializer(many=True, read_only=True)
    building_materials = BuildingMaterialSerializer(many=True, read_only=True)
    appliances = ApplianceSerializer(many=True, read_only=True)
    price_formatted = serializers.ReadOnlyField()
    is_liked_by_user = serializers.SerializerMethodField()
    
    class Meta:
        model = Property
        fields = '__all__'
    
    def get_is_liked_by_user(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.likes.filter(user=request.user).exists()
        return False


class PropertyCreateUpdateSerializer(serializers.ModelSerializer):
    """Serializer for creating and updating properties"""
    
    class Meta:
        model = Property
        exclude = ['owner', 'agent', 'verified_by', 'verification_date', 'slug',
                  'views_count', 'likes_count', 'inquiries_count', 'price_per_sqft']
        
    def validate_price(self, value):
        if value <= 0:
            raise serializers.ValidationError("Price must be greater than 0")
        return value
    
    def validate_total_area(self, value):
        if value <= 0:
            raise serializers.ValidationError("Total area must be greater than 0")
        return value
    
    def validate(self, data):
        if data.get('bedrooms', 0) < 0:
            raise serializers.ValidationError("Bedrooms cannot be negative")
        if data.get('bathrooms', 0) < 0:
            raise serializers.ValidationError("Bathrooms cannot be negative")
        
        # Validate area relationships
        total_area = data.get('total_area')
        carpet_area = data.get('carpet_area')
        built_up_area = data.get('built_up_area')
        super_area = data.get('super_area')
        
        if carpet_area and total_area and carpet_area > total_area:
            raise serializers.ValidationError("Carpet area cannot be greater than total area")
        if built_up_area and total_area and built_up_area > total_area:
            raise serializers.ValidationError("Built-up area cannot be greater than total area")
        if super_area and total_area and super_area < total_area:
            raise serializers.ValidationError("Super area cannot be less than total area")
            
        return data


class PropertyLikeSerializer(serializers.ModelSerializer):
    """Serializer for property likes"""
    
    class Meta:
        model = PropertyLike
        fields = ['id', 'user', 'property', 'created_at']
        read_only_fields = ['id', 'user', 'created_at']


class PropertyViewSerializer(serializers.ModelSerializer):
    """Serializer for property views"""
    
    class Meta:
        model = PropertyView
        fields = [
            'id', 'property', 'user', 'ip_address', 'user_agent', 'referrer',
            'session_key', 'device_info', 'viewed_at', 'time_spent', 'interactions'
        ]
        read_only_fields = ['id', 'viewed_at']


class PropertyInquirySerializer(serializers.ModelSerializer):
    """Serializer for property inquiries"""
    property_title = serializers.CharField(source='property.title', read_only=True)
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    
    class Meta:
        model = PropertyInquiry
        fields = [
            'id', 'property', 'property_title', 'user', 'user_name',
            'inquiry_type', 'message', 'contact_phone', 'preferred_contact_time',
            'is_responded', 'response_message', 'responded_at', 'responded_by',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'user', 'property_title', 'user_name', 
                          'is_responded', 'responded_at', 'responded_by', 
                          'created_at', 'updated_at']


class PropertySearchSerializer(serializers.Serializer):
    """Serializer for property search parameters"""
    query = serializers.CharField(max_length=255, required=False)
    property_type = serializers.ChoiceField(choices=Property.PROPERTY_TYPES, required=False)
    listing_type = serializers.ChoiceField(choices=Property.LISTING_TYPES, required=False)
    status = serializers.ChoiceField(choices=Property.STATUS_CHOICES, required=False)
    
    # Price filters
    min_price = serializers.DecimalField(max_digits=15, decimal_places=2, required=False)
    max_price = serializers.DecimalField(max_digits=15, decimal_places=2, required=False)
    
    # Size filters
    min_bedrooms = serializers.IntegerField(min_value=0, required=False)
    max_bedrooms = serializers.IntegerField(min_value=0, required=False)
    min_bathrooms = serializers.IntegerField(min_value=0, required=False)
    max_bathrooms = serializers.IntegerField(min_value=0, required=False)
    min_area = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
    max_area = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
    
    # Location filters
    city = serializers.CharField(max_length=100, required=False)
    state = serializers.CharField(max_length=100, required=False)
    locality = serializers.CharField(max_length=100, required=False)
    pincode = serializers.CharField(max_length=10, required=False)
    
    # Geographic search
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False)
    radius_km = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, default=10)
    
    # Property features
    furnishing_status = serializers.ChoiceField(choices=Property.FURNISHING_STATUS, required=False)
    property_age = serializers.ChoiceField(choices=Property.PROPERTY_AGE, required=False)
    min_parking = serializers.IntegerField(min_value=0, required=False)
    
    # Flags
    is_featured = serializers.BooleanField(required=False)
    is_premium = serializers.BooleanField(required=False)
    is_verified = serializers.BooleanField(required=False)
    
    def validate(self, data):
        # Validate price range
        if data.get('min_price') and data.get('max_price'):
            if data['min_price'] > data['max_price']:
                raise serializers.ValidationError("Minimum price cannot be greater than maximum price")
        
        # Validate bedroom range
        if data.get('min_bedrooms') and data.get('max_bedrooms'):
            if data['min_bedrooms'] > data['max_bedrooms']:
                raise serializers.ValidationError("Minimum bedrooms cannot be greater than maximum bedrooms")
        
        # Validate area range
        if data.get('min_area') and data.get('max_area'):
            if data['min_area'] > data['max_area']:
                raise serializers.ValidationError("Minimum area cannot be greater than maximum area")
        
        # Validate geographic search
        latitude = data.get('latitude')
        longitude = data.get('longitude')
        if (latitude and not longitude) or (longitude and not latitude):
            raise serializers.ValidationError("Both latitude and longitude are required for geographic search")
        
        return data 