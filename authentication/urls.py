"""
URL patterns for authentication app.
"""

from django.urls import path
from . import views

app_name = 'authentication'

urlpatterns = [
    # Registration and Login
    path('register/', views.RegisterView.as_view(), name='register'),
    path('login/', views.LoginView.as_view(), name='login'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    
    # Token Management
    path('token/info/', views.TokenInfoView.as_view(), name='token-info'),
    
    # Password Management
    path('password/change/', views.ChangePasswordView.as_view(), name='change-password'),
    path('password/reset/', views.PasswordResetView.as_view(), name='password-reset'),
    path('password/reset/confirm/', views.PasswordResetConfirmView.as_view(), name='password-reset-confirm'),
    
    # Social Authentication
    path('social/google/', views.GoogleOAuth2LoginView.as_view(), name='google-oauth2-login'),
    path('social/facebook/', views.FacebookOAuth2LoginView.as_view(), name='facebook-oauth2-login'),
    
    # Email Verification
    path('email/verify/', views.EmailVerificationView.as_view(), name='email-verify'),
    path('email/verify/resend/', views.ResendEmailVerificationView.as_view(), name='resend-email-verification'),
    
    # Phone Verification
    path('phone/verify/', views.PhoneVerificationView.as_view(), name='phone-verify'),
    path('phone/verify/resend/', views.ResendPhoneVerificationView.as_view(), name='resend-phone-verification'),
    
    # Two-Factor Authentication
    path('2fa/enable/', views.Enable2FAView.as_view(), name='enable-2fa'),
    path('2fa/disable/', views.Disable2FAView.as_view(), name='disable-2fa'),
    path('2fa/verify/', views.Verify2FAView.as_view(), name='verify-2fa'),
    
    # Session Management
    path('sessions/', views.UserSessionsView.as_view(), name='user-sessions'),
    path('sessions/<uuid:session_id>/revoke/', views.RevokeSessionView.as_view(), name='revoke-session'),
    path('sessions/revoke-all/', views.RevokeAllSessionsView.as_view(), name='revoke-all-sessions'),
] 