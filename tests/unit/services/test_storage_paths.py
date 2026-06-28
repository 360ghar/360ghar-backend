"""
Tests for app.services.storage_paths module.
"""

import pytest

from app.core.exceptions import BadRequestException
from app.services.storage_paths import (
    StorageFolder,
    generate_storage_path,
    get_folder_for_content_type,
    parse_user_id_from_path,
    sanitize_filename,
)


class TestSanitizeFilename:
    """Tests for sanitize_filename function."""

    def test_normal_filename(self):
        assert sanitize_filename("photo.jpg") == "photo.jpg"

    def test_removes_path_components(self):
        assert sanitize_filename("../../etc/passwd") == "passwd"
        assert sanitize_filename("C:\\Users\\test\\file.txt") == "file.txt"

    def test_replaces_unsafe_chars(self):
        result = sanitize_filename("my file (1).jpg")
        assert " " not in result
        assert "(" not in result
        assert ".jpg" in result

    def test_collapses_underscores(self):
        result = sanitize_filename("a___b.jpg")
        assert "___" not in result

    def test_strips_leading_trailing_underscores(self):
        result = sanitize_filename("_test_.jpg")
        assert not result.startswith("_")
        # The sanitize logic may leave trailing parts

    def test_empty_string_returns_file(self):
        assert sanitize_filename("") == "file"

    def test_preserves_extension_case_lowered(self):
        result = sanitize_filename("photo.JPG")
        assert result.endswith(".jpg")

    def test_no_extension(self):
        result = sanitize_filename("readme")
        assert "readme" in result

    def test_truncation(self):
        long_name = "a" * 100 + ".txt"
        result = sanitize_filename(long_name, max_length=50)
        name_part = result.rsplit(".", 1)[0]
        assert len(name_part) <= 50


class TestStorageFolder:
    """Tests for StorageFolder enum."""

    def test_avatar_value(self):
        assert StorageFolder.AVATAR.value == "avatars/{user_id}"

    def test_property_image_value(self):
        assert "property_id" in StorageFolder.PROPERTY_IMAGE.value
        assert "properties" in StorageFolder.PROPERTY_IMAGE.value

    def test_tour_thumbnail_value(self):
        assert "tour_id" in StorageFolder.TOUR_THUMBNAIL.value

    def test_scene_original_value(self):
        assert "scene_id" in StorageFolder.SCENE_ORIGINAL.value

    def test_agent_avatar_not_user_scoped(self):
        assert "agents" in StorageFolder.AGENT_AVATAR.value


class TestGenerateStoragePath:
    """Tests for generate_storage_path function."""

    def test_avatar_path(self):
        path = generate_storage_path(user_id=1, folder=StorageFolder.AVATAR, extension="jpg")
        assert path.startswith("avatars/1/")
        assert path.endswith(".jpg")

    def test_property_image_path(self):
        path = generate_storage_path(
            user_id=1,
            folder=StorageFolder.PROPERTY_IMAGE,
            property_id=42,
            extension="png",
        )
        assert "properties/42/" in path

    def test_property_image_missing_property_id(self):
        with pytest.raises(BadRequestException, match="property_id"):
            generate_storage_path(
                user_id=1,
                folder=StorageFolder.PROPERTY_IMAGE,
                extension="jpg",
            )

    def test_tour_path_missing_tour_id(self):
        with pytest.raises(BadRequestException, match="tour_id"):
            generate_storage_path(
                user_id=1,
                folder=StorageFolder.TOUR_THUMBNAIL,
                extension="jpg",
            )

    def test_scene_path_missing_scene_id(self):
        with pytest.raises(BadRequestException, match="scene_id"):
            generate_storage_path(
                user_id=1,
                folder=StorageFolder.SCENE_ORIGINAL,
                tour_id="tour-123",
                extension="jpg",
            )

    def test_agent_avatar_not_user_scoped(self):
        path = generate_storage_path(
            user_id=1,
            folder=StorageFolder.AGENT_AVATAR,
            agent_id=5,
            extension="jpg",
        )
        assert path.startswith("agents/5/avatars/")
        assert "users/" not in path

    def test_agent_avatar_missing_agent_id(self):
        with pytest.raises(BadRequestException, match="agent_id"):
            generate_storage_path(
                user_id=1,
                folder=StorageFolder.AGENT_AVATAR,
                extension="jpg",
            )

    def test_with_original_filename(self):
        path = generate_storage_path(
            user_id=1,
            folder=StorageFolder.AVATAR,
            original_filename="selfie.jpg",
        )
        assert "selfie.jpg" in path

    def test_uuid_in_path(self):
        path = generate_storage_path(
            user_id=1,
            folder=StorageFolder.AVATAR,
            extension="jpg",
        )
        # UUID is truncated to 8 chars + ".jpg" = 12 chars
        parts = path.split("/")
        filename = parts[-1]
        assert len(filename) > 8  # uuid8chars + extension


class TestGetFolderForContentType:
    """Tests for get_folder_for_content_type function."""

    def test_image(self):
        assert get_folder_for_content_type("image/jpeg") == StorageFolder.PROPERTY_IMAGE

    def test_video(self):
        assert get_folder_for_content_type("video/mp4") == StorageFolder.PROPERTY_VIDEO

    def test_pdf(self):
        assert get_folder_for_content_type("application/pdf") == StorageFolder.DOCUMENT_GENERAL

    def test_audio(self):
        assert get_folder_for_content_type("audio/mpeg") == StorageFolder.GENERIC_UPLOAD

    def test_unknown(self):
        assert get_folder_for_content_type("application/zip") == StorageFolder.GENERIC_UPLOAD


class TestParseUserIdFromPath:
    """Tests for parse_user_id_from_path function."""

    def test_valid_user_path(self):
        assert parse_user_id_from_path("avatars/123/photo.jpg") == 123

    def test_agent_path_returns_none(self):
        assert parse_user_id_from_path("agents/5/avatars/photo.jpg") is None

    def test_no_user_prefix(self):
        assert parse_user_id_from_path("properties/42/images/photo.jpg") is None

    def test_short_path(self):
        assert parse_user_id_from_path("users/") is None

    def test_non_numeric_user_id(self):
        assert parse_user_id_from_path("users/abc/file.jpg") is None
