"""
URL patterns for analytics app.
"""

from django.urls import path
from . import views

app_name = 'analytics'

urlpatterns = [
    # Market Analytics
    path('market/trends/', views.MarketTrendsView.as_view(), name='market-trends'),
    path('market/prices/', views.PriceAnalyticsView.as_view(), name='price-analytics'),
    path('market/inventory/', views.InventoryAnalyticsView.as_view(), name='inventory-analytics'),
    path('market/absorption/', views.AbsorptionRateView.as_view(), name='absorption-rate'),
    
    # Property Analytics
    path('properties/<uuid:property_id>/performance/', views.PropertyPerformanceView.as_view(), name='property-performance'),
    path('properties/<uuid:property_id>/valuation/', views.PropertyValuationView.as_view(), name='property-valuation'),
    path('properties/<uuid:property_id>/investment/', views.InvestmentAnalysisView.as_view(), name='investment-analysis'),
    path('properties/<uuid:property_id>/roi/', views.ROICalculatorView.as_view(), name='roi-calculator'),
    
    # Price Predictions
    path('predictions/price/', views.PricePredictionView.as_view(), name='price-prediction'),
    path('predictions/rental/', views.RentalPredictionView.as_view(), name='rental-prediction'),
    path('predictions/appreciation/', views.AppreciationForecastView.as_view(), name='appreciation-forecast'),
    
    # Neighborhood Analytics
    path('neighborhoods/<uuid:neighborhood_id>/market/', views.NeighborhoodMarketView.as_view(), name='neighborhood-market'),
    path('neighborhoods/<uuid:neighborhood_id>/growth/', views.NeighborhoodGrowthView.as_view(), name='neighborhood-growth'),
    path('neighborhoods/compare/', views.NeighborhoodComparisonView.as_view(), name='neighborhood-comparison'),
    
    # User Behavior Analytics
    path('users/engagement/', views.UserEngagementView.as_view(), name='user-engagement'),
    path('users/search-patterns/', views.SearchPatternsView.as_view(), name='search-patterns'),
    path('users/conversion/', views.ConversionAnalyticsView.as_view(), name='conversion-analytics'),
    
    # Agent Performance Analytics
    path('agents/<uuid:agent_id>/performance/', views.AgentPerformanceView.as_view(), name='agent-performance'),
    path('agents/<uuid:agent_id>/listings/', views.AgentListingAnalyticsView.as_view(), name='agent-listing-analytics'),
    path('agents/leaderboard/', views.AgentLeaderboardView.as_view(), name='agent-leaderboard'),
    
    # Reports
    path('reports/daily/', views.DailyReportView.as_view(), name='daily-report'),
    path('reports/weekly/', views.WeeklyReportView.as_view(), name='weekly-report'),
    path('reports/monthly/', views.MonthlyReportView.as_view(), name='monthly-report'),
    path('reports/custom/', views.CustomReportView.as_view(), name='custom-report'),
    
    # Dashboard Data
    path('dashboard/admin/', views.AdminDashboardView.as_view(), name='admin-dashboard'),
    path('dashboard/agent/', views.AgentDashboardView.as_view(), name='agent-dashboard'),
    path('dashboard/user/', views.UserDashboardView.as_view(), name='user-dashboard'),
    
    # Export Analytics
    path('export/', views.AnalyticsExportView.as_view(), name='analytics-export'),
] 
 