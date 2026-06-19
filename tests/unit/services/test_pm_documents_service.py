"""
Tests for app.services.pm_documents module — access control and creation.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import InsufficientPermissionsError, NotFoundException
from app.models.enums import DocumentType, UserRole
from app.models.users import User
from app.services.pm_documents import assert_can_access_document, create_document


class TestAssertCanAccessDocument:
    """Tests for document access control."""

    @pytest.mark.asyncio
    async def test_nonexistent_document_raises_not_found(self):
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)
        actor = User(id=1, supabase_user_id="abc", role=UserRole.admin.value, is_active=True)

        with pytest.raises(NotFoundException, match="Document not found"):
            await assert_can_access_document(db, actor=actor, document_id=999)

    @pytest.mark.asyncio
    async def test_admin_can_access_any_document(self):
        db = AsyncMock()
        mock_doc = MagicMock()
        mock_doc.owner_id = 99
        db.get = AsyncMock(return_value=mock_doc)
        actor = User(id=1, supabase_user_id="abc", role=UserRole.admin.value, is_active=True)

        result = await assert_can_access_document(db, actor=actor, document_id=1)
        assert result is mock_doc

    @pytest.mark.asyncio
    async def test_owner_can_access_own_document(self):
        db = AsyncMock()
        mock_doc = MagicMock()
        mock_doc.owner_id = 5
        db.get = AsyncMock(return_value=mock_doc)
        actor = User(id=5, supabase_user_id="abc", role=UserRole.user.value, is_active=True)

        result = await assert_can_access_document(db, actor=actor, document_id=1)
        assert result is mock_doc

    @pytest.mark.asyncio
    async def test_non_owner_non_admin_rejected(self):
        db = AsyncMock()
        mock_doc = MagicMock()
        mock_doc.owner_id = 99
        mock_doc.shared_with_tenant = False
        mock_doc.lease_id = None
        db.get = AsyncMock(return_value=mock_doc)
        actor = User(id=5, supabase_user_id="abc", role=UserRole.user.value, is_active=True)

        with pytest.raises(InsufficientPermissionsError):
            await assert_can_access_document(db, actor=actor, document_id=1)


class TestCreateDocument:
    """Tests for document creation."""

    @pytest.mark.asyncio
    async def test_create_document_success(self):
        db = AsyncMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        actor = User(id=1, supabase_user_id="abc", role=UserRole.admin.value, is_active=True)

        with patch("app.services.pm_documents.assert_can_manage_owner_portfolio", new_callable=AsyncMock):
            doc = await create_document(
                db,
                actor=actor,
                owner_id=1,
                document_type=DocumentType.lease_agreement,
                title="Lease Agreement",
                file_url="https://storage.example.com/lease.pdf",
            )
            db.add.assert_called_once()
            db.flush.assert_awaited_once()
