"""Geospatial utility functions."""
from __future__ import annotations

# ---------------------------------------------------------------------------
# City alias mapping — common alternate names for Indian cities.
# Canonical (display) form is the value; alias is the key.
# Used by property search to normalize user input before filtering.
# ---------------------------------------------------------------------------
CITY_ALIASES: dict[str, str] = {
    # Karnataka
    "bangalore": "Bengaluru",
    "bengaluru": "Bengaluru",
    # Maharashtra
    "bombay": "Mumbai",
    "mumbai": "Mumbai",
    "pune": "Pune",
    "poona": "Pune",
    "nagpur": "Nagpur",
    # Tamil Nadu
    "madras": "Chennai",
    "chennai": "Chennai",
    # Delhi NCR
    "delhi": "Delhi",
    "new delhi": "Delhi",
    "ncr": "Delhi",
    "gurgaon": "Gurugram",
    "gurugram": "Gurugram",
    "noida": "Noida",
    "faridabad": "Faridabad",
    "ghaziabad": "Ghaziabad",
    # West Bengal
    "calcutta": "Kolkata",
    "kolkata": "Kolkata",
    # Telangana
    "hyderabad": "Hyderabad",
    # Rajasthan
    "jaipur": "Jaipur",
    "jodhpur": "Jodhpur",
    "udaipur": "Udaipur",
    # Gujarat
    "ahmedabad": "Ahmedabad",
    "ahemdabad": "Ahmedabad",
    "surat": "Surat",
    "vadodara": "Vadodara",
    "baroda": "Vadodara",
    # Uttar Pradesh
    "lucknow": "Lucknow",
    "agra": "Agra",
    "kanpur": "Kanpur",
    "varanasi": "Varanasi",
    "benaras": "Varanasi",
    # Kerala
    "kochi": "Kochi",
    "cochin": "Kochi",
    "trivandrum": "Thiruvananthapuram",
    "thiruvananthapuram": "Thiruvananthapuram",
    # Punjab
    "chandigarh": "Chandigarh",
    "ludhiana": "Ludhiana",
    "amritsar": "Amritsar",
    # Madhya Pradesh
    "bhopal": "Bhopal",
    "indore": "Indore",
    # Goa
    "goa": "Goa",
    "panaji": "Panaji",
    "panjim": "Panaji",
    # Bihar
    "patna": "Patna",
    # Odisha
    "bhubaneswar": "Bhubaneswar",
    # Assam
    "guwahati": "Guwahati",
}


def normalize_city(city: str) -> str:
    """Normalize a city name using the alias map.

    Returns the canonical city name if an alias matches, otherwise
    returns the title-cased input.
    """
    if not city:
        return city
    canonical = CITY_ALIASES.get(city.strip().lower())
    if canonical:
        return canonical
    return city.strip().title()


def wkt_point(longitude: float, latitude: float) -> str:
    """Build a PostGIS WKT POINT string with SRID=4326.

    Args:
        longitude: Longitude in degrees
        latitude: Latitude in degrees

    Returns:
        WKT string like 'SRID=4326;POINT(lon lat)'
    """
    return f"SRID=4326;POINT({longitude} {latitude})"
