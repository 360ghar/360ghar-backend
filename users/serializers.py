"""
Serializers for users app.
"""

from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError
from .models import User, UserPreference, UserActivity, UserSession


class UserRegistrationSerializer(serializers.ModelSerializer):
    """Serializer for user registration"""
    password = serializers.CharField(write_only=True, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True)
    
    class Meta:
        model = User
        fields = [
            'username', 'email', 'password', 'password_confirm',
            'first_name', 'last_name', 'phone_number', 'user_type'
        ]
    
    def validate(self, data):
        if data['password'] != data['password_confirm']:
            raise serializers.ValidationError("Passwords don't match")
        return data
    
    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("Email already registered")
        return value
    
    def validate_username(self, value):
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("Username already taken")
        return value
    
    def create(self, validated_data):
        validated_data.pop('password_confirm')
        password = validated_data.pop('password')
        
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        
        return user


class UserSerializer(serializers.ModelSerializer):
    """Basic user serializer for user info"""
    full_name = serializers.ReadOnlyField()
    is_email_verified = serializers.SerializerMethodField()
    is_phone_verified = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name', 'full_name',
            'phone_number', 'user_type', 'profile_picture', 'profile_data',
            'date_joined', 'last_login', 'is_active', 'is_email_verified',
            'is_phone_verified', 'latitude', 'longitude', 'address'
        ]
        read_only_fields = [
            'id', 'date_joined', 'last_login', 'is_active',
            'is_email_verified', 'is_phone_verified'
        ]
    
    def get_is_email_verified(self, obj):
        return obj.verification_status == 'verified'
    
    def get_is_phone_verified(self, obj):
        # For now, return False as we don't have phone verification implemented
        return False


class UserProfileSerializer(serializers.ModelSerializer):
    """Detailed user profile serializer"""
    full_name = serializers.ReadOnlyField()
    total_properties = serializers.SerializerMethodField()
    total_views = serializers.SerializerMethodField()
    total_likes = serializers.SerializerMethodField()
    is_email_verified = serializers.SerializerMethodField()
    is_phone_verified = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name', 'full_name',
            'phone_number', 'user_type', 'profile_picture', 'profile_data',
            'date_joined', 'last_login', 'is_active', 'is_email_verified',
            'is_phone_verified', 'latitude', 'longitude', 'address',
            'total_properties', 'total_views', 'total_likes'
        ]
        read_only_fields = [
            'id', 'date_joined', 'last_login', 'is_active',
            'is_email_verified', 'is_phone_verified', 'total_properties',
            'total_views', 'total_likes'
        ]
    
    def get_is_email_verified(self, obj):
        return obj.verification_status == 'verified'
    
    def get_is_phone_verified(self, obj):
        return False
    
    def get_total_properties(self, obj):
        return obj.owned_properties.filter(is_active=True).count()
    
    def get_total_views(self, obj):
        return sum(prop.views_count for prop in obj.owned_properties.all())
    
    def get_total_likes(self, obj):
        return sum(prop.likes_count for prop in obj.owned_properties.all())


class UserUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating user profile"""
    
    class Meta:
        model = User
        fields = [
            'first_name', 'last_name', 'phone_number', 'profile_data',
            'profile_picture', 'latitude', 'longitude', 'address'
        ]
    
    def validate_phone_number(self, value):
        if value and User.objects.filter(phone_number=value).exclude(pk=self.instance.pk).exists():
            raise serializers.ValidationError("Phone number already registered")
        return value


class UserPreferenceSerializer(serializers.ModelSerializer):
    """Serializer for user preferences"""
    
    class Meta:
        model = UserPreference
        fields = [
            'id', 'preferred_property_types', 'preferred_listing_types',
            'min_budget', 'max_budget', 'preferred_locations',
            'min_bedrooms', 'max_bedrooms', 'preferred_amenities',
            'email_notifications', 'sms_notifications', 'push_notifications',
            'marketing_emails', 'newsletter_subscription', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class UserActivitySerializer(serializers.ModelSerializer):
    """Serializer for user activity tracking"""
    
    class Meta:
        model = UserActivity
        fields = [
            'id', 'activity_type', 'description', 'metadata',
            'ip_address', 'user_agent', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class UserSessionSerializer(serializers.ModelSerializer):
    """Serializer for user sessions"""
    
    class Meta:
        model = UserSession
        fields = [
            'id', 'ip_address', 'user_agent', 'device_info',
            'login_time', 'logout_time', 'last_activity', 'is_active'
        ]
        read_only_fields = ['id', 'login_time', 'logout_time', 'last_activity', 'is_active']


class PasswordChangeSerializer(serializers.Serializer):
    """Serializer for password change"""
    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, validators=[validate_password])
    
    def validate_old_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError("Old password is incorrect")
        return value


class PasswordResetSerializer(serializers.Serializer):
    """Serializer for password reset request"""
    email = serializers.EmailField(required=True)
    
    def validate_email(self, value):
        if not User.objects.filter(email=value, is_active=True).exists():
            # Don't reveal if email exists for security
            pass
        return value


class PasswordResetConfirmSerializer(serializers.Serializer):
    """Serializer for password reset confirmation"""
    uid = serializers.CharField(required=True)
    token = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, validators=[validate_password])


class LoginSerializer(serializers.Serializer):
    """Serializer for user login"""
    username = serializers.CharField(required=True)
    password = serializers.CharField(required=True, write_only=True)
    
    def validate(self, data):
        username = data.get('username')
        password = data.get('password')
        
        if username and password:
            user = authenticate(username=username, password=password)
            if not user:
                raise serializers.ValidationError("Invalid credentials")
            if not user.is_active:
                raise serializers.ValidationError("Account is disabled")
            data['user'] = user
        else:
            raise serializers.ValidationError("Username and password are required")
        
        return data


class UserStatsSerializer(serializers.Serializer):
    """Serializer for user statistics"""
    total_properties = serializers.IntegerField(read_only=True)
    active_properties = serializers.IntegerField(read_only=True)
    total_views = serializers.IntegerField(read_only=True)
    total_likes = serializers.IntegerField(read_only=True)
    total_inquiries = serializers.IntegerField(read_only=True)
    views_this_month = serializers.IntegerField(read_only=True)
    likes_this_month = serializers.IntegerField(read_only=True)
    inquiries_this_month = serializers.IntegerField(read_only=True)
    join_date = serializers.DateTimeField(read_only=True)
    last_login = serializers.DateTimeField(read_only=True)


class PublicUserSerializer(serializers.ModelSerializer):
    """Public user serializer (minimal info for property listings)"""
    full_name = serializers.ReadOnlyField()
    
    class Meta:
        model = User
        fields = [
            'id', 'username', 'first_name', 'last_name', 'full_name',
            'user_type', 'profile_picture', 'date_joined'
        ] 