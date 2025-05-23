"""
Admin configuration for search app.
"""

from django.contrib import admin
from .models import (
    SavedSearch, SearchAnalytics, PopularSearch, 
    SearchSuggestion, LocationTrend
)


@admin.register(SavedSearch)
class SavedSearchAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'user', 'search_type', 'location', 'search_count', 
        'is_active', 'created_at'
    ]
    list_filter = [
        'search_type', 'is_active', 'email_notifications', 
        'notification_frequency', 'created_at'
    ]
    search_fields = ['name', 'user__username', 'user__email', 'search_query', 'location']
    readonly_fields = ['id', 'search_count', 'last_searched', 'created_at', 'updated_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('user', 'name', 'search_type', 'search_query')
        }),
        ('Search Filters', {
            'fields': ('search_filters',),
            'classes': ('collapse',)
        }),
        ('Location Settings', {
            'fields': ('location', 'latitude', 'longitude', 'radius')
        }),
        ('Notifications', {
            'fields': ('email_notifications', 'notification_frequency', 'last_notification_sent')
        }),
        ('Statistics', {
            'fields': ('search_count', 'last_searched', 'total_results_found'),
            'classes': ('collapse',)
        }),
        ('Status', {
            'fields': ('is_active', 'created_at', 'updated_at')
        })
    )


@admin.register(SearchAnalytics)
class SearchAnalyticsAdmin(admin.ModelAdmin):
    list_display = [
        'user', 'search_type', 'search_query', 'results_count', 
        'device_type', 'created_at'
    ]
    list_filter = [
        'search_type', 'device_type', 'inquiry_sent', 'contact_made', 
        'saved_search_created', 'created_at'
    ]
    search_fields = ['user__username', 'search_query', 'search_location', 'ip_address']
    readonly_fields = ['id', 'created_at']
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('User Information', {
            'fields': ('user', 'session_id', 'ip_address', 'user_agent', 'device_type')
        }),
        ('Search Details', {
            'fields': ('search_type', 'search_query', 'search_filters', 'search_location')
        }),
        ('Results & Engagement', {
            'fields': (
                'results_count', 'clicked_results', 'search_duration',
                'time_on_results_page', 'pages_viewed'
            )
        }),
        ('User Actions', {
            'fields': (
                'properties_viewed', 'properties_liked', 'properties_shared',
                'inquiry_sent', 'contact_made', 'saved_search_created'
            ),
            'classes': ('collapse',)
        }),
        ('Location Data', {
            'fields': ('user_latitude', 'user_longitude'),
            'classes': ('collapse',)
        })
    )


@admin.register(PopularSearch)
class PopularSearchAdmin(admin.ModelAdmin):
    list_display = [
        'search_term', 'search_type', 'search_count', 'unique_users_count',
        'trending_score', 'is_trending', 'last_searched'
    ]
    list_filter = ['search_type', 'is_trending', 'last_searched']
    search_fields = ['search_term']
    readonly_fields = [
        'search_count', 'unique_users_count', 'this_week_count', 
        'this_month_count', 'trending_score', 'first_searched', 
        'last_searched', 'updated_at'
    ]
    ordering = ['-trending_score', '-search_count']
    
    fieldsets = (
        ('Search Information', {
            'fields': ('search_term', 'search_type')
        }),
        ('Popularity Metrics', {
            'fields': (
                'search_count', 'unique_users_count', 'this_week_count', 
                'this_month_count', 'trending_score', 'is_trending'
            )
        }),
        ('Associated Data', {
            'fields': ('associated_locations', 'average_price_range'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('first_searched', 'last_searched', 'updated_at'),
            'classes': ('collapse',)
        })
    )


@admin.register(SearchSuggestion)
class SearchSuggestionAdmin(admin.ModelAdmin):
    list_display = [
        'text', 'suggestion_type', 'popularity_score', 'click_count',
        'search_count', 'is_active', 'is_verified'
    ]
    list_filter = ['suggestion_type', 'is_active', 'is_verified', 'created_at']
    search_fields = ['text']
    readonly_fields = ['popularity_score', 'click_count', 'search_count', 'created_at', 'updated_at']
    ordering = ['-popularity_score', '-click_count']
    
    fieldsets = (
        ('Suggestion Details', {
            'fields': ('text', 'suggestion_type', 'metadata')
        }),
        ('Popularity Metrics', {
            'fields': ('popularity_score', 'click_count', 'search_count')
        }),
        ('Associated Data', {
            'fields': ('associated_locations',),
            'classes': ('collapse',)
        }),
        ('Status', {
            'fields': ('is_active', 'is_verified', 'created_at', 'updated_at')
        })
    )
    
    actions = ['mark_as_verified', 'mark_as_unverified', 'activate', 'deactivate']
    
    def mark_as_verified(self, request, queryset):
        queryset.update(is_verified=True)
        self.message_user(request, f"{queryset.count()} suggestions marked as verified.")
    mark_as_verified.short_description = "Mark selected suggestions as verified"
    
    def mark_as_unverified(self, request, queryset):
        queryset.update(is_verified=False)
        self.message_user(request, f"{queryset.count()} suggestions marked as unverified.")
    mark_as_unverified.short_description = "Mark selected suggestions as unverified"
    
    def activate(self, request, queryset):
        queryset.update(is_active=True)
        self.message_user(request, f"{queryset.count()} suggestions activated.")
    activate.short_description = "Activate selected suggestions"
    
    def deactivate(self, request, queryset):
        queryset.update(is_active=False)
        self.message_user(request, f"{queryset.count()} suggestions deactivated.")
    deactivate.short_description = "Deactivate selected suggestions"


@admin.register(LocationTrend)
class LocationTrendAdmin(admin.ModelAdmin):
    list_display = [
        'location_name', 'city', 'state', 'average_price', 'price_trend',
        'search_volume', 'trend_score', 'is_trending_up', 'is_hot_location',
        'data_date'
    ]
    list_filter = [
        'city', 'state', 'is_trending_up', 'is_hot_location', 'data_date'
    ]
    search_fields = ['location_name', 'city', 'state']
    readonly_fields = [
        'trend_score', 'is_trending_up', 'is_hot_location', 'last_updated'
    ]
    date_hierarchy = 'data_date'
    ordering = ['-trend_score', '-search_volume']
    
    fieldsets = (
        ('Location Information', {
            'fields': ('location_name', 'city', 'state', 'latitude', 'longitude')
        }),
        ('Market Data', {
            'fields': ('average_price', 'price_per_sqft', 'price_trend')
        }),
        ('Activity Metrics', {
            'fields': ('search_volume', 'property_count', 'active_listings')
        }),
        ('Trend Analysis', {
            'fields': ('trend_score', 'is_trending_up', 'is_hot_location')
        }),
        ('Timestamps', {
            'fields': ('data_date', 'last_updated')
        })
    )
    
    actions = ['mark_as_hot', 'unmark_as_hot']
    
    def mark_as_hot(self, request, queryset):
        queryset.update(is_hot_location=True)
        self.message_user(request, f"{queryset.count()} locations marked as hot.")
    mark_as_hot.short_description = "Mark selected locations as hot"
    
    def unmark_as_hot(self, request, queryset):
        queryset.update(is_hot_location=False)
        self.message_user(request, f"{queryset.count()} locations unmarked as hot.")
    unmark_as_hot.short_description = "Unmark selected locations as hot"
