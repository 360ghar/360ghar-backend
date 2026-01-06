#!/usr/bin/env python3
"""Verify the seeded PM data."""
import httpx
import os

TOKEN = os.environ.get("AUTH_TOKEN", "")
if not TOKEN:
    print("ERROR: AUTH_TOKEN environment variable not set!")
    exit(1)
BASE_URL = "http://localhost:8000/api/v1"

headers = {"Authorization": f"Bearer {TOKEN}"}

print("=" * 50)
print("PM Data Verification")
print("=" * 50)

# Check properties
print("\n--- Properties ---")
resp = httpx.get(f"{BASE_URL}/pm/properties/", headers=headers)
if resp.status_code == 200:
    props = resp.json()
    print(f"Total: {len(props)}")
    for p in props[:5]:
        print(f"  - {p['title']} (ID: {p['id']})")
else:
    print(f"Error: {resp.status_code} - {resp.text[:100]}")

# Check leases
print("\n--- Leases ---")
resp = httpx.get(f"{BASE_URL}/pm/leases/", headers=headers)
if resp.status_code == 200:
    leases = resp.json()
    print(f"Total: {len(leases)}")
    for l in leases[:5]:
        print(f"  - Lease {l['id']}: {l.get('tenant_name', 'N/A')} - {l.get('status', 'N/A')}")
else:
    print(f"Error: {resp.status_code} - {resp.text[:100]}")

# Check rent charges
print("\n--- Rent Charges ---")
resp = httpx.get(f"{BASE_URL}/pm/rent/charges", headers=headers)
if resp.status_code == 200:
    charges = resp.json()
    print(f"Total: {len(charges)}")
else:
    print(f"Error: {resp.status_code} - {resp.text[:100]}")

# Check tenants
print("\n--- Tenants ---")
resp = httpx.get(f"{BASE_URL}/pm/tenants/", headers=headers)
if resp.status_code == 200:
    tenants = resp.json()
    print(f"Total: {len(tenants)}")
    for t in tenants[:5]:
        print(f"  - {t.get('full_name') or t.get('tenant_name', 'N/A')}")
else:
    print(f"Error: {resp.status_code} - {resp.text[:100]}")

print("\n" + "=" * 50)
print("Verification Complete!")
