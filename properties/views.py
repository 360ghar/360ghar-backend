"""
Properties views for 360ghar platform.
"""

from rest_framework import status, viewsets, filters, permissions
from rest_framework.views import APIView
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q, Count, Avg, F
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.core.exceptions import PermissionDenied
import math

from .models import (
    Property, PropertyMedia, BuildingMaterial, Appliance,
    PropertyLike, PropertyView, PropertyInquiry
)
from .serializers import (
    PropertyListSerializer, PropertyDetailSerializer,
    PropertyCreateUpdateSerializer, PropertyMediaSerializer,
    BuildingMaterialSerializer, ApplianceSerializer,
    PropertyLikeSerializer, PropertyViewSerializer,
    PropertyInquirySerializer, PropertySearchSerializer
)


class PropertyPagination(PageNumberPagination):
    """Custom pagination for properties"""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class PropertyViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing properties
    """
    queryset = Property.objects.select_related('owner', 'agent', 'verified_by').prefetch_related(
        'media', 'building_materials', 'appliances'
    )
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = PropertyPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['title', 'description', 'address', 'locality', 'city']
    ordering_fields = ['price', 'created_at', 'updated_at', 'total_area', 'views_count', 'likes_count']
    ordering = ['-created_at']
    
    def get_serializer_class(self):
        if self.action == 'list':
            return PropertyListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return PropertyCreateUpdateSerializer
        return PropertyDetailSerializer
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filter active properties for non-owners
        if not (self.request.user.is_authenticated and 
                self.request.user.user_type in ['agent', 'admin']):
            queryset = queryset.filter(is_active=True, status='available')
        
        # Order by featured first, then by creation date
        return queryset.order_by('-is_featured', '-created_at')
    
    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        # Record property view
        self._record_property_view(instance)
        serializer = self.get_serializer(instance)
        return Response(serializer.data)
    
    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)
    
    def perform_update(self, serializer):
        property_obj = self.get_object()
        if not (self.request.user == property_obj.owner or 
                self.request.user.user_type in ['agent', 'admin']):
            raise PermissionDenied("You don't have permission to update this property")
        serializer.save()
    
    def perform_destroy(self, instance):
        if not (self.request.user == instance.owner or 
                self.request.user.user_type in ['agent', 'admin']):
            raise PermissionDenied("You don't have permission to delete this property")
        instance.delete()
    
    @action(detail=False, methods=['post'])
    def search(self, request):
        """Advanced property search"""
        serializer = PropertySearchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        queryset = self.filter_queryset(self.get_queryset())
        queryset = self._apply_search_filters(queryset, serializer.validated_data)
        
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = PropertyListSerializer(page, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)
        
        serializer = PropertyListSerializer(queryset, many=True, context={'request': request})
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def like(self, request, pk=None):
        """Like a property"""
        property_obj = self.get_object()
        like, created = PropertyLike.objects.get_or_create(
            user=request.user, property=property_obj
        )
        
        if created:
            # Update likes count
            Property.objects.filter(pk=property_obj.pk).update(
                likes_count=F('likes_count') + 1
            )
            return Response({'status': 'liked'}, status=status.HTTP_201_CREATED)
        else:
            return Response({'status': 'already_liked'}, status=status.HTTP_200_OK)
    
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def unlike(self, request, pk=None):
        """Unlike a property"""
        property_obj = self.get_object()
        deleted_count, _ = PropertyLike.objects.filter(
            user=request.user, property=property_obj
        ).delete()
        
        if deleted_count:
            # Update likes count
            Property.objects.filter(pk=property_obj.pk).update(
                likes_count=F('likes_count') - 1
            )
            return Response({'status': 'unliked'}, status=status.HTTP_200_OK)
        else:
            return Response({'status': 'not_liked'}, status=status.HTTP_200_OK)
    
    @action(detail=True, methods=['get'])
    def similar(self, request, pk=None):
        """Get similar properties"""
        property_obj = self.get_object()
        
        # Find similar properties based on type, location, and price range
        similar_queryset = Property.objects.filter(
            property_type=property_obj.property_type,
            city=property_obj.city,
            is_active=True,
            status='available'
        ).exclude(pk=property_obj.pk)
        
        # Price range filter (±20%)
        price_range = property_obj.price * 0.2
        similar_queryset = similar_queryset.filter(
            price__gte=property_obj.price - price_range,
            price__lte=property_obj.price + price_range
        )
        
        # Similar bedroom count (±1)
        if property_obj.bedrooms:
            similar_queryset = similar_queryset.filter(
                bedrooms__gte=max(1, property_obj.bedrooms - 1),
                bedrooms__lte=property_obj.bedrooms + 1
            )
        
        similar_queryset = similar_queryset[:10]
        serializer = PropertyListSerializer(similar_queryset, many=True, context={'request': request})
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def stats(self, request, pk=None):
        """Get property statistics"""
        property_obj = self.get_object()
        
        # Only owner or admin can see detailed stats
        if not (request.user == property_obj.owner or 
                request.user.user_type in ['agent', 'admin']):
            raise PermissionDenied("You don't have permission to view these statistics")
        
        stats = {
            'views_count': property_obj.views_count,
            'likes_count': property_obj.likes_count,
            'inquiries_count': property_obj.inquiries_count,
            'views_last_7_days': property_obj.property_views.filter(
                viewed_at__gte=timezone.now() - timezone.timedelta(days=7)
            ).count(),
            'inquiries_last_30_days': property_obj.inquiries.filter(
                created_at__gte=timezone.now() - timezone.timedelta(days=30)
            ).count(),
        }
        
        return Response(stats)
    
    def _record_property_view(self, property_obj):
        """Record a property view"""
        user = self.request.user if self.request.user.is_authenticated else None
        ip_address = self._get_client_ip()
        user_agent = self.request.META.get('HTTP_USER_AGENT', '')
        referrer = self.request.META.get('HTTP_REFERER', '')
        
        # Don't record views from the property owner
        if user and user == property_obj.owner:
            return
        
        # Check if this user/IP has already viewed this property recently (within 1 hour)
        recent_threshold = timezone.now() - timezone.timedelta(hours=1)
        recent_view = PropertyView.objects.filter(
            property=property_obj,
            viewed_at__gte=recent_threshold
        )
        
        if user:
            recent_view = recent_view.filter(user=user)
        else:
            recent_view = recent_view.filter(ip_address=ip_address)
        
        if not recent_view.exists():
            PropertyView.objects.create(
                property=property_obj,
                user=user,
                ip_address=ip_address,
                user_agent=user_agent,
                referrer=referrer,
                session_key=self.request.session.session_key or '',
                device_info=self._get_device_info()
            )
            
            # Update views count
            Property.objects.filter(pk=property_obj.pk).update(
                views_count=F('views_count') + 1
            )
    
    def _get_client_ip(self):
        """Get client IP address"""
        x_forwarded_for = self.request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = self.request.META.get('REMOTE_ADDR', '')
        return ip
    
    def _get_device_info(self):
        """Extract basic device info from user agent"""
        user_agent = self.request.META.get('HTTP_USER_AGENT', '')
        device_info = {'user_agent': user_agent}
        
        # Basic device detection
        if 'Mobile' in user_agent:
            device_info['device_type'] = 'mobile'
        elif 'Tablet' in user_agent:
            device_info['device_type'] = 'tablet'
        else:
            device_info['device_type'] = 'desktop'
        
        return device_info
    
    def _apply_search_filters(self, queryset, search_data):
        """Apply search filters to queryset"""
        
        # Text search
        if search_data.get('query'):
            query = search_data['query']
            queryset = queryset.filter(
                Q(title__icontains=query) |
                Q(description__icontains=query) |
                Q(address__icontains=query) |
                Q(locality__icontains=query) |
                Q(city__icontains=query)
            )
        
        # Property filters
        for field in ['property_type', 'listing_type', 'status', 'furnishing_status', 'property_age']:
            if search_data.get(field):
                queryset = queryset.filter(**{field: search_data[field]})
        
        # Location filters
        for field in ['city', 'state', 'locality', 'pincode']:
            if search_data.get(field):
                queryset = queryset.filter(**{f'{field}__icontains': search_data[field]})
        
        # Price range
        if search_data.get('min_price'):
            queryset = queryset.filter(price__gte=search_data['min_price'])
        if search_data.get('max_price'):
            queryset = queryset.filter(price__lte=search_data['max_price'])
        
        # Size filters
        if search_data.get('min_bedrooms'):
            queryset = queryset.filter(bedrooms__gte=search_data['min_bedrooms'])
        if search_data.get('max_bedrooms'):
            queryset = queryset.filter(bedrooms__lte=search_data['max_bedrooms'])
        if search_data.get('min_bathrooms'):
            queryset = queryset.filter(bathrooms__gte=search_data['min_bathrooms'])
        if search_data.get('max_bathrooms'):
            queryset = queryset.filter(bathrooms__lte=search_data['max_bathrooms'])
        if search_data.get('min_area'):
            queryset = queryset.filter(total_area__gte=search_data['min_area'])
        if search_data.get('max_area'):
            queryset = queryset.filter(total_area__lte=search_data['max_area'])
        
        # Features
        if search_data.get('min_parking'):
            queryset = queryset.filter(parking_spaces__gte=search_data['min_parking'])
        
        # Flags
        for flag in ['is_featured', 'is_premium', 'is_verified']:
            if search_data.get(flag) is not None:
                queryset = queryset.filter(**{flag: search_data[flag]})
        
        # Geographic search
        if search_data.get('latitude') and search_data.get('longitude'):
            lat = float(search_data['latitude'])
            lng = float(search_data['longitude'])
            radius = float(search_data.get('radius_km', 10))
            
            # Simple bounding box search (for SQLite compatibility)
            # For production with PostGIS, use proper distance queries
            lat_range = radius / 111.0  # Rough conversion: 1 degree ≈ 111 km
            lng_range = radius / (111.0 * math.cos(math.radians(lat)))
            
            queryset = queryset.filter(
                latitude__range=(lat - lat_range, lat + lat_range),
                longitude__range=(lng - lng_range, lng + lng_range)
            )
        
        return queryset


class PropertyMediaViewSet(viewsets.ModelViewSet):
    """ViewSet for property media"""
    serializer_class = PropertyMediaSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    
    def get_queryset(self):
        property_id = self.kwargs.get('property_pk')
        if property_id:
            return PropertyMedia.objects.filter(property_id=property_id)
        return PropertyMedia.objects.all()
    
    def perform_create(self, serializer):
        property_id = self.kwargs.get('property_pk')
        property_obj = get_object_or_404(Property, pk=property_id)
        
        # Check permission
        if self.request.user != property_obj.owner:
            raise PermissionDenied("You can only upload media for your own properties")
        
        serializer.save(property=property_obj)


class PropertyInquiryViewSet(viewsets.ModelViewSet):
    """ViewSet for property inquiries"""
    serializer_class = PropertyInquirySerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        property_id = self.kwargs.get('property_pk')
        
        queryset = PropertyInquiry.objects.select_related('property', 'user', 'responded_by')
        
        if property_id:
            queryset = queryset.filter(property_id=property_id)
        
        # Users can only see their own inquiries, property owners can see inquiries for their properties
        if user.user_type == 'admin':
            return queryset
        else:
            return queryset.filter(
                Q(user=user) | Q(property__owner=user)
            )
    
    def perform_create(self, serializer):
        property_id = self.kwargs.get('property_pk')
        property_obj = get_object_or_404(Property, pk=property_id)
        
        inquiry = serializer.save(user=self.request.user, property=property_obj)
        
        # Update inquiries count
        Property.objects.filter(pk=property_obj.pk).update(
            inquiries_count=F('inquiries_count') + 1
        )
    
    @action(detail=True, methods=['post'])
    def respond(self, request, pk=None, property_pk=None):
        """Respond to an inquiry"""
        inquiry = self.get_object()
        
        # Only property owner or admin can respond
        if not (request.user == inquiry.property.owner or 
                request.user.user_type == 'admin'):
            raise PermissionDenied("You don't have permission to respond to this inquiry")
        
        response_message = request.data.get('response_message')
        if not response_message:
            return Response(
                {'error': 'response_message is required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        inquiry.response_message = response_message
        inquiry.is_responded = True
        inquiry.responded_at = timezone.now()
        inquiry.responded_by = request.user
        inquiry.save()
        
        serializer = self.get_serializer(inquiry)
        return Response(serializer.data)


class BuildingMaterialViewSet(viewsets.ModelViewSet):
    """ViewSet for building materials"""
    serializer_class = BuildingMaterialSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    
    def get_queryset(self):
        property_id = self.kwargs.get('property_pk')
        if property_id:
            return BuildingMaterial.objects.filter(property_id=property_id)
        return BuildingMaterial.objects.all()
    
    def perform_create(self, serializer):
        property_id = self.kwargs.get('property_pk')
        property_obj = get_object_or_404(Property, pk=property_id)
        
        # Check permission
        if self.request.user != property_obj.owner:
            raise PermissionDenied("You can only add materials for your own properties")
        
        serializer.save(property=property_obj)


class ApplianceViewSet(viewsets.ModelViewSet):
    """ViewSet for appliances"""
    serializer_class = ApplianceSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    
    def get_queryset(self):
        property_id = self.kwargs.get('property_pk')
        if property_id:
            return Appliance.objects.filter(property_id=property_id)
        return Appliance.objects.all()
    
    def perform_create(self, serializer):
        property_id = self.kwargs.get('property_pk')
        property_obj = get_object_or_404(Property, pk=property_id)
        
        # Check permission
        if self.request.user != property_obj.owner:
            raise PermissionDenied("You can only add appliances for your own properties")
        
        serializer.save(property=property_obj)


# Additional API Views

class FeaturedPropertiesView(APIView):
    """Get featured properties"""
    permission_classes = [permissions.AllowAny]
    
    def get(self, request):
        properties = Property.objects.filter(
            is_featured=True, 
            is_active=True, 
            status='available'
        ).select_related('owner').prefetch_related('media')[:20]
        
        serializer = PropertyListSerializer(properties, many=True, context={'request': request})
        return Response(serializer.data)


class MyPropertiesView(APIView):
    """Get current user's properties"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        properties = Property.objects.filter(owner=request.user).select_related(
            'owner', 'agent', 'verified_by'
        ).prefetch_related('media')
        
        serializer = PropertyListSerializer(properties, many=True, context={'request': request})
        return Response(serializer.data)


class PropertyAnalyticsView(APIView):
    """Get property analytics for owners"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request, property_id):
        property_obj = get_object_or_404(Property, pk=property_id)
        
        # Only owner or admin can see analytics
        if not (request.user == property_obj.owner or 
                request.user.user_type == 'admin'):
            raise PermissionDenied("You don't have permission to view these analytics")
        
        # Get analytics data
        total_views = property_obj.views_count
        total_likes = property_obj.likes_count
        total_inquiries = property_obj.inquiries_count
        
        # Views in last 30 days
        last_30_days = timezone.now() - timezone.timedelta(days=30)
        recent_views = property_obj.property_views.filter(viewed_at__gte=last_30_days).count()
        recent_inquiries = property_obj.inquiries.filter(created_at__gte=last_30_days).count()
        
        # View sources
        view_sources = property_obj.property_views.exclude(
            referrer__isnull=True
        ).exclude(referrer='').values('referrer').annotate(
            count=Count('referrer')
        ).order_by('-count')[:5]
        
        analytics = {
            'total_views': total_views,
            'total_likes': total_likes,
            'total_inquiries': total_inquiries,
            'recent_views_30_days': recent_views,
            'recent_inquiries_30_days': recent_inquiries,
            'view_sources': list(view_sources),
            'performance_score': self._calculate_performance_score(
                total_views, total_likes, total_inquiries
            )
        }
        
        return Response(analytics)
    
    def _calculate_performance_score(self, views, likes, inquiries):
        """Calculate a simple performance score"""
        if views == 0:
            return 0
        
        like_rate = (likes / views) * 100 if views > 0 else 0
        inquiry_rate = (inquiries / views) * 100 if views > 0 else 0
        
        # Simple scoring algorithm
        score = min(100, (like_rate * 2) + (inquiry_rate * 5))
        return round(score, 2)
