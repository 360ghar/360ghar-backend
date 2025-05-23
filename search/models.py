"""
Search models for 360ghar platform.
Advanced search functionality with analytics and saved searches.
"""

import uuid
from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()


class SavedSearch(models.Model):
    """
    User's saved property searches.
    """
    
    SEARCH_TYPES = (
        ('property', 'Property Search'),
        ('agent', 'Agent Search'),
        ('location', 'Location Search'),
    )
    
    NOTIFICATION_FREQUENCY = (
        ('instant', 'Instant'),
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
        ('disabled', 'Disabled'),
    )
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='saved_searches')
    
    # Search details
    name = models.CharField(max_length=200)
    search_type = models.CharField(max_length=20, choices=SEARCH_TYPES, default='property')
    search_query = models.TextField(blank=True)
    search_filters = models.JSONField(default=dict)
    
    # Location data
    location = models.CharField(max_length=200, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    radius = models.PositiveIntegerField(default=10)  # in kilometers
    
    # Notification settings
    email_notifications = models.BooleanField(default=True)
    notification_frequency = models.CharField(
        max_length=20, 
        choices=NOTIFICATION_FREQUENCY, 
        default='daily'
    )
    last_notification_sent = models.DateTimeField(null=True, blank=True)
    
    # Search statistics
    search_count = models.PositiveIntegerField(default=0)
    last_searched = models.DateTimeField(null=True, blank=True)
    total_results_found = models.PositiveIntegerField(default=0)
    
    # Settings
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'saved_searches'
        indexes = [
            models.Index(fields=['user', 'is_active']),
            models.Index(fields=['search_type']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.name}"
    
    def execute_search(self):
        """Execute the saved search and return results."""
        # This will be implemented in the search service
        from .services import SearchService
        service = SearchService()
        return service.execute_saved_search(self)
    
    def increment_search_count(self):
        """Increment search count and update last searched time."""
        self.search_count += 1
        self.last_searched = timezone.now()
        self.save(update_fields=['search_count', 'last_searched'])


class SearchAnalytics(models.Model):
    """
    Analytics for search queries and user behavior.
    """
    
    SEARCH_TYPES = SavedSearch.SEARCH_TYPES
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='search_analytics'
    )
    session_id = models.CharField(max_length=50, blank=True)
    
    # Search details
    search_type = models.CharField(max_length=20, choices=SEARCH_TYPES)
    search_query = models.TextField(blank=True)
    search_filters = models.JSONField(default=dict)
    
    # Results data
    results_count = models.PositiveIntegerField(default=0)
    clicked_results = models.JSONField(default=list)  # List of property IDs clicked
    search_duration = models.PositiveIntegerField(null=True, blank=True)  # in seconds
    
    # Location data
    search_location = models.CharField(max_length=200, blank=True)
    user_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    user_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    
    # Technical data
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    device_type = models.CharField(max_length=20, blank=True)
    
    # Engagement metrics
    time_on_results_page = models.PositiveIntegerField(null=True, blank=True)  # in seconds
    pages_viewed = models.PositiveIntegerField(default=1)
    properties_viewed = models.JSONField(default=list)
    properties_liked = models.JSONField(default=list)
    properties_shared = models.JSONField(default=list)
    
    # Success metrics
    inquiry_sent = models.BooleanField(default=False)
    contact_made = models.BooleanField(default=False)
    saved_search_created = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'search_analytics'
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['search_type']),
            models.Index(fields=['created_at']),
            models.Index(fields=['session_id']),
        ]
    
    def __str__(self):
        username = self.user.username if self.user else 'Anonymous'
        return f"{username} - {self.search_type} search"


class PopularSearch(models.Model):
    """
    Track popular search terms and trending searches.
    """
    
    SEARCH_TYPES = SavedSearch.SEARCH_TYPES
    
    search_term = models.CharField(max_length=200, unique=True)
    search_type = models.CharField(max_length=20, choices=SEARCH_TYPES, default='property')
    
    # Popularity metrics
    search_count = models.PositiveIntegerField(default=1)
    unique_users_count = models.PositiveIntegerField(default=1)
    this_week_count = models.PositiveIntegerField(default=0)
    this_month_count = models.PositiveIntegerField(default=0)
    
    # Trend data
    trending_score = models.FloatField(default=0.0)
    is_trending = models.BooleanField(default=False)
    
    # Associated locations
    associated_locations = models.JSONField(default=list)
    average_price_range = models.JSONField(default=dict)
    
    first_searched = models.DateTimeField(auto_now_add=True)
    last_searched = models.DateTimeField(auto_now=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'popular_searches'
        indexes = [
            models.Index(fields=['search_type', 'trending_score']),
            models.Index(fields=['is_trending']),
            models.Index(fields=['search_count']),
        ]
        ordering = ['-trending_score', '-search_count']
    
    def __str__(self):
        return f"{self.search_term} ({self.search_count} searches)"
    
    @classmethod
    def increment_search(cls, search_term, search_type='property', user=None):
        """Increment search count for a term."""
        popular_search, created = cls.objects.get_or_create(
            search_term=search_term.lower().strip(),
            search_type=search_type,
            defaults={'search_count': 0, 'unique_users_count': 0}
        )
        
        popular_search.search_count += 1
        popular_search.last_searched = timezone.now()
        
        # Track unique users (simplified - in production would use more sophisticated tracking)
        if user and user.is_authenticated:
            # This is a simple approximation - in production you'd track unique users more accurately
            popular_search.unique_users_count = max(
                popular_search.unique_users_count, 
                popular_search.search_count // 10
            )
        
        # Update weekly/monthly counts (simplified)
        now = timezone.now()
        if not popular_search.updated_at or (now - popular_search.updated_at).days >= 1:
            # Reset weekly/monthly counters (this is simplified logic)
            if (now - popular_search.first_searched).days <= 7:
                popular_search.this_week_count += 1
            if (now - popular_search.first_searched).days <= 30:
                popular_search.this_month_count += 1
        
        # Calculate trending score (simplified algorithm)
        days_since_first = max((now - popular_search.first_searched).days, 1)
        popular_search.trending_score = (
            popular_search.this_week_count * 10 + 
            popular_search.this_month_count * 3 + 
            popular_search.search_count
        ) / days_since_first
        
        popular_search.is_trending = popular_search.trending_score > 5.0
        popular_search.save()
        
        return popular_search


class SearchSuggestion(models.Model):
    """
    Auto-complete suggestions for search queries.
    """
    
    SUGGESTION_TYPES = (
        ('location', 'Location'),
        ('property_type', 'Property Type'),
        ('amenity', 'Amenity'),
        ('landmark', 'Landmark'),
        ('builder', 'Builder'),
        ('general', 'General'),
    )
    
    text = models.CharField(max_length=200, unique=True)
    suggestion_type = models.CharField(max_length=20, choices=SUGGESTION_TYPES)
    
    # Relevance and popularity
    popularity_score = models.FloatField(default=0.0)
    click_count = models.PositiveIntegerField(default=0)
    search_count = models.PositiveIntegerField(default=0)
    
    # Associated data
    associated_locations = models.JSONField(default=list)
    metadata = models.JSONField(default=dict)
    
    # Status
    is_active = models.BooleanField(default=True)
    is_verified = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'search_suggestions'
        indexes = [
            models.Index(fields=['suggestion_type', 'popularity_score']),
            models.Index(fields=['is_active', 'is_verified']),
            models.Index(fields=['text']),
        ]
        ordering = ['-popularity_score', '-click_count']
    
    def __str__(self):
        return f"{self.text} ({self.suggestion_type})"
    
    def increment_usage(self, action='search'):
        """Increment usage statistics."""
        if action == 'search':
            self.search_count += 1
        elif action == 'click':
            self.click_count += 1
        
        # Update popularity score
        self.popularity_score = (self.search_count * 2 + self.click_count * 5) / 7
        self.save(update_fields=['search_count', 'click_count', 'popularity_score'])


class LocationTrend(models.Model):
    """
    Track trending locations and price movements.
    """
    
    location_name = models.CharField(max_length=200)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    
    # Geographic data
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    
    # Market data
    average_price = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    price_per_sqft = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    price_trend = models.FloatField(default=0.0)  # Percentage change
    
    # Activity metrics
    search_volume = models.PositiveIntegerField(default=0)
    property_count = models.PositiveIntegerField(default=0)
    active_listings = models.PositiveIntegerField(default=0)
    
    # Trend data
    trend_score = models.FloatField(default=0.0)
    is_trending_up = models.BooleanField(default=False)
    is_hot_location = models.BooleanField(default=False)
    
    # Time-based data
    data_date = models.DateField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'location_trends'
        unique_together = ['location_name', 'city', 'data_date']
        indexes = [
            models.Index(fields=['city', 'trend_score']),
            models.Index(fields=['is_trending_up']),
            models.Index(fields=['data_date']),
        ]
        ordering = ['-trend_score', '-search_volume']
    
    def __str__(self):
        return f"{self.location_name}, {self.city}"
