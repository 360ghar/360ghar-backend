"""
360Ghar MCP Server - Manual Testing Script
==========================================

This script allows you to test MCP tools directly without needing ChatGPT.
It handles authentication and calls MCP tools via the REST API.

Usage:
    python test_mcp_tools.py

Requirements:
    - Backend server running at http://localhost:8000
    - Valid Supabase user credentials (phone + password)
"""

import asyncio
import httpx
import json
from typing import Optional, Dict, Any


# Configuration
BASE_URL = "http://localhost:8000"
MCP_URL = f"{BASE_URL}/mcp/"

# Test user credentials (update with your actual test user)
TEST_PHONE = "+919876543210"  # Change this to your actual phone
TEST_PASSWORD = "your_password"  # Change this to your actual password


class MCPTester:
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self.mcp_url = f"{base_url}/mcp/"
        self.access_token: Optional[str] = None
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def close(self):
        await self.client.aclose()
    
    async def login_supabase(self, phone: str, password: str) -> bool:
        """Login via Supabase Auth and get JWT token."""
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
                print(f"   Token: {self.access_token[:20]}..." if self.access_token else "")
                return True
            else:
                print(f"❌ Login failed: {response.status_code}")
                print(f"   Response: {response.text}")
                return False
        except Exception as e:
            print(f"❌ Login error: {e}")
            return False
    
    async def call_mcp_tool(self, tool_name: str, arguments: Dict[str, Any] = None) -> Dict[str, Any]:
        """Call an MCP tool and return the result."""
        if arguments is None:
            arguments = {}
        
        # Add JWT to arguments if authenticated
        if self.access_token:
            arguments["jwt"] = self.access_token
        
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            },
            "id": 1
        }
        
        # MCP StreamableHTTP requires both application/json and text/event-stream
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"
        }
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        
        print(f"\n📞 Calling tool: {tool_name}")
        print(f"   Arguments: {json.dumps(arguments, indent=2)[:200]}...")
        
        try:
            response = await self.client.post(
                self.mcp_url,
                json=payload,
                headers=headers
            )
            
            result = response.json()
            print(f"   Status: {response.status_code}")
            return result
        except Exception as e:
            print(f"❌ Error: {e}")
            return {"error": str(e)}
    
    async def test_system_status(self):
        """Test system.status tool - works without auth."""
        result = await self.call_mcp_tool("system.status")
        self._print_result("system.status", result)
        return result
    
    async def test_properties_search(self, query: str = "Gurgaon", limit: int = 5):
        """Test properties.search tool."""
        result = await self.call_mcp_tool("properties.search", {
            "search_query": query,
            "limit": limit
        })
        self._print_result("properties.search", result)
        return result
    
    async def test_properties_get(self, property_id: int):
        """Test properties.get tool."""
        result = await self.call_mcp_tool("properties.get", {
            "property_id": property_id
        })
        self._print_result("properties.get", result)
        return result
    
    async def test_discovery_feed(self, limit: int = 5):
        """Test discovery.feed tool - requires auth."""
        result = await self.call_mcp_tool("discovery.feed", {"limit": limit})
        self._print_result("discovery.feed", result)
        return result
    
    async def test_user_profile(self):
        """Test user.profile tool - requires auth."""
        result = await self.call_mcp_tool("user.profile")
        self._print_result("user.profile", result)
        return result
    
    async def test_shortlist(self):
        """Test shortlist.list tool - requires auth."""
        result = await self.call_mcp_tool("shortlist.list", {"limit": 10})
        self._print_result("shortlist.list", result)
        return result
    
    async def test_swipe_like(self, property_id: int):
        """Test swipes.like tool - requires auth."""
        result = await self.call_mcp_tool("swipes.like", {"property_id": property_id})
        self._print_result("swipes.like", result)
        return result
    
    async def test_blog_search(self, query: str = "buying tips"):
        """Test blog.search tool."""
        result = await self.call_mcp_tool("blog.search", {"query": query, "limit": 5})
        self._print_result("blog.search", result)
        return result
    
    def _print_result(self, tool_name: str, result: Dict[str, Any]):
        """Pretty print the result."""
        print(f"\n{'='*60}")
        print(f"📋 Result for: {tool_name}")
        print(f"{'='*60}")
        
        if "error" in result:
            print(f"❌ Error: {result['error']}")
        elif "result" in result:
            content = result["result"]
            if isinstance(content, list) and len(content) > 0:
                # MCP returns content as array
                for item in content:
                    if isinstance(item, dict) and "text" in item:
                        try:
                            data = json.loads(item["text"])
                            print(json.dumps(data, indent=2, default=str)[:2000])
                        except:
                            print(item["text"][:2000])
            else:
                print(json.dumps(content, indent=2, default=str)[:2000])
        else:
            print(json.dumps(result, indent=2, default=str)[:2000])


async def run_all_tests():
    """Run all MCP tool tests."""
    tester = MCPTester()
    
    try:
        print("\n" + "="*60)
        print("🚀 360Ghar MCP Tool Testing")
        print("="*60)
        
        # Test 1: System Status (no auth needed)
        print("\n" + "-"*60)
        print("TEST 1: System Status (No Auth)")
        print("-"*60)
        await tester.test_system_status()
        
        # Test 2: Property Search (no auth needed)
        print("\n" + "-"*60)
        print("TEST 2: Property Search (No Auth)")
        print("-"*60)
        await tester.test_properties_search("Gurgaon", 3)
        
        # Test 3: Blog Search (no auth needed)
        print("\n" + "-"*60)
        print("TEST 3: Blog Search (No Auth)")
        print("-"*60)
        await tester.test_blog_search()
        
        # Login for authenticated tests
        print("\n" + "-"*60)
        print("AUTHENTICATION")
        print("-"*60)
        login_success = await tester.login_supabase(TEST_PHONE, TEST_PASSWORD)
        
        if login_success:
            # Test 4: User Profile (auth required)
            print("\n" + "-"*60)
            print("TEST 4: User Profile (Auth Required)")
            print("-"*60)
            await tester.test_user_profile()
            
            # Test 5: Discovery Feed (auth optional but personalized)
            print("\n" + "-"*60)
            print("TEST 5: Discovery Feed")
            print("-"*60)
            await tester.test_discovery_feed(3)
            
            # Test 6: Shortlist
            print("\n" + "-"*60)
            print("TEST 6: View Shortlist")
            print("-"*60)
            await tester.test_shortlist()
        else:
            print("\n⚠️  Skipping authenticated tests (login failed)")
            print("   Update TEST_PHONE and TEST_PASSWORD in this script")
        
        print("\n" + "="*60)
        print("✅ Testing Complete!")
        print("="*60)
        
    finally:
        await tester.close()


async def interactive_test():
    """Interactive testing mode."""
    tester = MCPTester()
    
    print("\n" + "="*60)
    print("🎮 Interactive MCP Testing Mode")
    print("="*60)
    print("\nCommands:")
    print("  1. status     - Check system status")
    print("  2. search     - Search properties")
    print("  3. get <id>   - Get property details")
    print("  4. login      - Login with credentials")
    print("  5. profile    - View user profile")
    print("  6. feed       - Get discovery feed")
    print("  7. like <id>  - Like a property")
    print("  8. shortlist  - View liked properties")
    print("  9. quit       - Exit")
    print("-"*60)
    
    try:
        while True:
            cmd = input("\n> ").strip().lower()
            
            if cmd == "quit" or cmd == "q":
                break
            elif cmd == "status" or cmd == "1":
                await tester.test_system_status()
            elif cmd == "search" or cmd == "2":
                query = input("  Search query: ").strip() or "Gurgaon"
                await tester.test_properties_search(query)
            elif cmd.startswith("get ") or cmd == "3":
                try:
                    prop_id = int(cmd.split()[1]) if cmd.startswith("get ") else int(input("  Property ID: "))
                    await tester.test_properties_get(prop_id)
                except (ValueError, IndexError):
                    print("  Invalid property ID")
            elif cmd == "login" or cmd == "4":
                phone = input("  Phone (e.g., +919876543210): ").strip()
                password = input("  Password: ").strip()
                await tester.login_supabase(phone, password)
            elif cmd == "profile" or cmd == "5":
                await tester.test_user_profile()
            elif cmd == "feed" or cmd == "6":
                await tester.test_discovery_feed()
            elif cmd.startswith("like ") or cmd == "7":
                try:
                    prop_id = int(cmd.split()[1]) if cmd.startswith("like ") else int(input("  Property ID: "))
                    await tester.test_swipe_like(prop_id)
                except (ValueError, IndexError):
                    print("  Invalid property ID")
            elif cmd == "shortlist" or cmd == "8":
                await tester.test_shortlist()
            else:
                print("  Unknown command. Type 'quit' to exit.")
    finally:
        await tester.close()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "-i":
        # Interactive mode
        asyncio.run(interactive_test())
    else:
        # Run all tests
        asyncio.run(run_all_tests())
