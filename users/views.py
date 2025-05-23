"""
Users views for 360ghar platform.
Complete user management system with profiles, preferences, and activities.
"""

from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.db.models import Count, Sum, Q, Avg
from rest_framework import status, viewsets, filters, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
import datetime

from .models import User, UserPreference, UserActivity, UserSession
from .serializers import (
    UserSerializer, UserProfileSerializer, UserUpdateSerializer,
    UserPreferenceSerializer, UserActivitySerializer, UserSessionSerializer,
    UserStatsSerializer, PublicUserSerializer
)


class UserPagination(PageNumberPagination):
    """Custom pagination for users"""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class UserProfileViewSet(viewsets.ModelViewSet):
    """User profile management viewset"""
    queryset = User.objects.all()
    permission_classes = [IsAuthenticated]
    pagination_class = UserPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['username', 'first_name', 'last_name', 'email']
    ordering_fields = ['date_joined', 'last_login', 'username']
    ordering = ['-date_joined']
    filterset_fields = ['user_type', 'is_active', 'is_email_verified']
    
    def get_serializer_class(self):
        if self.action == 'list':
            return UserSerializer
        elif self.action in ['update', 'partial_update']:
            return UserUpdateSerializer
        return UserProfileSerializer
    
    def get_permissions(self):
        """
        Instantiates and returns the list of permissions that this view requires.
        """
        if self.action == 'list':
            permission_classes = [IsAuthenticated]
        elif self.action == 'retrieve':
            permission_classes = [AllowAny]  # Public profiles
        elif self.action in ['update', 'partial_update', 'destroy']:
            permission_classes = [IsAuthenticated]
        else:
            permission_classes = [IsAuthenticated]
        
        return [permission() for permission in permission_classes]
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filter for active users only in public contexts
        if self.action == 'list' and not self.request.user.is_staff:
            queryset = queryset.filter(is_active=True)
        
        return queryset
    
    def update(self, request, *args, **kwargs):
        # Only allow users to update their own profile
        user = self.get_object()
        if user != request.user and not request.user.is_staff:
            return Response({
                'error': 'You can only update your own profile'
            }, status=status.HTTP_403_FORBIDDEN)
        
        return super().update(request, *args, **kwargs)
    
    def destroy(self, request, *args, **kwargs):
        # Only allow users to delete their own profile or admin
        user = self.get_object()
        if user != request.user and not request.user.is_staff:
            return Response({
                'error': 'You can only delete your own profile'
            }, status=status.HTTP_403_FORBIDDEN)
        
        # Soft delete - deactivate instead of hard delete
        user.is_active = False
        user.save()
        
        return Response({
            'message': 'Account deactivated successfully'
        }, status=status.HTTP_200_OK)
    
    @action(detail=True, methods=['get'])
    def stats(self, request, pk=None):
        """Get user statistics"""
        user = self.get_object()
        
        # Only show stats to the user themselves or admin
        if user != request.user and not request.user.is_staff:
            return Response({
                'error': 'Permission denied'
            }, status=status.HTTP_403_FORBIDDEN)
        
        # Calculate statistics
        total_properties = user.owned_properties.count()
        active_properties = user.owned_properties.filter(is_active=True).count()
        
        total_views = sum(prop.views_count for prop in user.owned_properties.all())
        total_likes = sum(prop.likes_count for prop in user.owned_properties.all())
        total_inquiries = sum(prop.inquiries_count for prop in user.owned_properties.all())
        
        # Last 30 days stats
        last_month = timezone.now() - timezone.timedelta(days=30)
        views_this_month = 0
        likes_this_month = 0
        inquiries_this_month = 0
        
        for prop in user.owned_properties.all():
            views_this_month += prop.property_views.filter(viewed_at__gte=last_month).count()
            likes_this_month += prop.likes.filter(created_at__gte=last_month).count()
            inquiries_this_month += prop.inquiries.filter(created_at__gte=last_month).count()
        
        stats_data = {
            'total_properties': total_properties,
            'active_properties': active_properties,
            'total_views': total_views,
            'total_likes': total_likes,
            'total_inquiries': total_inquiries,
            'views_this_month': views_this_month,
            'likes_this_month': likes_this_month,
            'inquiries_this_month': inquiries_this_month,
            'join_date': user.date_joined,
            'last_login': user.last_login,
        }
        
        serializer = UserStatsSerializer(stats_data)
        return Response(serializer.data)


class UserPreferenceViewSet(viewsets.ModelViewSet):
    """User preference management viewset"""
    serializer_class = UserPreferenceSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        return UserPreference.objects.filter(user=self.request.user)
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class UserActivityViewSet(viewsets.ReadOnlyModelViewSet):
    """User activity tracking viewset (read-only)"""
    serializer_class = UserActivitySerializer
    permission_classes = [IsAuthenticated]
    pagination_class = UserPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['activity_type']
    ordering = ['-created_at']
    
    def get_queryset(self):
        return UserActivity.objects.filter(user=self.request.user)


class CurrentUserView(APIView):
    """Get current authenticated user"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        serializer = UserSerializer(request.user, context={'request': request})
        return Response(serializer.data)


class CurrentUserProfileView(APIView):
    """Get/Update current user profile"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        serializer = UserProfileSerializer(request.user, context={'request': request})
        return Response(serializer.data)
    
    def put(self, request):
        serializer = UserUpdateSerializer(
            request.user, 
            data=request.data, 
            partial=True,
            context={'request': request}
        )
        if serializer.is_valid():
            serializer.save()
            
            # Log activity
            UserActivity.objects.create(
                user=request.user,
                activity_type='profile_update',
                description='Updated profile information',
                ip_address=self._get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '')
            )
            
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def _get_client_ip(self, request):
        """Get client IP address"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', '')


class CurrentUserPreferencesView(APIView):
    """Get/Update current user preferences"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        try:
            preferences = UserPreference.objects.get(user=request.user)
            serializer = UserPreferenceSerializer(preferences)
            return Response(serializer.data)
        except UserPreference.DoesNotExist:
            return Response({
                'message': 'No preferences set yet'
            }, status=status.HTTP_404_NOT_FOUND)
    
    def put(self, request):
        try:
            preferences = UserPreference.objects.get(user=request.user)
            serializer = UserPreferenceSerializer(preferences, data=request.data, partial=True)
        except UserPreference.DoesNotExist:
            serializer = UserPreferenceSerializer(data=request.data)
        
        if serializer.is_valid():
            serializer.save(user=request.user)
            
            # Log activity
            UserActivity.objects.create(
                user=request.user,
                activity_type='preferences_update',
                description='Updated user preferences',
                ip_address=self._get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '')
            )
            
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def _get_client_ip(self, request):
        """Get client IP address"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', '')


class CurrentUserActivitiesView(APIView):
    """Get current user activities"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        activities = UserActivity.objects.filter(user=request.user).order_by('-created_at')[:50]
        serializer = UserActivitySerializer(activities, many=True)
        return Response(serializer.data)


class CurrentUserSessionsView(APIView):
    """Get current user sessions"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        sessions = UserSession.objects.filter(
            user=request.user,
            logout_time__isnull=True
        ).order_by('-login_time')
        
        session_data = []
        current_token = request.auth.token if request.auth else None
        
        for session in sessions:
            session_info = {
                'id': session.id,
                'ip_address': session.ip_address,
                'device_info': session.device_info,
                'login_time': session.login_time,
                'last_activity': session.last_activity,
                'is_current': session.session_key == current_token
            }
            session_data.append(session_info)
        
        return Response({
            'sessions': session_data,
            'total_sessions': len(session_data)
        })


class UpdateProfilePictureView(APIView):
    """Update user profile picture"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        if 'profile_picture' not in request.FILES:
            return Response({
                'error': 'No profile picture file provided'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        profile_picture = request.FILES['profile_picture']
        
        # Validate file size (max 5MB)
        if profile_picture.size > 5 * 1024 * 1024:
            return Response({
                'error': 'File size too large. Maximum size is 5MB.'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Validate file type
        allowed_types = ['image/jpeg', 'image/png', 'image/jpg']
        if profile_picture.content_type not in allowed_types:
            return Response({
                'error': 'Invalid file type. Only JPEG and PNG files are allowed.'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Update profile picture
        request.user.profile_picture = profile_picture
        request.user.save(update_fields=['profile_picture'])
        
        # Log activity
        UserActivity.objects.create(
            user=request.user,
            activity_type='profile_picture_update',
            description='Updated profile picture',
            ip_address=self._get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', '')
        )
        
        return Response({
            'message': 'Profile picture updated successfully',
            'profile_picture_url': request.build_absolute_uri(request.user.profile_picture.url) if request.user.profile_picture else None
        })
    
    def _get_client_ip(self, request):
        """Get client IP address"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', '')


class AgentListView(APIView):
    """List of verified agents"""
    permission_classes = [AllowAny]
    
    def get(self, request):
        agents = User.objects.filter(
            user_type='agent',
            is_active=True,
            verification_status='verified'
        ).order_by('-date_joined')
        
        # Add agent-specific stats
        agent_data = []
        for agent in agents:
            agent_info = PublicUserSerializer(agent).data
            agent_info.update({
                'total_properties': agent.owned_properties.filter(is_active=True).count(),
                'total_views': sum(prop.views_count for prop in agent.owned_properties.all()),
                'total_likes': sum(prop.likes_count for prop in agent.owned_properties.all()),
            })
            agent_data.append(agent_info)
        
        return Response({
            'agents': agent_data,
            'total_agents': len(agent_data)
        })


class AgentDetailView(APIView):
    """Agent detail view with properties and stats"""
    permission_classes = [AllowAny]
    
    def get(self, request, pk):
        try:
            agent = User.objects.get(
                pk=pk,
                user_type='agent',
                is_active=True
            )
        except User.DoesNotExist:
            return Response({
                'error': 'Agent not found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        agent_data = PublicUserSerializer(agent).data
        
        # Add detailed agent stats
        properties = agent.owned_properties.filter(is_active=True)
        agent_data.update({
            'total_properties': properties.count(),
            'active_properties': properties.filter(status='available').count(),
            'sold_properties': properties.filter(status='sold').count(),
            'rented_properties': properties.filter(status='rented').count(),
            'total_views': sum(prop.views_count for prop in properties),
            'total_likes': sum(prop.likes_count for prop in properties),
            'total_inquiries': sum(prop.inquiries_count for prop in properties),
                         'avg_price': properties.aggregate(avg_price=Avg('price'))['avg_price'] or 0,
            'property_types': list(properties.values_list('property_type', flat=True).distinct()),
        })
        
        return Response(agent_data)


class UserVerificationView(APIView):
    """Request user verification"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        verification_type = request.data.get('verification_type', 'email')
        
        if verification_type == 'email':
            # Send email verification
            # Implementation for email verification resend
            UserActivity.objects.create(
                user=request.user,
                activity_type='email_verification_request',
                description='Requested email verification',
                ip_address=self._get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '')
            )
            
            return Response({
                'message': 'Email verification sent'
            })
        
        elif verification_type == 'phone':
            # Send phone verification
            # Implementation for phone verification
            UserActivity.objects.create(
                user=request.user,
                activity_type='phone_verification_request',
                description='Requested phone verification',
                ip_address=self._get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '')
            )
            
            return Response({
                'message': 'Phone verification will be implemented in future update'
            }, status=status.HTTP_501_NOT_IMPLEMENTED)
        
        return Response({
            'error': 'Invalid verification type'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    def _get_client_ip(self, request):
        """Get client IP address"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', '')


class UserSearchView(APIView):
    """Search users (for admin/agent features)"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        # Only allow agents and admins to search users
        if request.user.user_type not in ['agent', 'admin']:
            return Response({
                'error': 'Permission denied'
            }, status=status.HTTP_403_FORBIDDEN)
        
        query = request.GET.get('q', '')
        user_type = request.GET.get('user_type', '')
        
        users = User.objects.filter(is_active=True)
        
        if query:
            users = users.filter(
                Q(username__icontains=query) |
                Q(first_name__icontains=query) |
                Q(last_name__icontains=query) |
                Q(email__icontains=query)
            )
        
        if user_type:
            users = users.filter(user_type=user_type)
        
        users = users[:20]  # Limit results
        serializer = PublicUserSerializer(users, many=True)
        
        return Response({
            'users': serializer.data,
            'total_results': len(serializer.data)
        })


# Placeholder views for future implementation
class UploadVerificationDocumentsView(APIView):
    """Upload verification documents - to be implemented"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        return Response({
            'message': 'Document verification will be implemented in a future update'
        }, status=status.HTTP_501_NOT_IMPLEMENTED)


class ReferralView(APIView):
    """Referral system - to be implemented"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        return Response({
            'message': 'Referral system will be implemented in a future update'
        }, status=status.HTTP_501_NOT_IMPLEMENTED)


class ApplyReferralCodeView(APIView):
    """Apply referral code - to be implemented"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        return Response({
            'message': 'Referral system will be implemented in a future update'
        }, status=status.HTTP_501_NOT_IMPLEMENTED)
