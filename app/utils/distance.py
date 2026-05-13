import math


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great circle distance between two points on Earth using the Haversine formula.

    Args:
        lat1, lon1: Latitude and longitude of the first point (in decimal degrees)
        lat2, lon2: Latitude and longitude of the second point (in decimal degrees)

    Returns:
        Distance in kilometers
    """
    # Convert decimal degrees to radians
    lat1_rad, lon1_rad, lat2_rad, lon2_rad = map(math.radians, [lat1, lon1, lat2, lon2])

    # Haversine formula
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))

    # Radius of earth in kilometers
    earth_radius_km = 6371

    return c * earth_radius_km

def distance_in_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate distance in meters using Haversine formula.

    Returns:
        Distance in meters
    """
    return haversine_distance(lat1, lon1, lat2, lon2) * 1000

def are_coordinates_within_radius(lat1: float, lon1: float, lat2: float, lon2: float, radius_km: float) -> bool:
    """
    Check if two coordinates are within a specified radius.

    Args:
        lat1, lon1: First point coordinates
        lat2, lon2: Second point coordinates
        radius_km: Radius in kilometers

    Returns:
        True if points are within radius, False otherwise
    """
    distance = haversine_distance(lat1, lon1, lat2, lon2)
    return distance <= radius_km

def get_bounding_box(lat: float, lon: float, radius_km: float) -> tuple[float, float, float, float]:
    """
    Get approximate bounding box coordinates for a given center point and radius.
    Useful for efficient database queries to pre-filter results before exact distance calculation.

    Args:
        lat, lon: Center point coordinates
        radius_km: Radius in kilometers

    Returns:
        Tuple of (min_lat, max_lat, min_lon, max_lon)
    """
    # Rough approximation: 1 degree of latitude ≈ 111 km
    # 1 degree of longitude ≈ 111 km * cos(latitude)
    lat_delta = radius_km / 111.0
    lon_delta = radius_km / (111.0 * math.cos(math.radians(lat)))

    return (
        lat - lat_delta,  # min_lat
        lat + lat_delta,  # max_lat
        lon - lon_delta,  # min_lon
        lon + lon_delta   # max_lon
    )
