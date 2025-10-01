"""FAQ data populator that loads FAQs from JSON."""
import json
from typing import Optional, List, Dict, Any
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.models.core import FAQ
from .base import BasePopulator


class FAQPopulator(BasePopulator):
    """Populates FAQs in the database from JSON seed data."""

    def __init__(self):
        super().__init__()

    @property
    def model_class(self):
        return FAQ

    @property
    def unique_fields(self) -> List[str]:
        return ['question']  # FAQs are unique by question

    def _default_faqs_path(self) -> str:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base_dir, "data", "faqs.json")

    def _load_faqs_from_file(self, file_path: Optional[str] = None) -> List[Dict[str, Any]]:
        """Load FAQ definitions from JSON."""
        path = file_path or self._default_faqs_path()
        if not os.path.exists(path):
            raise FileNotFoundError(f"FAQ JSON not found at: {path}")
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, list):
            raise ValueError("faqs.json must contain a list of FAQ objects")
        return data

    def _prepare_faq_payload(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize FAQ payload prior to database insertion/update."""
        payload = dict(raw)

        # Default toggles for optional fields
        payload.setdefault("category", None)
        payload.setdefault("tags", None)
        payload.setdefault("display_order", 0)
        payload.setdefault("is_active", True)

        return payload

    async def populate_from_json(
        self,
        count: Optional[int] = None,
        file_path: Optional[str] = None,
        update_existing: bool = False,
    ) -> Dict[str, int]:
        """Create (and optionally update) FAQs from JSON seed data with duplicate checking."""
        faqs_data = self._load_faqs_from_file(file_path)

        if count is not None:
            faqs_data = faqs_data[:count]

        # Prepare FAQ payloads
        processed_data = []
        for faq_data in faqs_data:
            try:
                question = faq_data.get("question")
                if not question:
                    self.logger.warning("Skipping FAQ without a question in JSON data")
                    continue

                payload = self._prepare_faq_payload(faq_data)
                processed_data.append(payload)

            except Exception as exc:
                self.logger.error(f"Failed to prepare FAQ payload: {exc}")
                continue

        # For updates, we need special handling since the base class doesn't support updates
        if update_existing:
            return await self._populate_with_updates(processed_data)
        else:
            return await self.populate(processed_data, skip_existing=True)

    async def _populate_with_updates(self, faq_data_list: List[Dict[str, Any]]) -> Dict[str, int]:
        """Handle FAQ population with updates for existing records."""
        from sqlalchemy import update

        created_count = 0
        updated_count = 0
        skipped_count = 0

        self.logger.info(f"Processing {len(faq_data_list)} FAQs with update support...")

        async with await self.get_db_session() as session:
            try:
                for faq_data in faq_data_list:
                    try:
                        question = faq_data.get("question")
                        if not question:
                            continue

                        # Check if exists
                        existing = await self._record_exists(session, faq_data)

                        if existing:
                            # Update existing record
                            # We need to find the existing record to get its ID
                            from sqlalchemy import select
                            result = await session.execute(
                                select(FAQ).where(FAQ.question == question)
                            )
                            existing_faq = result.scalar_one()

                            await session.execute(
                                update(FAQ)
                                .where(FAQ.id == existing_faq.id)
                                .values(**faq_data)
                            )
                            updated_count += 1
                            self.logger.debug(f"Updated FAQ: {question}")
                        else:
                            # Create new record
                            await self._create_record(session, faq_data)
                            created_count += 1

                    except Exception as exc:
                        self.logger.error(f"Failed to process FAQ: {exc}")
                        continue

                    # Commit in batches
                    if (created_count + updated_count + skipped_count) % 50 == 0:
                        await session.commit()

                await session.commit()
                self.logger.info(f"FAQ processing complete: {created_count} created, {updated_count} updated, {skipped_count} skipped")

            except Exception as exc:
                await session.rollback()
                self.logger.error(f"FAQ population failed: {exc}")
                raise

        return {"created": created_count, "updated": updated_count, "skipped": skipped_count}
