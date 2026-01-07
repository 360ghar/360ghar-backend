#!/usr/bin/env python3
"""
Property Management Data Seeding Script (API-based)

Seeds the database with comprehensive mock data for PM features via API calls.
This approach uses the running backend server to seed data.

Usage:
    python populate_data/scripts/seed_pm_data_api.py
    python populate_data/scripts/seed_pm_data_api.py --base-url http://localhost:8000
"""

import argparse
import json
import random
import sys
import os
from datetime import date, datetime, timedelta
from pathlib import Path
import requests

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class PMDataSeederAPI:
    """Seeds PM data via API calls"""

    def __init__(self, base_url: str, access_token: str):
        self.base_url = base_url.rstrip("/")
        self.access_token = access_token
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        self.data_dir = Path(__file__).parent.parent / "data"
        self._pm_data = None

    @property
    def pm_data(self) -> dict:
        """Load PM data from JSON file"""
        if self._pm_data is None:
            pm_data_path = self.data_dir / "pm_data.json"
            with open(pm_data_path, "r", encoding="utf-8") as f:
                self._pm_data = json.load(f)
        return self._pm_data

    def _api_get(self, endpoint: str, params: dict = None) -> dict:
        """Make GET request to API"""
        url = f"{self.base_url}/api/v1{endpoint}"
        response = requests.get(url, headers=self.headers, params=params)
        response.raise_for_status()
        return response.json()

    def _api_post(self, endpoint: str, data: dict) -> dict:
        """Make POST request to API"""
        url = f"{self.base_url}/api/v1{endpoint}"
        response = requests.post(url, headers=self.headers, json=data)
        if not response.ok:
            print(f"Error {response.status_code}: {response.text[:200]}")
        response.raise_for_status()
        return response.json()

    def get_properties(self) -> list:
        """Get properties owned by current user"""
        return self._api_get("/pm/properties/")

    def create_lease(self, lease_data: dict) -> dict:
        """Create a lease"""
        return self._api_post("/pm/leases/", lease_data)

    def generate_rent_charges(self, lease_id: int, months: int = 6) -> dict:
        """Generate rent charges for a lease"""
        return self._api_post("/pm/rent/charges/generate", {
            "lease_id": lease_id,
            "months": months,
        })

    def record_payment(self, payment_data: dict) -> dict:
        """Record a rent payment"""
        return self._api_post("/pm/rent/payments", payment_data)

    def create_maintenance_request(self, request_data: dict) -> dict:
        """Create a maintenance request"""
        return self._api_post("/pm/maintenance/requests", request_data)

    def create_expense(self, expense_data: dict) -> dict:
        """Create an expense"""
        return self._api_post("/pm/expenses/", expense_data)

    def create_inspection(self, inspection_data: dict) -> dict:
        """Create an inspection checklist"""
        return self._api_post("/pm/inspections/", inspection_data)

    def seed_all(self, max_properties: int = 5, leases_per_property: int = 1):
        """Seed all PM data"""
        counts = {
            "leases": 0,
            "rent_charges": 0,
            "rent_payments": 0,
            "maintenance_requests": 0,
            "expenses": 0,
            "inspections": 0,
        }

        # Get existing properties
        print("Fetching properties...")
        properties = self.get_properties()
        
        if not properties:
            print("No properties found. Please create properties first.")
            return counts

        print(f"Found {len(properties)} properties")
        properties = properties[:max_properties]

        tenants = self.pm_data["tenants"]
        lease_templates = self.pm_data["lease_templates"]

        # Create leases for each property
        leases = []
        for i, prop in enumerate(properties):
            print(f"\nProcessing property {i+1}/{len(properties)}: {prop.get('title', 'N/A')[:50]}")
            
            for j in range(leases_per_property):
                tenant = tenants[j % len(tenants)]
                monthly_rent = random.choice(lease_templates["monthly_rents"])
                
                # Calculate dates
                start_date = date.today() - timedelta(days=random.randint(60, 180))
                end_date = start_date + timedelta(days=365)
                
                lease_data = {
                    "property_id": prop["id"],
                    "tenant_name": tenant["name"],
                    "tenant_phone": tenant["phone"],
                    "tenant_email": tenant["email"],
                    "status": "active",
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "monthly_rent": monthly_rent,
                    "security_deposit": monthly_rent * 2,
                    "grace_period_days": random.choice(lease_templates["grace_period_days"]),
                    "payment_due_day": random.choice(lease_templates["payment_due_days"]),
                    "late_fee_amount": random.choice(lease_templates["late_fee_amounts"]),
                    "special_clauses": random.choice(lease_templates["special_clauses"]),
                }

                try:
                    lease = self.create_lease(lease_data)
                    leases.append(lease)
                    counts["leases"] += 1
                    print(f"  Created lease {lease['id']} for {tenant['name']}")

                    # Generate rent charges
                    try:
                        charge_result = self.generate_rent_charges(lease["id"], months=4)
                        charges_created = charge_result.get("created", 0) if isinstance(charge_result, dict) else 0
                        counts["rent_charges"] += charges_created
                        print(f"    Generated {charges_created} rent charges")
                    except Exception as e:
                        print(f"    Warning: Could not generate rent charges: {e}")

                except Exception as e:
                    print(f"  Failed to create lease: {e}")

            # Create maintenance requests
            maint_templates = random.sample(
                self.pm_data["maintenance_templates"], 
                min(2, len(self.pm_data["maintenance_templates"]))
            )
            for template in maint_templates:
                request_data = {
                    "property_id": prop["id"],
                    "category": template["category"],
                    "urgency": template["urgency"],
                    "title": template["title"],
                    "description": template["description"],
                }
                try:
                    req = self.create_maintenance_request(request_data)
                    counts["maintenance_requests"] += 1
                    print(f"  Created maintenance request: {template['title'][:30]}")
                except Exception as e:
                    print(f"  Failed to create maintenance request: {e}")

            # Create expenses
            expense_templates = random.sample(
                self.pm_data["expense_templates"],
                min(3, len(self.pm_data["expense_templates"]))
            )
            for template in expense_templates:
                amount_min, amount_max = template["amount_range"]
                expense_data = {
                    "property_id": prop["id"],
                    "category": template["category"],
                    "amount": round(random.uniform(amount_min, amount_max), 2),
                    "expense_date": (date.today() - timedelta(days=random.randint(1, 90))).isoformat(),
                    "description": template["description"],
                }
                try:
                    self.create_expense(expense_data)
                    counts["expenses"] += 1
                    print(f"  Created expense: {template['description'][:30]}")
                except Exception as e:
                    print(f"  Failed to create expense: {e}")

        # Create inspections for first few leases
        for lease in leases[:3]:
            inspection_data = {
                "lease_id": lease["id"],
                "inspection_type": "move_in",
                "rooms_data": {
                    "rooms": self.pm_data["inspection_rooms"],
                    "summary": "Overall good condition",
                },
                "overall_notes": "Move-in inspection completed. Property in good condition.",
                "conducted_at": datetime.now().isoformat(),
            }
            try:
                self.create_inspection(inspection_data)
                counts["inspections"] += 1
                print(f"  Created move-in inspection for lease {lease['id']}")
            except Exception as e:
                print(f"  Failed to create inspection: {e}")

        return counts


def get_access_token(base_url: str, email: str = None, phone: str = None) -> str:
    """
    Get access token for authentication.
    You can provide an email or phone to get the OTP sent.
    For testing, you might need to manually get the token from Supabase.
    """
    # For now, return a placeholder - you'll need to provide a real token
    raise ValueError(
        "Please provide a valid access token. "
        "Get it from the app or Supabase dashboard."
    )


def main():
    parser = argparse.ArgumentParser(
        description="Seed Property Management mock data via API"
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Base URL of the backend API (default: http://localhost:8000)"
    )
    parser.add_argument(
        "--token",
        required=True,
        help="Access token for authentication (get from app login)"
    )
    parser.add_argument(
        "--max-properties",
        type=int,
        default=5,
        help="Maximum number of properties to seed data for (default: 5)"
    )
    parser.add_argument(
        "--leases-per-property",
        type=int,
        default=1,
        help="Number of leases per property (default: 1)"
    )

    args = parser.parse_args()

    print("=" * 60)
    print("PM DATA SEEDING (API-based)")
    print("=" * 60)
    print(f"Base URL: {args.base_url}")
    print(f"Max Properties: {args.max_properties}")
    print(f"Leases per Property: {args.leases_per_property}")
    print("=" * 60)

    seeder = PMDataSeederAPI(args.base_url, args.token)
    
    try:
        counts = seeder.seed_all(
            max_properties=args.max_properties,
            leases_per_property=args.leases_per_property,
        )

        print("\n" + "=" * 60)
        print("SEEDING COMPLETE")
        print("=" * 60)
        for entity, count in counts.items():
            print(f"  {entity}: {count}")
        print("=" * 60)

    except requests.exceptions.HTTPError as e:
        print(f"\nHTTP Error: {e}")
        print("Make sure the backend server is running and the token is valid.")
        sys.exit(1)
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
