"""
Tests for app.models.tours module — Tour, Scene, Hotspot, etc.
"""


from app.models.enums import HotspotType, TourStatus, TourVisibility
from app.models.tours import AIJob, Hotspot, MediaFile, Scene, Tour


class TestTourModel:
    """Tests for Tour model."""

    def test_tablename(self):
        assert Tour.__tablename__ == "tours"

    def test_default_status(self):
        assert Tour.status.default.arg == TourStatus.draft

    def test_default_visibility(self):
        assert Tour.visibility.default.arg == TourVisibility.private

    def test_has_required_columns(self):
        columns = {c.name for c in Tour.__table__.columns}
        assert {"id", "user_id", "title", "status", "visibility"}.issubset(columns)


class TestSceneModel:
    """Tests for Scene model."""

    def test_tablename(self):
        assert Scene.__tablename__ == "scenes"

    def test_has_required_columns(self):
        columns = {c.name for c in Scene.__table__.columns}
        assert {"id", "tour_id", "title"}.issubset(columns)


class TestHotspotModel:
    """Tests for Hotspot model."""

    def test_tablename(self):
        assert Hotspot.__tablename__ == "hotspots"

    def test_default_type_is_info(self):
        assert Hotspot.type.default.arg == HotspotType.info

    def test_default_is_active(self):
        assert Hotspot.is_active.default.arg is True

    def test_default_order_index(self):
        assert Hotspot.order_index.default.arg == 0

    def test_has_required_columns(self):
        columns = {c.name for c in Hotspot.__table__.columns}
        assert {"id", "scene_id", "type", "position"}.issubset(columns)


class TestAIJobModel:
    """Tests for AIJob model."""

    def test_tablename(self):
        assert AIJob.__tablename__ == "ai_jobs"

    def test_has_required_columns(self):
        columns = {c.name for c in AIJob.__table__.columns}
        assert {"id", "tour_id", "status"}.issubset(columns)


class TestMediaFileModel:
    """Tests for MediaFile model."""

    def test_tablename(self):
        assert MediaFile.__tablename__ == "media_files"

    def test_has_required_columns(self):
        columns = {c.name for c in MediaFile.__table__.columns}
        assert {"id", "tour_id", "file_url"}.issubset(columns)
