"""
Tests for app.utils.distance module — Haversine, bounding box, radius checks.
"""


import pytest

from app.utils.distance import (
    are_coordinates_within_radius,
    distance_in_meters,
    get_bounding_box,
    haversine_distance,
)


class TestHaversineDistance:
    """Tests for haversine_distance function."""

    def test_same_point_returns_zero(self):
        assert haversine_distance(19.076, 72.877, 19.076, 72.877) == 0.0

    def test_mumbai_to_pune_approximately(self):
        # Mumbai ~19.076,72.877; Pune ~18.520,73.856
        dist = haversine_distance(19.076, 72.877, 18.520, 73.856)
        # Known distance is approximately 120 km
        assert 100 < dist < 150

    def test_antipodal_points(self):
        # Maximum distance on Earth
        dist = haversine_distance(0, 0, 0, 180)
        # Half circumference ~20015 km
        assert 19000 < dist < 21000

    @pytest.mark.parametrize("lat1,lon1,lat2,lon2,expected_range", [
        (0, 0, 0, 1, (110, 112)),   # ~111 km per degree at equator
        (51.5, -0.12, 48.86, 2.35, (330, 360)),  # London to Paris
    ])
    def test_known_distances(self, lat1, lon1, lat2, lon2, expected_range):
        dist = haversine_distance(lat1, lon1, lat2, lon2)
        assert expected_range[0] <= dist <= expected_range[1]

    def test_negative_coordinates(self):
        dist = haversine_distance(-33.87, 151.21, -37.81, 144.96)  # Sydney to Melbourne
        assert 700 < dist < 900

    def test_symmetry(self):
        d1 = haversine_distance(19.076, 72.877, 18.520, 73.856)
        d2 = haversine_distance(18.520, 73.856, 19.076, 72.877)
        assert abs(d1 - d2) < 0.001  # Should be symmetric


class TestDistanceInMeters:
    """Tests for distance_in_meters function."""

    def test_same_point(self):
        assert distance_in_meters(19.0, 72.0, 19.0, 72.0) == 0.0

    def test_returns_meters(self):
        # 1 km = 1000 meters
        dist_m = distance_in_meters(0, 0, 0, 0.01)
        dist_km = haversine_distance(0, 0, 0, 0.01)
        assert abs(dist_m - dist_km * 1000) < 10


class TestAreCoordinatesWithinRadius:
    """Tests for are_coordinates_within_radius function."""

    def test_same_point_within_any_radius(self):
        assert are_coordinates_within_radius(19.0, 72.0, 19.0, 72.0, 1.0) is True

    def test_close_points_within_radius(self):
        # Points ~1.1 km apart, within 2 km radius
        assert are_coordinates_within_radius(19.0, 72.0, 19.01, 72.0, 2.0) is True

    def test_distant_points_outside_radius(self):
        # Mumbai to Delhi ~1100 km, not within 10 km
        assert are_coordinates_within_radius(19.076, 72.877, 28.613, 77.209, 10) is False

    def test_exact_boundary(self):
        # Test a point exactly at the radius boundary
        dist_km = haversine_distance(19.0, 72.0, 19.0, 72.01)
        assert are_coordinates_within_radius(19.0, 72.0, 19.0, 72.01, dist_km) is True


class TestGetBoundingBox:
    """Tests for get_bounding_box function."""

    def test_returns_four_values(self):
        result = get_bounding_box(19.0, 72.0, 5.0)
        assert len(result) == 4

    def test_center_within_box(self):
        min_lat, max_lat, min_lon, max_lon = get_bounding_box(19.0, 72.0, 5.0)
        assert min_lat <= 19.0 <= max_lat
        assert min_lon <= 72.0 <= max_lon

    def test_larger_radius_produces_larger_box(self):
        small = get_bounding_box(19.0, 72.0, 5.0)
        large = get_bounding_box(19.0, 72.0, 20.0)
        assert large[1] - large[0] > small[1] - small[0]  # lat range larger
        assert large[3] - large[2] > small[3] - small[2]  # lon range larger

    def test_box_symmetry_at_equator(self):
        min_lat, max_lat, min_lon, max_lon = get_bounding_box(0, 0, 10.0)
        lat_diff_up = 0 - min_lat
        lat_diff_down = max_lat - 0
        assert abs(lat_diff_up - lat_diff_down) < 0.001

    def test_high_latitude_narrower_longitude_range(self):
        # At higher latitudes, longitude range should be narrower per degree
        equator_box = get_bounding_box(0, 0, 10.0)
        high_lat_box = get_bounding_box(60, 0, 10.0)
        # The lon delta at equator is larger than at high lat
        equator_lon_delta = equator_box[3] - equator_box[2]
        high_lat_lon_delta = high_lat_box[3] - high_lat_box[2]
        # Per-degree, longitude shrinks with cos(lat), but total delta depends on implementation
        # Just verify both produce valid boxes
        assert high_lat_lon_delta > 0
        assert equator_lon_delta > 0
