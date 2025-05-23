"""
Location models for 360ghar application.
Includes neighborhoods, schools, POIs, and other geographical data.
"""

from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
import uuid


class Neighborhood(models.Model):
    """
    Neighborhood/locality information with boundaries and demographics.
    """
    
    NEIGHBORHOOD_TYPES = (
        ('residential', 'Residential'),
        ('commercial', 'Commercial'),
        ('mixed', 'Mixed Use'),
        ('industrial', 'Industrial'),
    )
    
    DEVELOPMENT_LEVELS = (
        ('developing', 'Developing'),
        ('developed', 'Well Developed'),
        ('premium', 'Premium'),
        ('luxury', 'Luxury'),
    )
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, db_index=True)
    slug = models.SlugField(max_length=250, unique=True)
    
    # Location data (simplified for SQLite development)
    boundaries_data = models.JSONField(default=dict, blank=True, help_text="Polygon boundaries as JSON")
    center_latitude = models.DecimalField(max_digits=9, decimal_places=6, db_index=True)
    center_longitude = models.DecimalField(max_digits=9, decimal_places=6, db_index=True)
    
    # Administrative details
    city = models.CharField(max_length=100, db_index=True)
    state = models.CharField(max_length=100, db_index=True)
    country = models.CharField(max_length=100, default='India')
    pincode = models.CharField(max_length=10, db_index=True)
    
    # Classification
    neighborhood_type = models.CharField(max_length=20, choices=NEIGHBORHOOD_TYPES)
    development_level = models.CharField(max_length=20, choices=DEVELOPMENT_LEVELS)
    
    # Demographics
    population = models.PositiveIntegerField(blank=True, null=True)
    area_sqkm = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    population_density = models.PositiveIntegerField(blank=True, null=True)  # per sq km
    
    # Economic data
    average_property_price = models.DecimalField(max_digits=15, decimal_places=2, blank=True, null=True)
    price_growth_rate = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)  # percentage
    
    # Demographics breakdown
    demographics = models.JSONField(default=dict, blank=True, help_text="Age groups, income levels, etc.")
    
    # Amenities and features
    amenities = models.JSONField(default=list, blank=True)
    connectivity = models.JSONField(default=dict, blank=True, help_text="Metro, bus, highways etc.")
    
    # Ratings and scores
    safety_rating = models.DecimalField(max_digits=3, decimal_places=2, blank=True, null=True)
    connectivity_rating = models.DecimalField(max_digits=3, decimal_places=2, blank=True, null=True)
    lifestyle_rating = models.DecimalField(max_digits=3, decimal_places=2, blank=True, null=True)
    environment_rating = models.DecimalField(max_digits=3, decimal_places=2, blank=True, null=True)
    
    # SEO and content
    description = models.TextField(blank=True)
    highlights = models.JSONField(default=list, blank=True)
    future_developments = models.JSONField(default=list, blank=True)
    
    # Statistics
    properties_count = models.PositiveIntegerField(default=0)
    views_count = models.PositiveIntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'neighborhoods'
        indexes = [
            models.Index(fields=['city', 'state']),
            models.Index(fields=['neighborhood_type']),
            models.Index(fields=['center_latitude', 'center_longitude']),
        ]
    
    def __str__(self):
        return f"{self.name}, {self.city}"


class School(models.Model):
    """
    Schools and educational institutions.
    """
    
    SCHOOL_TYPES = (
        ('primary', 'Primary School'),
        ('secondary', 'Secondary School'),
        ('high_school', 'High School'),
        ('college', 'College'),
        ('university', 'University'),
        ('professional', 'Professional Institute'),
    )
    
    BOARDS = (
        ('cbse', 'CBSE'),
        ('icse', 'ICSE'),
        ('state', 'State Board'),
        ('ib', 'International Baccalaureate'),
        ('cambridge', 'Cambridge'),
        ('other', 'Other'),
    )
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, db_index=True)
    
    # Location (simplified for SQLite development)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, db_index=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, db_index=True)
    address = models.TextField()
    neighborhood = models.ForeignKey(
        Neighborhood, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='schools'
    )
    
    # Catchment area (simplified for SQLite development)
    catchment_area_data = models.JSONField(default=dict, blank=True, help_text="Catchment area as JSON")
    
    # Classification
    school_type = models.CharField(max_length=20, choices=SCHOOL_TYPES)
    board = models.CharField(max_length=20, choices=BOARDS, blank=True)
    is_government = models.BooleanField(default=False)
    is_coeducational = models.BooleanField(default=True)
    
    # Ratings and performance
    overall_rating = models.DecimalField(
        max_digits=3, 
        decimal_places=2, 
        validators=[MinValueValidator(0), MaxValueValidator(5)],
        blank=True, 
        null=True
    )
    academic_rating = models.DecimalField(max_digits=3, decimal_places=2, blank=True, null=True)
    infrastructure_rating = models.DecimalField(max_digits=3, decimal_places=2, blank=True, null=True)
    teacher_rating = models.DecimalField(max_digits=3, decimal_places=2, blank=True, null=True)
    
    # Academic performance
    pass_percentage = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    average_score = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    
    # Facilities and features
    facilities = models.JSONField(default=list, blank=True)
    extracurricular = models.JSONField(default=list, blank=True)
    
    # Contact information
    website = models.URLField(blank=True)
    phone_number = models.CharField(max_length=15, blank=True)
    email = models.EmailField(blank=True)
    
    # Capacity and fees
    student_capacity = models.PositiveIntegerField(blank=True, null=True)
    current_enrollment = models.PositiveIntegerField(blank=True, null=True)
    annual_fees_range = models.JSONField(default=dict, blank=True)  # min and max fees
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'schools'
        indexes = [
            models.Index(fields=['school_type']),
            models.Index(fields=['latitude', 'longitude']),
            models.Index(fields=['overall_rating']),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.get_school_type_display()})"


class PointOfInterest(models.Model):
    """
    Points of Interest like hospitals, malls, parks, etc.
    """
    
    POI_CATEGORIES = (
        ('hospital', 'Hospital/Clinic'),
        ('mall', 'Shopping Mall'),
        ('market', 'Market'),
        ('park', 'Park/Garden'),
        ('gym', 'Gym/Fitness Center'),
        ('restaurant', 'Restaurant'),
        ('bank', 'Bank/ATM'),
        ('metro', 'Metro Station'),
        ('bus_stop', 'Bus Stop'),
        ('airport', 'Airport'),
        ('railway', 'Railway Station'),
        ('temple', 'Temple/Religious Place'),
        ('entertainment', 'Entertainment'),
        ('government', 'Government Office'),
        ('police', 'Police Station'),
        ('fire', 'Fire Station'),
        ('petrol', 'Petrol Pump'),
        ('other', 'Other'),
    )
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, db_index=True)
    category = models.CharField(max_length=20, choices=POI_CATEGORIES, db_index=True)
    
    # Location (simplified for SQLite development)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, db_index=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, db_index=True)
    address = models.TextField()
    neighborhood = models.ForeignKey(
        Neighborhood,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pois'
    )
    
    # Details
    description = models.TextField(blank=True)
    features = models.JSONField(default=list, blank=True)
    
    # Contact and timing
    phone_number = models.CharField(max_length=15, blank=True)
    website = models.URLField(blank=True)
    operating_hours = models.JSONField(default=dict, blank=True)
    
    # Ratings
    rating = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(5)],
        blank=True,
        null=True
    )
    reviews_count = models.PositiveIntegerField(default=0)
    
    # Metadata
    is_verified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'points_of_interest'
        indexes = [
            models.Index(fields=['category']),
            models.Index(fields=['latitude', 'longitude']),
            models.Index(fields=['rating']),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.get_category_display()})"


class TransportHub(models.Model):
    """
    Transport hubs like metro stations, bus stops, railway stations.
    """
    
    TRANSPORT_TYPES = (
        ('metro', 'Metro Station'),
        ('bus', 'Bus Stop'),
        ('railway', 'Railway Station'),
        ('airport', 'Airport'),
        ('taxi_stand', 'Taxi Stand'),
        ('auto_stand', 'Auto Stand'),
    )
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, db_index=True)
    transport_type = models.CharField(max_length=20, choices=TRANSPORT_TYPES, db_index=True)
    
    # Location (simplified for SQLite development)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, db_index=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, db_index=True)
    address = models.TextField()
    
    # Transport details
    lines_served = models.JSONField(default=list, blank=True)  # metro lines, bus routes, etc.
    connections = models.JSONField(default=list, blank=True)  # connecting transport options
    
    # Facilities
    facilities = models.JSONField(default=list, blank=True)
    accessibility_features = models.JSONField(default=list, blank=True)
    
    # Usage statistics
    daily_footfall = models.PositiveIntegerField(blank=True, null=True)
    peak_hours = models.JSONField(default=dict, blank=True)
    
    # Service information
    first_service = models.TimeField(blank=True, null=True)
    last_service = models.TimeField(blank=True, null=True)
    frequency = models.PositiveIntegerField(blank=True, null=True)  # minutes between services
    
    is_operational = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'transport_hubs'
        indexes = [
            models.Index(fields=['transport_type']),
            models.Index(fields=['latitude', 'longitude']),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.get_transport_type_display()})"


class NeighborhoodReview(models.Model):
    """
    User reviews for neighborhoods.
    """
    
    REVIEW_ASPECTS = (
        ('safety', 'Safety'),
        ('connectivity', 'Connectivity'),
        ('lifestyle', 'Lifestyle'),
        ('amenities', 'Amenities'),
        ('environment', 'Environment'),
        ('value_for_money', 'Value for Money'),
    )
    
    neighborhood = models.ForeignKey(Neighborhood, on_delete=models.CASCADE, related_name='reviews')
    user = models.ForeignKey('users.User', on_delete=models.CASCADE)
    
    # Overall rating
    overall_rating = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    
    # Aspect-wise ratings
    aspect_ratings = models.JSONField(default=dict, blank=True)
    
    # Review content
    title = models.CharField(max_length=200)
    review_text = models.TextField()
    pros = models.JSONField(default=list, blank=True)
    cons = models.JSONField(default=list, blank=True)
    
    # Verification
    is_verified = models.BooleanField(default=False)
    residency_verified = models.BooleanField(default=False)
    
    # Engagement
    helpful_votes = models.PositiveIntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'neighborhood_reviews'
        unique_together = ['neighborhood', 'user']
        indexes = [
            models.Index(fields=['neighborhood', 'overall_rating']),
            models.Index(fields=['user']),
        ]
    
    def __str__(self):
        return f"Review of {self.neighborhood.name} by {self.user.username}"


class PropertyVisitReview(models.Model):
    """
    Reviews from actual property visits.
    """
    
    property = models.ForeignKey('properties.Property', on_delete=models.CASCADE, related_name='visit_reviews')
    user = models.ForeignKey('users.User', on_delete=models.CASCADE)
    
    # Visit details
    visit_date = models.DateField()
    visit_duration = models.PositiveIntegerField(blank=True, null=True)  # in minutes
    visited_with_agent = models.BooleanField(default=False)
    
    # Ratings
    overall_rating = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    condition_rating = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        blank=True,
        null=True
    )
    location_rating = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        blank=True,
        null=True
    )
    
    # Review content
    title = models.CharField(max_length=200)
    review_text = models.TextField()
    pros = models.JSONField(default=list, blank=True)
    cons = models.JSONField(default=list, blank=True)
    
    # Property condition details
    actual_condition = models.TextField(blank=True)
    differences_from_listing = models.TextField(blank=True)
    
    # Recommendations
    would_recommend = models.BooleanField(default=True)
    target_audience = models.CharField(max_length=200, blank=True)
    
    # Verification
    is_verified = models.BooleanField(default=False)
    visit_proof = models.FileField(upload_to='visit_proofs/', blank=True, null=True)
    
    # Engagement
    helpful_votes = models.PositiveIntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'property_visit_reviews'
        unique_together = ['property', 'user', 'visit_date']
        indexes = [
            models.Index(fields=['property', 'overall_rating']),
            models.Index(fields=['user']),
            models.Index(fields=['visit_date']),
        ]
    
    def __str__(self):
        return f"Visit review of {self.property.title} by {self.user.username}"


class CommuteRoute(models.Model):
    """
    Commute routes and travel times from properties to important locations.
    """
    
    TRANSPORT_MODES = (
        ('driving', 'Driving'),
        ('public_transport', 'Public Transport'),
        ('walking', 'Walking'),
        ('cycling', 'Cycling'),
        ('metro', 'Metro'),
        ('bus', 'Bus'),
    )
    
    # From location (simplified for SQLite development)
    from_latitude = models.DecimalField(max_digits=9, decimal_places=6)
    from_longitude = models.DecimalField(max_digits=9, decimal_places=6)
    # To location (simplified for SQLite development)
    to_latitude = models.DecimalField(max_digits=9, decimal_places=6)
    to_longitude = models.DecimalField(max_digits=9, decimal_places=6)
    to_location_name = models.CharField(max_length=200)
    
    transport_mode = models.CharField(max_length=20, choices=TRANSPORT_MODES)
    
    # Route details
    distance_km = models.DecimalField(max_digits=8, decimal_places=2)
    duration_minutes = models.PositiveIntegerField()  # average duration
    duration_peak = models.PositiveIntegerField(blank=True, null=True)  # peak hours
    duration_off_peak = models.PositiveIntegerField(blank=True, null=True)  # off-peak hours
    
    # Cost information
    cost_one_way = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
    cost_monthly = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    
    # Route information (simplified for SQLite development)
    route_polyline_data = models.JSONField(default=dict, blank=True, help_text="Route polyline as JSON")
    intermediate_stops = models.JSONField(default=list, blank=True)
    
    # Frequency and reliability
    service_frequency = models.PositiveIntegerField(blank=True, null=True)  # services per hour
    reliability_score = models.DecimalField(max_digits=3, decimal_places=2, blank=True, null=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'commute_routes'
        indexes = [
            models.Index(fields=['from_latitude', 'from_longitude']),
            models.Index(fields=['to_latitude', 'to_longitude']),
            models.Index(fields=['transport_mode']),
            models.Index(fields=['duration_minutes']),
        ]
    
    def __str__(self):
        return f"{self.to_location_name} via {self.get_transport_mode_display()} - {self.duration_minutes}min"
