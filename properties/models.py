"""
Property models for 360ghar application.
"""

from django.contrib.gis.db import models
from django.contrib.postgres.fields import ArrayField
from django.core.validators import MinValueValidator, MaxValueValidator
from django.urls import reverse
from django.utils.text import slugify
import uuid


class Property(models.Model):
    """
    Main property model with all essential information.
    """
    
    PROPERTY_TYPES = (
        ('apartment', 'Apartment'),
        ('house', 'Independent House'),
        ('villa', 'Villa'),
        ('studio', 'Studio Apartment'),
        ('penthouse', 'Penthouse'),
        ('duplex', 'Duplex'),
        ('commercial', 'Commercial Space'),
        ('office', 'Office Space'),
        ('retail', 'Retail Space'),
        ('warehouse', 'Warehouse'),
        ('land', 'Plot/Land'),
        ('farmhouse', 'Farmhouse'),
    )
    
    STATUS_CHOICES = (
        ('available', 'Available'),
        ('sold', 'Sold'),
        ('rented', 'Rented'),
        ('under_offer', 'Under Offer'),
        ('off_market', 'Off Market'),
        ('coming_soon', 'Coming Soon'),
    )
    
    LISTING_TYPES = (
        ('sale', 'For Sale'),
        ('rent', 'For Rent'),
        ('pg', 'Paying Guest'),
        ('lease', 'Lease'),
    )
    
    FURNISHING_STATUS = (
        ('unfurnished', 'Unfurnished'),
        ('semi_furnished', 'Semi Furnished'),
        ('fully_furnished', 'Fully Furnished'),
    )
    
    PROPERTY_AGE = (
        ('under_construction', 'Under Construction'),
        ('ready_to_move', 'Ready to Move'),
        ('1-2_years', '1-2 Years'),
        ('3-5_years', '3-5 Years'),
        ('5-10_years', '5-10 Years'),
        ('10+_years', '10+ Years'),
    )
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Basic Information
    title = models.CharField(max_length=200, db_index=True)
    slug = models.SlugField(max_length=250, unique=True, blank=True)
    description = models.TextField()
    property_type = models.CharField(max_length=50, choices=PROPERTY_TYPES, db_index=True)
    listing_type = models.CharField(max_length=20, choices=LISTING_TYPES, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='available', db_index=True)
    
    # Owner/Agent Information
    owner = models.ForeignKey('users.User', on_delete=models.CASCADE, related_name='owned_properties')
    agent = models.ForeignKey(
        'users.User', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='managed_properties'
    )
    
    # Location Information (simplified for SQLite development)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, db_index=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, db_index=True)
    address = models.TextField()
    locality = models.CharField(max_length=100, db_index=True)
    city = models.CharField(max_length=100, db_index=True)
    state = models.CharField(max_length=100, db_index=True)
    country = models.CharField(max_length=100, default='India')
    pincode = models.CharField(max_length=10, db_index=True)
    
    # Pricing Information
    price = models.DecimalField(max_digits=15, decimal_places=2, db_index=True)
    price_per_sqft = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    maintenance_charges = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    security_deposit = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    
    # Property Specifications
    total_area = models.DecimalField(max_digits=10, decimal_places=2)  # in sq ft
    carpet_area = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    built_up_area = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    super_area = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    
    bedrooms = models.PositiveIntegerField(validators=[MaxValueValidator(20)])
    bathrooms = models.PositiveIntegerField(validators=[MaxValueValidator(20)])
    balconies = models.PositiveIntegerField(default=0, validators=[MaxValueValidator(10)])
    
    # Building Information
    total_floors = models.PositiveIntegerField(blank=True, null=True)
    floor_number = models.PositiveIntegerField(blank=True, null=True)
    year_built = models.PositiveIntegerField(blank=True, null=True)
    property_age = models.CharField(max_length=50, choices=PROPERTY_AGE, blank=True)
    
    # Additional Details
    furnishing_status = models.CharField(max_length=20, choices=FURNISHING_STATUS, blank=True)
    parking_spaces = models.PositiveIntegerField(default=0)
    
    # Features and Amenities (JSON fields for flexibility)
    features = models.JSONField(default=dict, blank=True, help_text="Property features like AC, Lift, etc.")
    amenities = models.JSONField(default=list, blank=True, help_text="Building/Society amenities")
    
    # Smart Home Features
    smart_home_features = models.JSONField(default=list, blank=True)
    
    # Accessibility Features
    accessibility_features = models.JSONField(default=list, blank=True)
    
    # Energy Efficiency
    energy_rating = models.CharField(max_length=10, blank=True, null=True)
    solar_panels = models.BooleanField(default=False)
    
    # Legal Information
    rera_id = models.CharField(max_length=50, blank=True, null=True)
    legal_clearance = models.JSONField(default=dict, blank=True)
    
    # Verification and Quality
    is_verified = models.BooleanField(default=False)
    verification_date = models.DateTimeField(blank=True, null=True)
    verified_by = models.ForeignKey(
        'users.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_properties'
    )
    
    # Performance Metrics
    views_count = models.PositiveIntegerField(default=0)
    likes_count = models.PositiveIntegerField(default=0)
    inquiries_count = models.PositiveIntegerField(default=0)
    
    # SEO and Social
    meta_title = models.CharField(max_length=200, blank=True)
    meta_description = models.TextField(max_length=500, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    featured_until = models.DateTimeField(blank=True, null=True)
    
    # Status flags
    is_featured = models.BooleanField(default=False)
    is_premium = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        db_table = 'properties'
        indexes = [
            models.Index(fields=['property_type', 'listing_type']),
            models.Index(fields=['city', 'locality']),
            models.Index(fields=['price']),
            models.Index(fields=['bedrooms', 'bathrooms']),
            models.Index(fields=['latitude', 'longitude']),
            models.Index(fields=['status', 'is_active']),
            models.Index(fields=['-created_at']),
        ]
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.title} - {self.locality}, {self.city}"
    
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self.generate_unique_slug()
        
        # Calculate price per sqft
        if self.total_area and self.price:
            self.price_per_sqft = self.price / self.total_area
            
        super().save(*args, **kwargs)
    
    def generate_unique_slug(self):
        """Generate a unique slug for the property."""
        base_slug = slugify(f"{self.title}-{self.locality}-{self.city}")
        slug = base_slug
        counter = 1
        
        while Property.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1
            
        return slug
    
    def get_absolute_url(self):
        return reverse('properties:detail', kwargs={'slug': self.slug})
    
    @property
    def price_formatted(self):
        """Return formatted price in Indian currency format."""
        if self.price >= 10000000:  # 1 Crore
            return f"₹ {self.price / 10000000:.2f} Cr"
        elif self.price >= 100000:  # 1 Lakh
            return f"₹ {self.price / 100000:.2f} L"
        else:
            return f"₹ {self.price:,.0f}"


class PropertyMedia(models.Model):
    """
    Media files associated with properties.
    """
    
    MEDIA_TYPES = (
        ('photo', 'Photo'),
        ('video', 'Video'),
        ('360_tour', '360° Tour'),
        ('floor_plan', 'Floor Plan'),
        ('document', 'Document'),
        ('virtual_tour', 'Virtual Tour'),
    )
    
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='media')
    media_type = models.CharField(max_length=20, choices=MEDIA_TYPES, db_index=True)
    file = models.FileField(upload_to='property_media/')
    thumbnail = models.ImageField(upload_to='property_thumbnails/', blank=True, null=True)
    
    title = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    alt_text = models.CharField(max_length=200, blank=True)
    
    # Metadata
    file_size = models.PositiveIntegerField(blank=True, null=True)
    dimensions = models.JSONField(default=dict, blank=True)  # width, height for images/videos
    duration = models.PositiveIntegerField(blank=True, null=True)  # for videos in seconds
    
    # Ordering and flags
    order = models.PositiveIntegerField(default=0)
    is_primary = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'property_media'
        ordering = ['order', 'created_at']
        indexes = [
            models.Index(fields=['property', 'media_type']),
            models.Index(fields=['is_primary']),
        ]
    
    def __str__(self):
        return f"{self.property.title} - {self.get_media_type_display()}"


class BuildingMaterial(models.Model):
    """
    Building materials and construction quality information.
    """
    
    COMPONENT_TYPES = (
        ('foundation', 'Foundation'),
        ('structure', 'Structure'),
        ('walls', 'Walls'),
        ('roof', 'Roof'),
        ('flooring', 'Flooring'),
        ('doors', 'Doors'),
        ('windows', 'Windows'),
        ('plumbing', 'Plumbing'),
        ('electrical', 'Electrical'),
        ('paint', 'Paint/Finish'),
    )
    
    QUALITY_RATINGS = (
        (1, 'Poor'),
        (2, 'Below Average'),
        (3, 'Average'),
        (4, 'Good'),
        (5, 'Excellent'),
    )
    
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='building_materials')
    component = models.CharField(max_length=50, choices=COMPONENT_TYPES)
    material_type = models.CharField(max_length=100)
    brand = models.CharField(max_length=100, blank=True)
    quality_score = models.PositiveIntegerField(choices=QUALITY_RATINGS)
    
    installation_date = models.DateField(blank=True, null=True)
    warranty_period = models.PositiveIntegerField(blank=True, null=True)  # in months
    maintenance_notes = models.TextField(blank=True)
    
    last_updated = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'building_materials'
        unique_together = ['property', 'component']
    
    def __str__(self):
        return f"{self.property.title} - {self.get_component_display()}"


class Appliance(models.Model):
    """
    Appliances and fixtures in the property.
    """
    
    APPLIANCE_TYPES = (
        ('ac', 'Air Conditioner'),
        ('refrigerator', 'Refrigerator'),
        ('washing_machine', 'Washing Machine'),
        ('microwave', 'Microwave'),
        ('dishwasher', 'Dishwasher'),
        ('water_heater', 'Water Heater'),
        ('tv', 'Television'),
        ('fan', 'Ceiling Fan'),
        ('light', 'Light Fixture'),
        ('other', 'Other'),
    )
    
    CONDITIONS = (
        ('new', 'New'),
        ('excellent', 'Excellent'),
        ('good', 'Good'),
        ('fair', 'Fair'),
        ('poor', 'Poor'),
    )
    
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='appliances')
    appliance_type = models.CharField(max_length=50, choices=APPLIANCE_TYPES)
    brand = models.CharField(max_length=100, blank=True)
    model = models.CharField(max_length=100, blank=True)
    
    age_years = models.PositiveIntegerField(blank=True, null=True)
    condition = models.CharField(max_length=20, choices=CONDITIONS, blank=True)
    warranty_status = models.BooleanField(default=False)
    warranty_expires = models.DateField(blank=True, null=True)
    
    specifications = models.JSONField(default=dict, blank=True)
    energy_rating = models.CharField(max_length=10, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'property_appliances'
    
    def __str__(self):
        return f"{self.property.title} - {self.get_appliance_type_display()}"


class PropertyLike(models.Model):
    """
    User likes/favorites for properties.
    """
    
    user = models.ForeignKey('users.User', on_delete=models.CASCADE)
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='likes')
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'property_likes'
        unique_together = ['user', 'property']
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['property']),
        ]
    
    def __str__(self):
        return f"{self.user.username} likes {self.property.title}"


class PropertyView(models.Model):
    """
    Track property views for analytics.
    """
    
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='property_views')
    user = models.ForeignKey('users.User', on_delete=models.CASCADE, null=True, blank=True)
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField(blank=True)
    referrer = models.URLField(blank=True, null=True)
    
    # Session information
    session_key = models.CharField(max_length=40, blank=True)
    device_info = models.JSONField(default=dict, blank=True)
    
    # Time tracking
    viewed_at = models.DateTimeField(auto_now_add=True)
    time_spent = models.PositiveIntegerField(default=0)  # in seconds
    
    # Interaction data
    interactions = models.JSONField(default=dict, blank=True)  # clicks, scrolls, etc.
    
    class Meta:
        db_table = 'property_views'
        indexes = [
            models.Index(fields=['property']),
            models.Index(fields=['user']),
            models.Index(fields=['viewed_at']),
        ]
    
    def __str__(self):
        user_display = self.user.username if self.user else "Anonymous"
        return f"{user_display} viewed {self.property.title}"


class PropertyInquiry(models.Model):
    """
    Inquiries made by users for properties.
    """
    
    INQUIRY_TYPES = (
        ('general', 'General Inquiry'),
        ('visit', 'Schedule Visit'),
        ('price', 'Price Negotiation'),
        ('finance', 'Financing Options'),
        ('legal', 'Legal Documentation'),
    )
    
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='inquiries')
    user = models.ForeignKey('users.User', on_delete=models.CASCADE)
    inquiry_type = models.CharField(max_length=20, choices=INQUIRY_TYPES, default='general')
    
    message = models.TextField()
    contact_phone = models.CharField(max_length=15, blank=True)
    preferred_contact_time = models.CharField(max_length=100, blank=True)
    
    # Response tracking
    is_responded = models.BooleanField(default=False)
    response_message = models.TextField(blank=True)
    responded_at = models.DateTimeField(blank=True, null=True)
    responded_by = models.ForeignKey(
        'users.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='responded_inquiries'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'property_inquiries'
        indexes = [
            models.Index(fields=['property']),
            models.Index(fields=['user']),
            models.Index(fields=['is_responded']),
        ]
    
    def __str__(self):
        return f"Inquiry for {self.property.title} by {self.user.username}"
