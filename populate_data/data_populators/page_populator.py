"""
Page data populator for creating/updating CMS-like pages from JSON
"""
from __future__ import annotations

import json
import os
from typing import Optional, List, Dict, Any

from sqlalchemy import select, delete, update

# Ensure project root is on path (similar to other populators)
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.core.logging import get_logger
from app.models.core import Page
from app.models.enums import PageFormat
from .base import BasePopulator


logger = get_logger(__name__)


class PagePopulator(BasePopulator):
    """Populates pages from a JSON file."""

    def __init__(self):
        super().__init__()

    @property
    def model_class(self):
        return Page

    @property
    def unique_fields(self) -> List[str]:
        return ['unique_name']  # Pages are unique by unique_name

    def _default_pages_path(self) -> str:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # populate_data/
        return os.path.join(base_dir, "data", "pages.json")

    def _load_pages_from_file(self, file_path: Optional[str] = None) -> List[Dict[str, Any]]:
        path = file_path or self._default_pages_path()
        if not os.path.exists(path):
            raise FileNotFoundError(f"Pages JSON not found at: {path}")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError("pages.json must contain a list of page objects")
        return data

    async def populate_from_json(
        self,
        count: Optional[int] = None,
        file_path: Optional[str] = None,
        update_existing: bool = False,
    ) -> Dict[str, int]:
        """
        Create (and optionally update) pages from JSON with duplicate checking.

        Args:
            count: Optional cap on number of pages to create.
            file_path: Optional path to pages.json. Defaults to populate_data/data/pages.json
            update_existing: If True, update existing pages instead of skipping.

        Returns:
            Dict with counts of created, updated, and skipped pages.
        """
        pages_data = self._load_pages_from_file(file_path)

        if count is not None:
            pages_data = pages_data[:count]

        # Prepare page payloads
        processed_data = []
        for page in pages_data:
            try:
                unique_name = page.get("unique_name")
                if not unique_name:
                    self.logger.warning("Skipping page without 'unique_name'")
                    continue

                # Normalize/validate format
                fmt_value = page.get("format", "html")
                try:
                    page_format = PageFormat(fmt_value)
                except Exception:
                    self.logger.warning(
                        f"Invalid format '{fmt_value}' for page '{unique_name}'; defaulting to 'html'"
                    )
                    page_format = PageFormat.html

                # Prepare page data
                page_data = {
                    "unique_name": unique_name,
                    "title": page.get("title", unique_name.replace("-", " ").title()),
                    "content": page.get("content", ""),
                    "format": page_format,
                    "custom_config": page.get("custom_config"),
                    "is_active": page.get("is_active", True),
                    "is_draft": page.get("is_draft", False),
                    "is_private": page.get("is_private", True),
                }
                processed_data.append(page_data)

            except Exception as exc:
                self.logger.error(f"Failed to prepare page payload: {exc}")
                continue

        # For updates, we need special handling since the base class doesn't support updates
        if update_existing:
            return await self._populate_with_updates(processed_data)
        else:
            return await self.populate(processed_data, skip_existing=True)

    async def _populate_with_updates(self, page_data_list: List[Dict[str, Any]]) -> Dict[str, int]:
        """Handle page population with updates for existing records."""
        created_count = 0
        updated_count = 0
        skipped_count = 0

        self.logger.info(f"Processing {len(page_data_list)} pages with update support...")

        async with await self.get_db_session() as session:
            try:
                for page_data in page_data_list:
                    try:
                        unique_name = page_data.get("unique_name")
                        if not unique_name:
                            continue

                        # Check if exists
                        existing = await self._record_exists(session, page_data)

                        if existing:
                            # Update existing record
                            result = await session.execute(
                                select(Page).where(Page.unique_name == unique_name)
                            )
                            existing_page = result.scalar_one()

                            await session.execute(
                                update(Page)
                                .where(Page.id == existing_page.id)
                                .values(**page_data)
                            )
                            updated_count += 1
                            self.logger.debug(f"Updated page: {unique_name}")
                        else:
                            # Create new record
                            await self._create_record(session, page_data)
                            created_count += 1

                    except Exception as exc:
                        self.logger.error(f"Failed to process page: {exc}")
                        continue

                    # Commit in batches
                    if (created_count + updated_count + skipped_count) % 50 == 0:
                        await session.commit()

                await session.commit()
                self.logger.info(f"Page processing complete: {created_count} created, {updated_count} updated, {skipped_count} skipped")

            except Exception as exc:
                await session.rollback()
                self.logger.error(f"Page population failed: {exc}")
                raise

        return {"created": created_count, "updated": updated_count, "skipped": skipped_count}

    async def clear_all(self) -> int:
        """Delete all pages."""
        try:
            async with await self.get_db_session() as session:
                result = await session.execute(delete(Page))
                deleted = result.rowcount or 0
                await session.commit()
                self.logger.info(f"Deleted {deleted} pages")
                return deleted
        except Exception as e:
            logger.error(f"Failed to clear pages: {str(e)}")
            return 0
