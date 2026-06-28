"""
ActivityLoader — loads Category 3 (simulated user activity) data.

Reads from generated/ or generates at runtime using IDs from
categories 1 & 2 via the shared IDMap.
"""

from __future__ import annotations

import asyncio
import importlib

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.agents import AgentInteraction
from app.models.ai_conversations import AIConversation, AIConversationMessage
from app.models.conversations import Conversation, ConversationParticipant
from app.models.conversations import Message as UserMessage
from app.models.data_hub import AuctionAlert
from app.models.properties import Visit
from app.models.social import (
    FlatmateProfileViewEvent,
    FlatmateSuperLikeUsage,
    MatchQnAAnswer,
    UserBlock,
    UserMatch,
    UserReport,
)
from app.models.tours import TourAnalyticsEvent
from app.models.users import UserSearchHistory, UserSwipe

_base = importlib.import_module("seed_data.loaders.01_base")
SEED_DATA_DIR = _base.SEED_DATA_DIR
SimpleLoader = _base.SimpleLoader
IDMap = _base.IDMap
load_json = _base.load_json
resolve_refs = _base.resolve_refs

logger = get_logger(__name__)

GENERATED_DIR = SEED_DATA_DIR / "generated"


async def load_all_activity(id_map: IDMap) -> dict[str, dict[str, int]]:
    """Load all Category 3 generated activity data."""
    results: dict[str, dict[str, int]] = {}

    # ── Swipes (property) ────────────────────────────────────────
    swipe_records = load_json(GENERATED_DIR / "01_swipes.json")
    resolved = [resolve_refs(r, id_map, model=UserSwipe) for r in swipe_records]
    results["swipes"] = await SimpleLoader(UserSwipe, []).load(resolved)

    # ── Matches ──────────────────────────────────────────────────
    match_records = load_json(GENERATED_DIR / "02_matches.json")
    created_matches = 0
    async with AsyncSessionLocal() as session:
        for data in match_records:
            match_ref = data.pop("_match_ref", None)
            clean = resolve_refs(data, id_map, model=UserMatch)
            u1 = clean.get("user_one_id")
            u2 = clean.get("user_two_id")
            if not u1 or not u2:
                continue
            stmt = select(UserMatch).where(UserMatch.user_one_id == u1, UserMatch.user_two_id == u2)
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if existing:
                if match_ref:
                    id_map.put("match", match_ref, existing.id)
                continue
            record = UserMatch(**clean)
            session.add(record)
            await session.flush()
            if match_ref:
                id_map.put("match", match_ref, record.id)
            created_matches += 1
        await session.commit()
    results["matches"] = {"created": created_matches, "skipped": 0}

    # ── Match QnA answers ────────────────────────────────────────
    qna_records = load_json(GENERATED_DIR / "03_match_qna.json")
    resolved_qna = [resolve_refs(r, id_map, model=MatchQnAAnswer) for r in qna_records]
    results["match_qna"] = await SimpleLoader(MatchQnAAnswer, []).load(resolved_qna)

    # ── Conversations ────────────────────────────────────────────
    conv_records = load_json(GENERATED_DIR / "04_conversations.json")
    participant_records = load_json(GENERATED_DIR / "04b_conversation_participants.json")
    created_conv = 0
    async with AsyncSessionLocal() as session:
        for data in conv_records:
            conv_ref = data.pop("_conv_ref", None)
            clean = resolve_refs(data, id_map, model=Conversation)
            created_by = clean.get("created_by_user_id")
            if not created_by:
                continue
            # Dedupe: check if a conversation already exists for this creator + source
            conv_stmt = select(Conversation).where(
                Conversation.created_by_user_id == created_by,
                Conversation.source == clean.get("source"),
            )
            existing_conv = (await session.execute(conv_stmt)).scalar_one_or_none()
            if existing_conv:
                if conv_ref:
                    id_map.put("conversation", conv_ref, existing_conv.id)
                continue
            conv_record = Conversation(**clean)
            session.add(conv_record)
            await session.flush()
            if conv_ref:
                id_map.put("conversation", conv_ref, conv_record.id)
            created_conv += 1
        await session.commit()
    results["conversations"] = {"created": created_conv, "skipped": 0}

    # ── Conversation participants ────────────────────────────────
    created_cp = 0
    async with AsyncSessionLocal() as session:
        for data in participant_records:
            conv_ref = data.pop("conversation_id_ref", None)
            user_ref = data.pop("user_id_ref", None)
            conv_id = id_map.get("conversation", conv_ref) if conv_ref else None
            user_id = id_map.get("user", user_ref) if user_ref else None
            if not conv_id or not user_id:
                continue
            # Dedupe: skip if participant already exists
            cp_stmt = select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == conv_id,
                ConversationParticipant.user_id == user_id,
            )
            existing_cp = (await session.execute(cp_stmt)).scalar_one_or_none()
            if existing_cp:
                continue
            cp_clean = {"conversation_id": conv_id, "user_id": user_id}
            if data.get("role"):
                cp_clean["role"] = data["role"]
            cp_record = ConversationParticipant(**cp_clean)
            session.add(cp_record)
            created_cp += 1
        await session.commit()
    results["conversation_participants"] = {"created": created_cp, "skipped": 0}

    # ── Messages ─────────────────────────────────────────────────
    msg_records = load_json(GENERATED_DIR / "05_messages.json")
    resolved_msg = [resolve_refs(r, id_map, model=UserMessage) for r in msg_records]

    # ── Super like usage ─────────────────────────────────────────
    sl_records = load_json(GENERATED_DIR / "06_super_like_usage.json")
    resolved_sl = [resolve_refs(r, id_map, model=FlatmateSuperLikeUsage) for r in sl_records]

    # ── Blocks ────────────────────────────────────────────────────
    block_records = load_json(GENERATED_DIR / "07_blocks.json")
    resolved_blocks = [resolve_refs(r, id_map, model=UserBlock) for r in block_records]

    # ── Reports ──────────────────────────────────────────────────
    report_records = load_json(GENERATED_DIR / "08_reports.json")
    resolved_reports = [resolve_refs(r, id_map, model=UserReport) for r in report_records]

    # ── Profile view events ──────────────────────────────────────
    pve_records = load_json(GENERATED_DIR / "09_profile_view_events.json")
    resolved_pve = [resolve_refs(r, id_map, model=FlatmateProfileViewEvent) for r in pve_records]

    # ── Visits (flatmate_meet) ────────────────────────────────────
    fvisit_records = load_json(GENERATED_DIR / "10_flatmate_visits.json")
    resolved_fv = [resolve_refs(r, id_map, model=Visit) for r in fvisit_records]

    # ── Agent interactions ───────────────────────────────────────
    ai_records = load_json(GENERATED_DIR / "11_agent_interactions.json")
    resolved_ai = [resolve_refs(r, id_map, model=AgentInteraction) for r in ai_records]

    # ── User search history ──────────────────────────────────────
    sh_records = load_json(GENERATED_DIR / "12_search_history.json")
    resolved_sh = [resolve_refs(r, id_map, model=UserSearchHistory) for r in sh_records]

    # ── Tour analytics ───────────────────────────────────────────
    ta_records = load_json(GENERATED_DIR / "13_tour_analytics.json")
    resolved_ta = [resolve_refs(r, id_map, model=TourAnalyticsEvent) for r in ta_records]

    # ── Auction alerts ───────────────────────────────────────────
    aa_records = load_json(GENERATED_DIR / "15_auction_alerts.json")
    resolved_aa = [resolve_refs(r, id_map, model=AuctionAlert) for r in aa_records]

    # ── Parallel load: all independent after matches+conversations ──
    async def _safe_load(key: str, coro):
        try:
            return key, await coro
        except Exception as exc:
            logger.warning("Skipping %s: %s", key, exc)
            return key, {"created": 0, "skipped": 0}

    parallel_tasks = [
        _safe_load("messages", SimpleLoader(UserMessage, []).load(resolved_msg)),
        _safe_load("super_like_usage", SimpleLoader(FlatmateSuperLikeUsage, []).load(resolved_sl)),
        _safe_load("blocks", SimpleLoader(UserBlock, []).load(resolved_blocks)),
        _safe_load("reports", SimpleLoader(UserReport, []).load(resolved_reports)),
        _safe_load("profile_view_events", SimpleLoader(FlatmateProfileViewEvent, []).load(resolved_pve)),
        _safe_load("flatmate_visits", SimpleLoader(Visit, []).load(resolved_fv)),
        _safe_load("agent_interactions", SimpleLoader(AgentInteraction, []).load(resolved_ai)),
        _safe_load("search_history", SimpleLoader(UserSearchHistory, []).load(resolved_sh)),
        _safe_load("tour_analytics", SimpleLoader(TourAnalyticsEvent, []).load(resolved_ta)),
        _safe_load("auction_alerts", SimpleLoader(AuctionAlert, []).load(resolved_aa)),
    ]
    parallel_results = await asyncio.gather(*parallel_tasks)
    for key, res in parallel_results:
        results[key] = res

    # ── AI conversations (sequential — needs flush for FK) ────────
    try:
        aic_records = load_json(GENERATED_DIR / "14_ai_conversations.json")
        created_aic = 0
        async with AsyncSessionLocal() as session:
            for data in aic_records:
                try:
                    messages = data.pop("_messages", [])
                    clean = resolve_refs(data, id_map, model=AIConversation)
                    if not clean.get("user_id"):
                        logger.debug("Skipping AI conversation: user_id_ref %s not in IDMap", data.get("user_id_ref"))
                        continue
                    record = AIConversation(**clean)
                    session.add(record)
                    await session.flush()
                    for msg in messages:
                        msg["conversation_id"] = record.id
                        session.add(AIConversationMessage(**msg))
                    created_aic += 1
                except Exception as aic_exc:
                    logger.warning("Skipping AI conversation record: %s", aic_exc)
                    await session.rollback()
                    continue
            await session.commit()
        results["ai_conversations"] = {"created": created_aic, "skipped": 0}
    except Exception as exc:
        logger.warning("Skipping ai_conversations: %s", exc)
        results["ai_conversations"] = {"created": 0, "skipped": 0}

    return results
