"""
URL patterns for users app.
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

app_name = 'users'

# Create a router and register our viewsets with it
router = DefaultRouter()
router.register(r'profiles', views.UserProfileViewSet, basename='profile')
router.register(r'preferences', views.UserPreferenceViewSet, basename='preferences')
router.register(r'activities', views.UserActivityViewSet, basename='activities')

urlpatterns = [
    # Include the router URLs
    path('', include(router.urls)),
    
    # Custom user endpoints
    path('me/', views.CurrentUserView.as_view(), name='current-user'),
    path('me/profile/', views.CurrentUserProfileView.as_view(), name='current-user-profile'),
    path('me/preferences/', views.CurrentUserPreferencesView.as_view(), name='current-user-preferences'),
    path('me/activities/', views.CurrentUserActivitiesView.as_view(), name='current-user-activities'),
    path('me/sessions/', views.CurrentUserSessionsView.as_view(), name='current-user-sessions'),
    
    # Profile management
    path('profile/picture/', views.UpdateProfilePictureView.as_view(), name='update-profile-picture'),
    
    # User search (for admin/agents)
    path('search/', views.UserSearchView.as_view(), name='user-search'),
    
    # Verification
    path('verify/', views.UserVerificationView.as_view(), name='user-verification'),
    path('verify/documents/', views.UploadVerificationDocumentsView.as_view(), name='upload-verification-docs'),
    
    # Agent specific endpoints
    path('agents/', views.AgentListView.as_view(), name='agent-list'),
    path('agents/<uuid:pk>/', views.AgentDetailView.as_view(), name='agent-detail'),
    
    # Referral system
    path('referrals/', views.ReferralView.as_view(), name='referrals'),
    path('referrals/apply/', views.ApplyReferralCodeView.as_view(), name='apply-referral'),
] 