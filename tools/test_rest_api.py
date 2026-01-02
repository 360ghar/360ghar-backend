"""
360Ghar REST API - Manual Testing Script
=========================================

This script tests the REST API endpoints directly.
Much simpler than MCP testing since it uses standard JSON.

Usage:
    python test_rest_api.py
"""

import asyncio
import httpx
import json
from typing import Optional, Dict, Any


# Configuration
BASE_URL = "http://localhost:8000"


class RestAPITester:
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self.access_token: Optional[str] = None
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def close(self):
        await self.client.aclose()
    
    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers
    
    async def login(self, phone: str, password: str) -> bool:
        """Login and get access token."""
        print(f"\n🔐 Logging in with phone: {phone}")
        
        try:
            response = await self.client.post(
                f"{self.base_url}/api/v1/auth/login/",
                json={"phone": phone, "password": password}
            )
            
            if response.status_code == 200:
                data = response.json()
                self.access_token = data.get("access_token")
                print(f"✅ Login successful!")
                return True
            else:
                print(f"❌ Login failed: {response.status_code}")
                print(f"   Response: {response.text[:200]}")
                return False
        except Exception as e:
            print(f"❌ Login error: {e}")
            return False
    
    async def health_check(self):
        """Check server health."""
        print("\n📋 Health Check")
        response = await self.client.get(f"{self.base_url}/health")
        data = response.json()
        print(json.dumps(data, indent=2))
        return data
    
    async def search_properties(self, query: str = None, limit: int = 5):
        """Search properties."""
        print(f"\n🏠 Searching properties: {query or 'all'}")
        
        params = {"limit": limit}
        if query:
            params["q"] = query
        
        response = await self.client.get(
            f"{self.base_url}/api/v1/properties/",
            params=params,
            headers=self._headers()
        )
        
        if response.status_code == 200:
            data = response.json()
            properties = data.get("properties", [])
            print(f"✅ Found {len(properties)} properties")
            for i, prop in enumerate(properties[:5], 1):
                print(f"   {i}. [{prop.get('id')}] {prop.get('title', 'N/A')[:50]}")
                print(f"      📍 {prop.get('city', 'N/A')}, {prop.get('locality', 'N/A')}")
                print(f"      💰 ₹{prop.get('base_price', 0):,}")
            return data
        else:
            print(f"❌ Error: {response.status_code}")
            print(f"   {response.text[:200]}")
            return None
    
    async def get_property(self, property_id: int):
        """Get property details."""
        print(f"\n🏠 Getting property #{property_id}")
        
        response = await self.client.get(
            f"{self.base_url}/api/v1/properties/{property_id}/",
            headers=self._headers()
        )
        
        if response.status_code == 200:
            data = response.json()
            prop = data.get("property", data)
            print(f"✅ Property Details:")
            print(f"   Title: {prop.get('title', 'N/A')}")
            print(f"   Type: {prop.get('property_type', 'N/A')}")
            print(f"   Location: {prop.get('city', 'N/A')}, {prop.get('locality', 'N/A')}")
            print(f"   Price: ₹{prop.get('base_price', 0):,}")
            print(f"   Bedrooms: {prop.get('bedrooms', 'N/A')}")
            print(f"   Bathrooms: {prop.get('bathrooms', 'N/A')}")
            return data
        else:
            print(f"❌ Error: {response.status_code}")
            return None
    
    async def get_profile(self):
        """Get current user profile."""
        print("\n👤 Getting user profile")
        
        if not self.access_token:
            print("❌ Not logged in")
            return None
        
        response = await self.client.get(
            f"{self.base_url}/api/v1/users/profile/",
            headers=self._headers()
        )
        
        if response.status_code == 200:
            data = response.json()
            user = data.get("user", data)
            print(f"✅ User Profile:")
            print(f"   Name: {user.get('full_name', 'N/A')}")
            print(f"   Phone: {user.get('phone', 'N/A')}")
            print(f"   Email: {user.get('email', 'N/A')}")
            print(f"   Role: {user.get('role', 'N/A')}")
            return data
        else:
            print(f"❌ Error: {response.status_code}")
            return None
    
    async def get_recommendations(self, limit: int = 5):
        """Get property recommendations."""
        print(f"\n⭐ Getting recommendations")
        
        response = await self.client.get(
            f"{self.base_url}/api/v1/properties/recommendations/",
            params={"limit": limit},
            headers=self._headers()
        )
        
        if response.status_code == 200:
            data = response.json()
            props = data if isinstance(data, list) else data.get("properties", [])
            print(f"✅ Found {len(props)} recommendations")
            for i, prop in enumerate(props[:5], 1):
                print(f"   {i}. [{prop.get('id')}] {prop.get('title', 'N/A')[:50]}")
            return data
        else:
            print(f"❌ Error: {response.status_code}")
            return None
    
    async def get_swipe_history(self, liked_only: bool = True):
        """Get swipe history / shortlist."""
        print(f"\n❤️ Getting {'shortlist' if liked_only else 'swipe history'}")
        
        if not self.access_token:
            print("❌ Not logged in")
            return None
        
        params = {"is_liked": "true"} if liked_only else {}
        response = await self.client.get(
            f"{self.base_url}/api/v1/swipes/",
            params=params,
            headers=self._headers()
        )
        
        if response.status_code == 200:
            data = response.json()
            items = data.get("items", [])
            print(f"✅ Found {len(items)} items")
            for item in items[:5]:
                prop = item.get("property", {})
                print(f"   - [{prop.get('id')}] {prop.get('title', 'N/A')[:40]}")
            return data
        else:
            print(f"❌ Error: {response.status_code}")
            return None
    
    async def like_property(self, property_id: int):
        """Like a property."""
        print(f"\n❤️ Liking property #{property_id}")
        
        if not self.access_token:
            print("❌ Not logged in")
            return None
        
        response = await self.client.post(
            f"{self.base_url}/api/v1/swipes/",
            json={"property_id": property_id, "is_liked": True},
            headers=self._headers()
        )
        
        if response.status_code in [200, 201]:
            print(f"✅ Property #{property_id} liked!")
            return response.json()
        else:
            print(f"❌ Error: {response.status_code}")
            return None


async def interactive_test():
    """Interactive testing mode."""
    tester = RestAPITester()
    
    print("\n" + "="*60)
    print("🎮 Interactive REST API Testing")
    print("="*60)
    print("\nCommands:")
    print("  1. health     - Check server health")
    print("  2. search     - Search properties")
    print("  3. get <id>   - Get property details")
    print("  4. login      - Login with credentials")
    print("  5. profile    - View user profile")
    print("  6. recommend  - Get recommendations")
    print("  7. like <id>  - Like a property")
    print("  8. shortlist  - View liked properties")
    print("  9. quit       - Exit")
    print("-"*60)
    
    try:
        while True:
            cmd = input("\n> ").strip().lower()
            
            if cmd in ["quit", "q", "9"]:
                break
            elif cmd in ["health", "1"]:
                await tester.health_check()
            elif cmd in ["search", "2"]:
                query = input("  Search query (or Enter for all): ").strip() or None
                await tester.search_properties(query)
            elif cmd.startswith("get ") or cmd == "3":
                try:
                    prop_id = int(cmd.split()[1]) if cmd.startswith("get ") else int(input("  Property ID: "))
                    await tester.get_property(prop_id)
                except (ValueError, IndexError):
                    print("  Invalid property ID")
            elif cmd in ["login", "4"]:
                phone = input("  Phone (e.g., +919876543210): ").strip()
                password = input("  Password: ").strip()
                await tester.login(phone, password)
            elif cmd in ["profile", "5"]:
                await tester.get_profile()
            elif cmd in ["recommend", "6"]:
                await tester.get_recommendations()
            elif cmd.startswith("like ") or cmd == "7":
                try:
                    prop_id = int(cmd.split()[1]) if cmd.startswith("like ") else int(input("  Property ID: "))
                    await tester.like_property(prop_id)
                except (ValueError, IndexError):
                    print("  Invalid property ID")
            elif cmd in ["shortlist", "8"]:
                await tester.get_swipe_history(liked_only=True)
            else:
                print("  Unknown command")
    finally:
        await tester.close()
        print("\n👋 Goodbye!")


if __name__ == "__main__":
    asyncio.run(interactive_test())
