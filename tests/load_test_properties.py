import asyncio
import aiohttp
import time
import statistics
import json
from typing import List
from app.core.logging import setup_logging, get_logger
logger = get_logger(__name__)

async def test_endpoint(session, url, params):
    """Test a single endpoint call"""
    start = time.time()
    try:
        async with session.get(url, params=params) as response:
            if response.status == 200:
                await response.json()
                return time.time() - start, True
            else:
                return time.time() - start, False
    except Exception as e:
        return time.time() - start, False

async def load_test():
    """Test the /properties endpoint with various scenarios"""
    base_url = "http://localhost:8000/api/v1/properties"
    
    test_scenarios = [
        # Location-based search (Delhi coordinates)
        {"lat": 28.6139, "lng": 77.2090, "radius": 10, "limit": 20},
        # Text search
        {"q": "2 BHK apartment", "limit": 20},
        # Filter combination
        {"property_type": "apartment", "price_min": 5000000, "price_max": 10000000, "limit": 20},
        # Pagination test
        {"page": 2, "limit": 50},
        # Complex filter combination
        {
            "lat": 28.5355, "lng": 77.3910,  # Noida coordinates
            "radius": 15,
            "property_type": "apartment",
            "bedrooms_min": 2,
            "bathrooms_min": 2,
            "price_min": 3000000,
            "price_max": 8000000,
            "amenities": "parking",
            "sort_by": "price_low",
            "limit": 30
        },
        # Short stay booking search
        {
            "purpose": "short_stay",
            "guests": 4,
            "check_in": "2024-12-01",
            "check_out": "2024-12-05",
            "city": "Mumbai",
            "limit": 25
        }
    ]
    
    logger.info("Starting Property Endpoint Load Test")
    
    # Test each scenario
    for i, params in enumerate(test_scenarios, 1):
        logger.info("Testing scenario", extra={"index": i, "params": params})
        await test_scenario(base_url, params, concurrent_requests=20, total_requests=100)
    
    # Comprehensive load test
    logger.info("Comprehensive Load Test")
    await comprehensive_load_test(base_url, test_scenarios)

async def test_scenario(base_url: str, params: dict, concurrent_requests: int = 10, total_requests: int = 50):
    """Test a specific scenario with concurrent requests"""
    times = []
    success_count = 0
    
    connector = aiohttp.TCPConnector(limit=100, limit_per_host=50)
    timeout = aiohttp.ClientTimeout(total=30)
    
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        # Warm up request
        await test_endpoint(session, base_url, params)
        
        # Run batches of concurrent requests
        for batch in range(0, total_requests, concurrent_requests):
            batch_size = min(concurrent_requests, total_requests - batch)
            tasks = [
                test_endpoint(session, base_url, params)
                for _ in range(batch_size)
            ]
            
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for result in batch_results:
                if isinstance(result, tuple):
                    time_taken, success = result
                    times.append(time_taken)
                    if success:
                        success_count += 1
    
    # Calculate statistics
    if times:
        avg_time = statistics.mean(times)
        median_time = statistics.median(times)
        p95_time = statistics.quantiles(times, n=20)[18] if len(times) >= 20 else max(times)
        p99_time = statistics.quantiles(times, n=100)[98] if len(times) >= 100 else max(times)
        success_rate = (success_count / len(times)) * 100
        
        logger.info(
            "Scenario results",
            extra={
                "success_rate": round(success_rate, 1),
                "success_count": success_count,
                "total": len(times),
                "avg": round(avg_time, 3),
                "median": round(median_time, 3),
                "p95": round(p95_time, 3),
                "p99": round(p99_time, 3),
                "min": round(min(times), 3),
                "max": round(max(times), 3),
            },
        )
        
        # Performance assessment
        if avg_time < 0.1:
            perf_rating = "🟢 Excellent"
        elif avg_time < 0.5:
            perf_rating = "🟡 Good"
        elif avg_time < 1.0:
            perf_rating = "🟠 Acceptable"
        else:
            perf_rating = "🔴 Slow"
        
        logger.info("Performance", extra={"rating": perf_rating})
    else:
        logger.warning("No successful requests")

async def comprehensive_load_test(base_url: str, scenarios: list):
    """Run comprehensive load test with mixed scenarios"""
    total_requests = 500
    concurrent_requests = 50
    
    times = []
    success_count = 0
    start_time = time.time()
    
    connector = aiohttp.TCPConnector(limit=200, limit_per_host=100)
    timeout = aiohttp.ClientTimeout(total=30)
    
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        tasks = []
        
        for i in range(total_requests):
            # Rotate through scenarios
            params = scenarios[i % len(scenarios)]
            tasks.append(test_endpoint(session, base_url, params))
            
            # Process in batches
            if len(tasks) >= concurrent_requests or i == total_requests - 1:
                batch_results = await asyncio.gather(*tasks, return_exceptions=True)
                
                for result in batch_results:
                    if isinstance(result, tuple):
                        time_taken, success = result
                        times.append(time_taken)
                        if success:
                            success_count += 1
                
                tasks = []
                
                # Progress indicator
                completed = i + 1
                progress = (completed / total_requests) * 100
                logger.info("Progress", extra={"progress_pct": round(progress, 1), "completed": completed, "total": total_requests})
    
    total_time = time.time() - start_time
    
    logger.info(
        "Comprehensive results",
        extra={
            "total_requests": total_requests,
            "success_rate": round((success_count / len(times)) * 100, 1) if times else 0,
            "total_time": round(total_time, 2),
            "throughput_rps": round(total_requests / total_time, 1) if total_time else 0,
        },
    )
    
    if times:
        logger.info(
            "Response time stats",
            extra={
                "avg": round(statistics.mean(times), 3),
                "p95": round(statistics.quantiles(times, n=20)[18], 3),
            },
        )

async def stress_test():
    """Stress test with high concurrency"""
    base_url = "http://localhost:8000/api/v1/properties"
    params = {"lat": 28.6139, "lng": 77.2090, "radius": 5, "limit": 10}
    
    logger.info("Stress Test - High Concurrency")
    
    concurrent_levels = [10, 25, 50, 100, 200]
    
    for concurrency in concurrent_levels:
        logger.info("Testing concurrency", extra={"concurrency": concurrency})
        
        times = []
        success_count = 0
        
        connector = aiohttp.TCPConnector(limit=concurrency + 50, limit_per_host=concurrency)
        timeout = aiohttp.ClientTimeout(total=60)
        
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            start_time = time.time()
            
            tasks = [
                test_endpoint(session, base_url, params)
                for _ in range(concurrency)
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            batch_time = time.time() - start_time
            
            for result in results:
                if isinstance(result, tuple):
                    time_taken, success = result
                    times.append(time_taken)
                    if success:
                        success_count += 1
        
        if times:
            success_rate = (success_count / len(times)) * 100
            avg_time = statistics.mean(times)
            throughput = concurrency / batch_time
            
            logger.info(
                "Batch results",
                extra={
                    "success_rate": round(success_rate, 1),
                    "avg_time": round(avg_time, 3),
                    "batch_time": round(batch_time, 3),
                    "throughput": round(throughput, 1),
                },
            )
            
            if success_rate < 95:
                logger.warning("High failure rate detected")
            if avg_time > 2.0:
                logger.warning("High response time detected")

if __name__ == "__main__":
    setup_logging()
    logger.info("360Ghar Property API Load Testing Suite")
    logger.info("Ensure server is running at http://localhost:8000")
    try:
        asyncio.run(load_test())
        asyncio.run(stress_test())
        logger.info("Load testing completed")
        logger.info(
            "Expected Performance Benchmarks",
            extra={
                "avg_ms": "<500",
                "p95_ms": "<1000",
                "success_rate_pct": ">99",
                "throughput_rps": ">100",
            },
        )
    except KeyboardInterrupt:
        logger.warning("Testing interrupted by user")
    except Exception as e:
        logger.exception(f"Testing failed: {e}")