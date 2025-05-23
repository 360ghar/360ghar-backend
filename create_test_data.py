#!/usr/bin/env python
"""
Script to create test data for 360ghar platform
"""
import os
import django

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ghar360.settings')
django.setup()

from users.models import User
from properties.models import Property
from decimal import Decimal

def create_test_data():
    # Create a test user if doesn't exist
    user, created = User.objects.get_or_create(
        username='testuser',
        defaults={
            'email': 'test@360ghar.com',
            'first_name': 'Test',
            'last_name': 'User',
            'user_type': 'seller'
        }
    )
    if created:
        user.set_password('test123')
        user.save()
        print(f'Created test user: {user.username}')
    else:
        print(f'Test user already exists: {user.username}')

    # Create test properties
    properties_data = [
        {
            'title': 'Modern 2BHK Apartment in Bandra',
            'description': 'Beautiful 2BHK apartment with modern amenities and city view',
            'property_type': 'apartment',
            'listing_type': 'sale',
            'address': '123 Test Street, Bandra West',
            'locality': 'Bandra West',
            'city': 'Mumbai',
            'state': 'Maharashtra',
            'pincode': '400050',
            'latitude': Decimal('19.0596'),
            'longitude': Decimal('72.8295'),
            'price': Decimal('15000000'),
            'total_area': Decimal('1200'),
            'bedrooms': 2,
            'bathrooms': 2,
            'is_featured': True,
        },
        {
            'title': 'Luxury Villa in Gurgaon',
            'description': 'Spacious 4BHK villa with garden and swimming pool',
            'property_type': 'villa',
            'listing_type': 'sale',
            'address': '456 Villa Road, Sector 47',
            'locality': 'Sector 47',
            'city': 'Gurgaon',
            'state': 'Haryana',
            'pincode': '122018',
            'latitude': Decimal('28.4595'),
            'longitude': Decimal('77.0266'),
            'price': Decimal('25000000'),
            'total_area': Decimal('2500'),
            'bedrooms': 4,
            'bathrooms': 3,
            'parking_spaces': 2,
            'is_featured': True,
        },
        {
            'title': 'Cozy Studio Apartment in Bangalore',
            'description': 'Perfect for young professionals, near IT hubs',
            'property_type': 'studio',
            'listing_type': 'rent',
            'address': '789 Tech Park Road, Whitefield',
            'locality': 'Whitefield',
            'city': 'Bangalore',
            'state': 'Karnataka',
            'pincode': '560066',
            'latitude': Decimal('12.9698'),
            'longitude': Decimal('77.7500'),
            'price': Decimal('25000'),
            'total_area': Decimal('500'),
            'bedrooms': 1,
            'bathrooms': 1,
        }
    ]

    for prop_data in properties_data:
        property_obj, created = Property.objects.get_or_create(
            title=prop_data['title'],
            defaults={
                **prop_data,
                'owner': user,
                'is_active': True,
                'status': 'available'
            }
        )
        if created:
            print(f'Created property: {property_obj.title}')
        else:
            print(f'Property already exists: {property_obj.title}')

    print(f'\nTotal properties in database: {Property.objects.count()}')
    print(f'Featured properties: {Property.objects.filter(is_featured=True).count()}')

if __name__ == '__main__':
    create_test_data() 