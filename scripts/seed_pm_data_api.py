#!/usr/bin/env python3
"""
Seed PM mock data via API endpoints.
Uses HTTP requests to the running backend server.

Usage:
    1. Make sure the backend is running at localhost:8000
    2. Run: python scripts/seed_pm_data_api.py
    
Requires:
    - pip install httpx
"""
import httpx
import asyncio
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

BASE_URL = "http://localhost:8000/api/v1"

import os

# Get token from environment variable for security
# Usage: AUTH_TOKEN=your_jwt_token python scripts/seed_pm_data_api.py
AUTH_TOKEN = os.environ.get("AUTH_TOKEN", "")

if not AUTH_TOKEN:
    print("ERROR: AUTH_TOKEN environment variable not set!")
    print("Usage: AUTH_TOKEN=your_jwt_token python scripts/seed_pm_data_api.py")
    print("\nGet your token from the app's auth state or network inspector.")
    exit(1)


MOCK_PROPERTIES = [
    {
        "title": "Spacious 2BHK Apartment in Vijay Nagar",
        "description": "Modern 2BHK apartment with modular kitchen, 24x7 water supply, and covered parking. Located in prime area near schools and markets.",
        "property_type": "apartment",
        "purpose": "rent",
        "base_price": 15000,
        "city": "Indore",
        "features": ["2 BHK", "Modular Kitchen", "Covered Parking", "24x7 Water"],
    },
    {
        "title": "Premium 3BHK House in Arera Colony",
        "description": "Independent 3BHK house with garden, parking for 2 cars, servant quarter, and RO water system. Ideal for families.",
        "property_type": "house",
        "purpose": "rent",
        "base_price": 25000,
        "city": "Bhopal",
        "features": ["3 BHK", "Garden", "2 Car Parking", "Servant Quarter"],
    },
    {
        "title": "Luxury 4BHK Villa in Premium Society",
        "description": "Luxury villa with private pool, home theater, modular kitchen, and 24x7 security. Premium living at its best.",
        "property_type": "house",
        "purpose": "rent",
        "base_price": 50000,
        "city": "Mumbai",
        "features": ["4 BHK", "Pool", "Home Theater", "24x7 Security"],
    },
]


async def seed_data():
    """Create mock PM data via API."""
    print("=" * 60)
    print("PM Data API Seeder")
    print("=" * 60)
    
    headers = {
        "Authorization": f"Bearer {AUTH_TOKEN}",
        "Content-Type": "application/json",
    }
    
    async with httpx.AsyncClient(timeout=30) as client:
        # 1. Create Properties
        print("\n--- Creating Properties ---")
        properties = []
        for prop_data in MOCK_PROPERTIES:
            try:
                resp = await client.post(
                    f"{BASE_URL}/pm/properties/",
                    json=prop_data,
                    headers=headers,
                )
                if resp.status_code == 200:
                    prop = resp.json()
                    properties.append(prop)
                    print(f"✓ Created: {prop['title']} (ID: {prop['id']})")
                else:
                    print(f"✗ Failed: {prop_data['title']} - {resp.status_code}: {resp.text[:100]}")
            except Exception as e:
                print(f"✗ Error: {prop_data['title']} - {e}")
        
        if not properties:
            print("No properties created. Please check the API.")
            return
        
        # 2. Create Leases
        print("\n--- Creating Leases ---")
        leases = []
        today = date.today()
        
        for i, prop in enumerate(properties[:2]):  # First 2 properties
            start = today - relativedelta(months=6-i*3)
            end = start + relativedelta(months=12)
            
            lease_data = {
                "property_id": prop["id"],
                "tenant_name": f"Test Tenant {i+1}",
                "tenant_phone": f"+9198765432{i}0",
                "tenant_email": f"tenant{i+1}@test.com",
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "monthly_rent": prop.get("base_price", 15000),
                "security_deposit": prop.get("base_price", 15000) * 2,
                "status": "active",
            }
            
            try:
                resp = await client.post(
                    f"{BASE_URL}/pm/leases/",
                    json=lease_data,
                    headers=headers,
                )
                if resp.status_code == 200:
                    lease = resp.json()
                    leases.append(lease)
                    print(f"✓ Created lease for {prop['title']} (ID: {lease['id']})")
                else:
                    print(f"✗ Failed lease for {prop['title']} - {resp.status_code}: {resp.text[:100]}")
            except Exception as e:
                print(f"✗ Error creating lease: {e}")
        
        # 3. Generate Rent Charges
        print("\n--- Generating Rent Charges ---")
        for lease in leases:
            try:
                start_month = (today - relativedelta(months=2)).replace(day=1)
                resp = await client.post(
                    f"{BASE_URL}/pm/rent/charges/generate",
                    json={
                        "lease_id": lease["id"],
                        "start_month": start_month.isoformat(),
                        "months": 3,
                    },
                    headers=headers,
                )
                if resp.status_code == 200:
                    print(f"✓ Generated rent charges for lease {lease['id']}")
                else:
                    print(f"✗ Failed: {resp.status_code}: {resp.text[:100]}")
            except Exception as e:
                print(f"✗ Error: {e}")
        
        # Summary
        print("\n" + "=" * 60)
        print("PM Data Seed Completed!")
        print("=" * 60)
        print(f"\nCreated:")
        print(f"  - Properties: {len(properties)}")
        print(f"  - Leases: {len(leases)}")
        print(f"\nTest with:")
        print(f"  curl -H 'Authorization: Bearer test' {BASE_URL}/pm/properties/")


if __name__ == "__main__":
    asyncio.run(seed_data())
