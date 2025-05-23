"""
Authentication views for 360ghar platform.
Complete authentication system with OAuth2, JWT, and user management.
"""

from rest_framework import status, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.hashers import check_password
from django.core.mail import send_mail
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.urls import reverse
from django.conf import settings
from django.utils import timezone
from django.db import transaction
from oauth2_provider.models import Application, AccessToken
from oauth2_provider.views import TokenView as BaseTokenView
from oauth2_provider import oauth2_validators
from oauthlib.common import generate_token
import json

from users.models import User, UserSession
from users.serializers import UserRegistrationSerializer, UserSerializer


class RegisterView(APIView):
    """User registration with email verification"""
    permission_classes = [AllowAny]
    
    def post(self, request):
        serializer = UserRegistrationSerializer(data=request.data)
        
        if serializer.is_valid():
            try:
                with transaction.atomic():
                    user = serializer.save()
                    
                    # Send verification email
                    self._send_verification_email(user, request)
                    
                    return Response({
                        'message': 'Registration successful. Please check your email for verification.',
                        'user_id': user.id,
                        'email': user.email
                    }, status=status.HTTP_201_CREATED)
                    
            except Exception as e:
                return Response({
                    'error': 'Registration failed',
                    'details': str(e)
                }, status=status.HTTP_400_BAD_REQUEST)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def _send_verification_email(self, user, request):
        """Send email verification"""
        token = default_token_generator.make_token(user)
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        
        verification_url = request.build_absolute_uri(
            reverse('authentication:email-verify') + f'?uid={uid}&token={token}'
        )
        
        subject = 'Verify your 360Ghar account'
        message = f"""
        Welcome to 360Ghar!
        
        Please click the link below to verify your email address:
        {verification_url}
        
        If you didn't create this account, please ignore this email.
        
        Best regards,
        360Ghar Team
        """
        
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False
        )


class LoginView(APIView):
    """User login with OAuth2 token generation"""
    permission_classes = [AllowAny]
    
    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')
        
        if not username or not password:
            return Response({
                'error': 'Username and password are required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Authenticate user
        user = authenticate(username=username, password=password)
        
        if user is None:
            return Response({
                'error': 'Invalid credentials'
            }, status=status.HTTP_401_UNAUTHORIZED)
        
        if not user.is_active:
            return Response({
                'error': 'Account is disabled'
            }, status=status.HTTP_401_UNAUTHORIZED)
        
        # Generate OAuth2 tokens
        application = self._get_or_create_application()
        access_token = self._create_access_token(user, application)
        
        # Create user session
        session = UserSession.objects.create(
            user=user,
            session_key=access_token.token,
            ip_address=self._get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
            device_info=self._get_device_info(request)
        )
        
        # Update last login
        user.last_login = timezone.now()
        user.save(update_fields=['last_login'])
        
        return Response({
            'access_token': access_token.token,
            'refresh_token': None,  # Will implement refresh tokens if needed
            'token_type': 'Bearer',
            'expires_in': 3600,
            'user': UserSerializer(user).data,
            'session_id': session.id
        }, status=status.HTTP_200_OK)
    
    def _get_or_create_application(self):
        """Get or create OAuth2 application for 360Ghar"""
        try:
            return Application.objects.get(name='360Ghar Web App')
        except Application.DoesNotExist:
            return Application.objects.create(
                name='360Ghar Web App',
                client_type=Application.CLIENT_CONFIDENTIAL,
                authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
            )
    
    def _create_access_token(self, user, application):
        """Create OAuth2 access token"""
        return AccessToken.objects.create(
            user=user,
            application=application,
            token=generate_token(),
            expires=timezone.now() + timezone.timedelta(seconds=3600),
            scope='read write'
        )
    
    def _get_client_ip(self, request):
        """Get client IP address"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', '')
    
    def _get_device_info(self, request):
        """Extract device information"""
        user_agent = request.META.get('HTTP_USER_AGENT', '')
        device_info = {'user_agent': user_agent}
        
        if 'Mobile' in user_agent:
            device_info['device_type'] = 'mobile'
        elif 'Tablet' in user_agent:
            device_info['device_type'] = 'tablet'
        else:
            device_info['device_type'] = 'desktop'
        
        return device_info


class LogoutView(APIView):
    """User logout with token revocation"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        try:
            # Get the access token from the request
            auth_header = request.META.get('HTTP_AUTHORIZATION', '')
            if auth_header.startswith('Bearer '):
                token = auth_header[7:]
                
                # Revoke the access token
                AccessToken.objects.filter(token=token).delete()
                
                # End user session
                UserSession.objects.filter(
                    user=request.user,
                    session_key=token,
                    logout_time__isnull=True
                ).update(logout_time=timezone.now())
                
                return Response({
                    'message': 'Successfully logged out'
                }, status=status.HTTP_200_OK)
            
            return Response({
                'error': 'No valid token found'
            }, status=status.HTTP_400_BAD_REQUEST)
            
        except Exception as e:
            return Response({
                'error': 'Logout failed',
                'details': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)


class ChangePasswordView(APIView):
    """Change user password"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        old_password = request.data.get('old_password')
        new_password = request.data.get('new_password')
        
        if not old_password or not new_password:
            return Response({
                'error': 'Both old and new passwords are required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        user = request.user
        
        # Verify old password
        if not check_password(old_password, user.password):
            return Response({
                'error': 'Old password is incorrect'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Validate new password
        try:
            from django.contrib.auth.password_validation import validate_password
            validate_password(new_password, user)
        except Exception as e:
            return Response({
                'error': 'New password validation failed',
                'details': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Change password
        user.set_password(new_password)
        user.save()
        
        # Revoke all existing tokens
        AccessToken.objects.filter(user=user).delete()
        UserSession.objects.filter(user=user, logout_time__isnull=True).update(
            logout_time=timezone.now()
        )
        
        return Response({
            'message': 'Password changed successfully. Please login again.'
        }, status=status.HTTP_200_OK)


class PasswordResetView(APIView):
    """Request password reset"""
    permission_classes = [AllowAny]
    
    def post(self, request):
        email = request.data.get('email')
        
        if not email:
            return Response({
                'error': 'Email is required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            user = User.objects.get(email=email, is_active=True)
            
            # Generate reset token
            token = default_token_generator.make_token(user)
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            
            # Send reset email
            reset_url = request.build_absolute_uri(
                reverse('authentication:password-reset-confirm') + f'?uid={uid}&token={token}'
            )
            
            subject = 'Reset your 360Ghar password'
            message = f"""
            You requested a password reset for your 360Ghar account.
            
            Click the link below to reset your password:
            {reset_url}
            
            If you didn't request this, please ignore this email.
            This link will expire in 24 hours.
            
            Best regards,
            360Ghar Team
            """
            
            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=False
            )
            
            return Response({
                'message': 'Password reset instructions sent to your email'
            }, status=status.HTTP_200_OK)
            
        except User.DoesNotExist:
            # Don't reveal if email exists or not for security
            return Response({
                'message': 'If the email exists, password reset instructions have been sent'
            }, status=status.HTTP_200_OK)


class PasswordResetConfirmView(APIView):
    """Confirm password reset with new password"""
    permission_classes = [AllowAny]
    
    def post(self, request):
        uid = request.data.get('uid')
        token = request.data.get('token')
        new_password = request.data.get('new_password')
        
        if not all([uid, token, new_password]):
            return Response({
                'error': 'UID, token, and new password are required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            # Decode user ID
            user_id = force_str(urlsafe_base64_decode(uid))
            user = User.objects.get(pk=user_id, is_active=True)
            
            # Verify token
            if not default_token_generator.check_token(user, token):
                return Response({
                    'error': 'Invalid or expired reset token'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Validate new password
            try:
                from django.contrib.auth.password_validation import validate_password
                validate_password(new_password, user)
            except Exception as e:
                return Response({
                    'error': 'Password validation failed',
                    'details': str(e)
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Set new password
            user.set_password(new_password)
            user.save()
            
            # Revoke all existing tokens and sessions
            AccessToken.objects.filter(user=user).delete()
            UserSession.objects.filter(user=user, logout_time__isnull=True).update(
                logout_time=timezone.now()
            )
            
            return Response({
                'message': 'Password reset successful. Please login with your new password.'
            }, status=status.HTTP_200_OK)
            
        except (User.DoesNotExist, ValueError, TypeError):
            return Response({
                'error': 'Invalid reset link'
            }, status=status.HTTP_400_BAD_REQUEST)


class EmailVerificationView(APIView):
    """Verify user email address"""
    permission_classes = [AllowAny]
    
    def get(self, request):
        uid = request.GET.get('uid')
        token = request.GET.get('token')
        
        if not uid or not token:
            return Response({
                'error': 'Invalid verification link'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            user_id = force_str(urlsafe_base64_decode(uid))
            user = User.objects.get(pk=user_id)
            
            if default_token_generator.check_token(user, token):
                user.is_email_verified = True
                user.save(update_fields=['is_email_verified'])
                
                return Response({
                    'message': 'Email verified successfully'
                }, status=status.HTTP_200_OK)
            else:
                return Response({
                    'error': 'Invalid or expired verification token'
                }, status=status.HTTP_400_BAD_REQUEST)
                
        except (User.DoesNotExist, ValueError, TypeError):
            return Response({
                'error': 'Invalid verification link'
            }, status=status.HTTP_400_BAD_REQUEST)


class UserSessionsView(APIView):
    """Get user's active sessions"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        sessions = UserSession.objects.filter(
            user=request.user,
            logout_time__isnull=True
        ).order_by('-login_time')
        
        session_data = []
        for session in sessions:
            session_data.append({
                'id': session.id,
                'ip_address': session.ip_address,
                'device_info': session.device_info,
                'login_time': session.login_time,
                'last_activity': session.last_activity,
                'is_current': session.session_key == request.auth.token if request.auth else False
            })
        
        return Response({
            'sessions': session_data,
            'total_sessions': len(session_data)
        }, status=status.HTTP_200_OK)


class RevokeSessionView(APIView):
    """Revoke a specific session"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request, session_id):
        try:
            session = UserSession.objects.get(
                id=session_id,
                user=request.user,
                logout_time__isnull=True
            )
            
            # Revoke the access token
            AccessToken.objects.filter(token=session.session_key).delete()
            
            # End the session
            session.logout_time = timezone.now()
            session.save()
            
            return Response({
                'message': 'Session revoked successfully'
            }, status=status.HTTP_200_OK)
            
        except UserSession.DoesNotExist:
            return Response({
                'error': 'Session not found'
            }, status=status.HTTP_404_NOT_FOUND)


class RevokeAllSessionsView(APIView):
    """Revoke all user sessions except current"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        current_token = request.auth.token if request.auth else None
        
        # Revoke all tokens except current
        if current_token:
            AccessToken.objects.filter(user=request.user).exclude(token=current_token).delete()
            UserSession.objects.filter(
                user=request.user,
                logout_time__isnull=True
            ).exclude(session_key=current_token).update(logout_time=timezone.now())
        else:
            # Revoke all tokens
            AccessToken.objects.filter(user=request.user).delete()
            UserSession.objects.filter(
                user=request.user,
                logout_time__isnull=True
            ).update(logout_time=timezone.now())
        
        revoked_count = UserSession.objects.filter(
            user=request.user,
            logout_time=timezone.now()
        ).count()
        
        return Response({
            'message': f'Successfully revoked {revoked_count} sessions'
        }, status=status.HTTP_200_OK)


class TokenInfoView(APIView):
    """Get information about the current token"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        if not request.auth:
            return Response({
                'error': 'No token provided'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        token = request.auth
        
        return Response({
            'user_id': token.user.id,
            'username': token.user.username,
            'email': token.user.email,
            'scope': token.scope,
            'expires': token.expires,
            'application': token.application.name if token.application else None,
            'created': token.created,
        }, status=status.HTTP_200_OK)


# Placeholder views for future implementation
class GoogleOAuth2LoginView(APIView):
    """Google OAuth2 login - to be implemented"""
    permission_classes = [AllowAny]
    
    def post(self, request):
        return Response({
            'message': 'Google OAuth2 login will be implemented in a future update'
        }, status=status.HTTP_501_NOT_IMPLEMENTED)


class FacebookOAuth2LoginView(APIView):
    """Facebook OAuth2 login - to be implemented"""
    permission_classes = [AllowAny]
    
    def post(self, request):
        return Response({
            'message': 'Facebook OAuth2 login will be implemented in a future update'
        }, status=status.HTTP_501_NOT_IMPLEMENTED)


class ResendEmailVerificationView(APIView):
    """Resend email verification - to be implemented"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        return Response({
            'message': 'Resend email verification will be implemented in a future update'
        }, status=status.HTTP_501_NOT_IMPLEMENTED)


class PhoneVerificationView(APIView):
    """Phone verification - to be implemented"""
    permission_classes = [AllowAny]
    
    def post(self, request):
        return Response({
            'message': 'Phone verification will be implemented in a future update'
        }, status=status.HTTP_501_NOT_IMPLEMENTED)


class ResendPhoneVerificationView(APIView):
    """Resend phone verification - to be implemented"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        return Response({
            'message': 'Resend phone verification will be implemented in a future update'
        }, status=status.HTTP_501_NOT_IMPLEMENTED)


class Enable2FAView(APIView):
    """Enable 2FA - to be implemented"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        return Response({
            'message': '2FA will be implemented in a future update'
        }, status=status.HTTP_501_NOT_IMPLEMENTED)


class Disable2FAView(APIView):
    """Disable 2FA - to be implemented"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        return Response({
            'message': '2FA will be implemented in a future update'
        }, status=status.HTTP_501_NOT_IMPLEMENTED)


class Verify2FAView(APIView):
    """Verify 2FA - to be implemented"""
    permission_classes = [AllowAny]
    
    def post(self, request):
        return Response({
            'message': '2FA will be implemented in a future update'
        }, status=status.HTTP_501_NOT_IMPLEMENTED)
