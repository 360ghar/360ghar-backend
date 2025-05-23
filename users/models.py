"""
User models for 360ghar application.
"""

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.core.validators import RegexValidator
from django.utils import timezone
import uuid


class User(AbstractUser):
    """
    Custom user model extending Django's AbstractUser.
    """
    
    USER_TYPES = (
        ('buyer', 'Buyer'),
        ('seller', 'Seller'),
        ('agent', 'Real Estate Agent'),
        ('admin', 'Administrator'),
        ('developer', 'Property Developer'),
    )
    
    VERIFICATION_STATUS = (
        ('pending', 'Pending'),
        ('verified', 'Verified'),
        ('rejected', 'Rejected'),
    )
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_type = models.CharField(max_length=20, choices=USER_TYPES, default='buyer')
    phone_number = models.CharField(
        max_length=15,
        validators=[RegexValidator(r'^\+?1?\d{9,15}$')],
        blank=True,
        null=True
    )
    profile_picture = models.ImageField(upload_to='profile_pictures/', blank=True, null=True)
    date_of_birth = models.DateField(blank=True, null=True)
    
    # Verification fields
    verification_status = models.CharField(
        max_length=20, 
        choices=VERIFICATION_STATUS, 
        default='pending'
    )
    verification_documents = models.JSONField(default=dict, blank=True)
    verified_at = models.DateTimeField(blank=True, null=True)
    verified_by = models.ForeignKey(
        'self', 
        on_delete=models.SET_NULL, 
        blank=True, 
        null=True,
        related_name='verified_users'
    )
    
    # Profile data
    profile_data = models.JSONField(default=dict, blank=True)
    preferences = models.JSONField(default=dict, blank=True)
    
    # Location (simplified for SQLite development)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    address = models.TextField(blank=True, null=True)
    
    # Agent specific fields
    license_number = models.CharField(max_length=50, blank=True, null=True)
    agency_name = models.CharField(max_length=200, blank=True, null=True)
    experience_years = models.PositiveIntegerField(blank=True, null=True)
    specializations = models.JSONField(default=list, blank=True)
    
    # Business hours for agents
    business_hours = models.JSONField(default=dict, blank=True)
    
    # Social media links
    social_links = models.JSONField(default=dict, blank=True)
    
    # Privacy settings
    privacy_settings = models.JSONField(default=dict, blank=True)
    
    # Marketing preferences
    marketing_consent = models.BooleanField(default=False)
    email_notifications = models.BooleanField(default=True)
    sms_notifications = models.BooleanField(default=False)
    push_notifications = models.BooleanField(default=True)
    
    # Activity tracking
    last_active = models.DateTimeField(auto_now=True)
    signup_source = models.CharField(max_length=50, blank=True, null=True)
    referral_code = models.CharField(max_length=20, unique=True, blank=True, null=True)
    referred_by = models.ForeignKey(
        'self', 
        on_delete=models.SET_NULL, 
        blank=True, 
        null=True,
        related_name='referrals'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'users'
        indexes = [
            models.Index(fields=['user_type']),
            models.Index(fields=['verification_status']),
            models.Index(fields=['latitude', 'longitude']),
            models.Index(fields=['last_active']),
        ]
    
    def __str__(self):
        return f"{self.username} ({self.get_user_type_display()})"
    
    def save(self, *args, **kwargs):
        # Generate referral code if not exists
        if not self.referral_code:
            self.referral_code = self.generate_referral_code()
        super().save(*args, **kwargs)
    
    def generate_referral_code(self):
        """Generate a unique referral code."""
        import random
        import string
        while True:
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
            if not User.objects.filter(referral_code=code).exists():
                return code
    
    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()
    
    @property
    def is_verified(self):
        return self.verification_status == 'verified'
    
    @property
    def is_agent(self):
        return self.user_type == 'agent'
    
    @property
    def is_seller(self):
        return self.user_type == 'seller'
    
    @property
    def is_buyer(self):
        return self.user_type == 'buyer'


class UserPreference(models.Model):
    """
    User preferences for property search and notifications.
    """
    
    PROPERTY_TYPES = (
        ('apartment', 'Apartment'),
        ('house', 'House'),
        ('villa', 'Villa'),
        ('studio', 'Studio'),
        ('penthouse', 'Penthouse'),
        ('commercial', 'Commercial'),
        ('land', 'Land'),
    )
    
    BUDGET_RANGES = (
        ('0-1000000', '0 - 10 Lakhs'),
        ('1000000-2500000', '10 - 25 Lakhs'),
        ('2500000-5000000', '25 - 50 Lakhs'),
        ('5000000-10000000', '50 Lakhs - 1 Crore'),
        ('10000000-25000000', '1 - 2.5 Crores'),
        ('25000000+', '2.5+ Crores'),
    )
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='search_preferences')
    
    # Property preferences
    preferred_property_types = models.JSONField(default=list, blank=True)
    budget_range = models.CharField(max_length=50, choices=BUDGET_RANGES, blank=True)
    min_bedrooms = models.PositiveIntegerField(blank=True, null=True)
    max_bedrooms = models.PositiveIntegerField(blank=True, null=True)
    min_bathrooms = models.PositiveIntegerField(blank=True, null=True)
    
    # Location preferences
    preferred_locations = models.JSONField(default=list, blank=True)
    max_commute_time = models.PositiveIntegerField(blank=True, null=True)  # in minutes
    
    # Amenity preferences
    preferred_amenities = models.JSONField(default=list, blank=True)
    
    # Search radius preference
    search_radius = models.PositiveIntegerField(default=10)  # in kilometers
    
    # Notification preferences
    instant_notifications = models.BooleanField(default=True)
    daily_digest = models.BooleanField(default=False)
    weekly_digest = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'user_preferences'
    
    def __str__(self):
        return f"Preferences for {self.user.username}"


class UserActivity(models.Model):
    """
    Track user activities and engagement.
    """
    
    ACTIVITY_TYPES = (
        ('login', 'Login'),
        ('logout', 'Logout'),
        ('property_view', 'Property View'),
        ('property_like', 'Property Like'),
        ('property_share', 'Property Share'),
        ('search', 'Search'),
        ('contact_agent', 'Contact Agent'),
        ('schedule_visit', 'Schedule Visit'),
        ('profile_update', 'Profile Update'),
    )
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='activities')
    activity_type = models.CharField(max_length=50, choices=ACTIVITY_TYPES)
    description = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'user_activities'
        indexes = [
            models.Index(fields=['user', 'activity_type']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.get_activity_type_display()}"


class UserSession(models.Model):
    """
    Track user sessions for analytics.
    """
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sessions')
    session_key = models.CharField(max_length=40, unique=True)
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField(blank=True)
    device_info = models.JSONField(default=dict, blank=True)
    location_data = models.JSONField(default=dict, blank=True)
    
    login_time = models.DateTimeField(auto_now_add=True)
    logout_time = models.DateTimeField(blank=True, null=True)
    last_activity = models.DateTimeField(auto_now=True)
    
    is_active = models.BooleanField(default=True)
    
    class Meta:
        db_table = 'user_sessions'
        indexes = [
            models.Index(fields=['user', 'is_active']),
            models.Index(fields=['session_key']),
        ]
    
    @property
    def duration(self):
        """Calculate session duration."""
        if self.logout_time:
            return self.logout_time - self.login_time
        return timezone.now() - self.login_time
    
    def __str__(self):
        return f"{self.user.username} - {self.login_time}"
