#!/usr/bin/env python3
"""
Generate Category 3 simulated user activity.

Creates random but realistic user interactions: swipes, matches,
conversations, messages, visits, analytics, etc.

Uses IDs from Categories 1 & 2 via the IDMap populated during loading.

Usage:
    python -m seed_data.generators.generate_activity
    python seed_data/generators/generate_activity.py
"""

from __future__ import annotations

import json
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from seed_data.shared import (
    ALL_AGENT_NAMES,
    BANKS,
    CITIES,
    HC_DIR_PROPERTY_TITLES,
)

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"
GENERATED_DIR = Path(__file__).resolve().parent.parent / "generated"


def _rand_dt(days_back: int = 30) -> str:
    d = datetime.now(timezone.utc) - timedelta(days=random.randint(0, days_back), hours=random.randint(0, 23))
    return d.isoformat()


def _rand_date(days_back: int = 365) -> str:
    d = datetime.now(timezone.utc).date() - timedelta(days=random.randint(0, days_back))
    return d.isoformat()


def load_seed_users() -> list[dict[str, Any]]:
    """Load seed user emails for generating activity refs."""
    path = SEED_DIR / "01_users.json"
    if not path.exists():
        return []
    with open(path) as f:
        return json.load(f)


def load_seed_properties() -> list[dict[str, Any]]:
    """Property titles for generating activity refs.

    The catalog is the 109 real hardcoded properties (synthetic seed-property
    creation is disabled and ``seed/03_properties.json`` is now empty), so
    activity (swipes, flatmate visits) references those titles. Returns dicts
    shaped ``{"title": ...}`` to match the ``generate_*`` consumers.
    """
    return [{"title": t} for t in HC_DIR_PROPERTY_TITLES]


def load_seed_tours() -> list[dict[str, Any]]:
    """Load seed tour IDs for generating analytics."""
    path = SEED_DIR / "07_tours.json"
    if not path.exists():
        return []
    with open(path) as f:
        return json.load(f)


def generate_swipes(users: list[dict], properties: list[dict]) -> list[dict]:
    """Generate property and flatmate swipes."""
    swipes = []
    user_emails = [u["email"] for u in users]
    prop_titles = [p["title"] for p in properties]

    # Property swipes
    for _ in range(150):
        swipes.append({
            "user_id_ref": random.choice(user_emails),
            "property_id_ref": random.choice(prop_titles),
            "target_type": "property",
            "swipe_action": random.choice(["like", "like", "like", "pass", "super_like"]),
            "is_liked": random.random() < 0.6,
        })

    # Flatmate swipes (user-to-user)
    for _ in range(100):
        u1, u2 = random.sample(user_emails, 2)
        swipes.append({
            "user_id_ref": u1,
            "target_user_id_ref": u2,
            "target_type": "user",
            "swipe_action": random.choice(["like", "pass", "super_like"]),
            "is_liked": random.random() < 0.5,
        })

    return swipes


def generate_matches(users: list[dict]) -> list[dict]:
    """Generate flatmate matches from mutual likes."""
    user_emails = [u["email"] for u in users]
    matches = []
    for i in range(25):
        u1, u2 = random.sample(user_emails, 2)
        matches.append({
            "_match_ref": f"match_{i+1:03d}",
            "user_one_id_ref": min(u1, u2),  # Consistent ordering
            "user_two_id_ref": max(u1, u2),
            "status": "active",
        })
    return matches


def generate_conversations(users: list[dict], matches: list[dict]) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """Generate conversations, participants, messages, and QnA answers from matches."""
    convs = []
    participants = []
    messages = []
    qna_answers = []

    for i, match in enumerate(matches[:10]):
        u1 = match["user_one_id_ref"]
        u2 = match["user_two_id_ref"]
        conv_ref = f"conv_{i+1:03d}"
        source = random.choice(["listing_interest", "profile_match"])

        convs.append({
            "_conv_ref": conv_ref,
            "app": "flatmates",
            "created_by_user_id_ref": u1,
            "source": source,
            "status": random.choice(["active", "active", "active", "archived"]),
            "last_message_preview": None,
        })

        # Add both users as conversation participants
        participants.append({
            "conversation_id_ref": conv_ref,
            "user_id_ref": u1,
            "role": "admin" if u1 == match.get("created_by_user_id_ref", u1) else "member",
        })
        participants.append({
            "conversation_id_ref": conv_ref,
            "user_id_ref": u2,
            "role": "member",
        })

        # Generate 2-8 messages per conversation
        for j in range(random.randint(2, 8)):
            sender = random.choice([u1, u2])
            msgs = [
                "Hi! I saw your profile on 360Ghar. Are you still looking?",
                "Yes, I'm interested! What's your budget range?",
                "I'm looking at around 15-25k per month. What about you?",
                "That works for me! When are you planning to move?",
                "Within the next month. Should we schedule a visit?",
                "Sure, let me check my schedule and get back to you.",
                "Sounds great! Looking forward to it.",
                "Thanks for connecting! Let me know if you have any questions.",
            ]
            messages.append({
                "conversation_id_ref": conv_ref,
                "sender_id_ref": sender,
                "body": msgs[j % len(msgs)],
                "message_type": "text",
                "read_at": _rand_dt(15) if random.random() < 0.7 else None,
            })

        # QnA answers for some matches
        if random.random() < 0.7:
            match_ref = match.get("_match_ref", f"match_{i+1:03d}")
            qna_answers.append({
                "match_id_ref": match_ref,
                "user_id_ref": u1,
                "q1": random.choice(["Netflix & chill", "Going out with friends", "Outdoor activities"]),
                "q2": random.choice(["Love them!", "Fine with them", "Not a fan"]),
                "q3": random.choice(["Cleanliness", "Respect for privacy", "Good communication"]),
            })
            qna_answers.append({
                "match_id_ref": match_ref,
                "user_id_ref": u2,
                "q1": random.choice(["Netflix & chill", "Outdoor activities", "Working on side projects"]),
                "q2": random.choice(["Love them!", "Fine with them"]),
                "q3": random.choice(["Cleanliness", "Similar lifestyle"]),
            })

    return convs, participants, messages, qna_answers


def generate_social_activity(users: list[dict], matches: list[dict]) -> dict[str, list]:
    """Generate blocks, reports, super likes, profile views."""
    user_emails = [u["email"] for u in users]

    blocks = []
    for _ in range(6):
        u1, u2 = random.sample(user_emails, 2)
        blocks.append({"blocker_user_id_ref": u1, "blocked_user_id_ref": u2})

    reports = []
    report_reasons = ["spam", "fake_profile", "abuse", "inappropriate", "other"]
    for _ in range(5):
        u1, u2 = random.sample(user_emails, 2)
        reports.append({
            "reporter_user_id_ref": u1,
            "reported_user_id_ref": u2,
            "reason": random.choice(report_reasons),
            "status": "open",
            "notes": "Reported during flatmate discovery.",
        })

    super_likes = []
    today = datetime.now(timezone.utc).date()
    for _ in range(15):
        u1, u2 = random.sample(user_emails, 2)
        super_likes.append({
            "user_id_ref": u1,
            "target_user_id_ref": u2,
            "used_on": (today - timedelta(days=random.randint(0, 7))).isoformat(),
        })

    profile_views = []
    for _ in range(60):
        u1, u2 = random.sample(user_emails, 2)
        profile_views.append({
            "viewer_user_id_ref": u1,
            "viewed_user_id_ref": u2,
            "source": random.choice(["swipe_deck", "match_list", "conversation"]),
            "duration_seconds": random.randint(3, 120),
            "scroll_depth_percent": random.randint(20, 100),
        })

    return {"blocks": blocks, "reports": reports, "super_like_usage": super_likes, "profile_view_events": profile_views}


def generate_flatmate_visits(users: list[dict], properties: list[dict]) -> list[dict]:
    """Generate flatmate_meet visits."""
    user_emails = [u["email"] for u in users]
    visits = []
    for _ in range(15):
        visits.append({
            "user_id_ref": random.choice(user_emails),
            "property_id_ref": random.choice([p["title"] for p in properties]) if properties else None,
            "counterparty_user_id_ref": random.choice(user_emails),
            "visit_context": "flatmate_meet",
            "scheduled_date": _rand_dt(14),
            "status": random.choice(["scheduled", "confirmed", "completed"]),
        })
    return visits


def generate_agent_interactions(users: list[dict]) -> list[dict]:
    """Generate agent interaction records."""
    interactions = []
    agent_names = ALL_AGENT_NAMES
    user_emails = [u["email"] for u in users]
    messages = [
        "I'm looking for a 2BHK in DLF Phase 3. Can you help?",
        "Sure! I have some great options. What's your budget?",
        "Around 40-50k per month.",
        "I'll shortlist 3-4 properties for you by tomorrow.",
        "Thanks! Can we schedule visits this weekend?",
    ]
    for _ in range(25):
        interactions.append({
            "agent_id_ref": random.choice(agent_names),
            "user_id_ref": random.choice(user_emails),
            "interaction_type": random.choice(["chat", "chat", "call", "email"]),
            "message": random.choice(messages),
            "response": random.choice(messages),
            "response_time_seconds": random.randint(30, 7200),
            "user_satisfaction": random.randint(3, 5),
        })
    return interactions


def generate_search_history(users: list[dict], properties: list[dict]) -> list[dict]:
    """Generate user search history."""
    user_emails = [u["email"] for u in users]
    queries = [
        "2BHK Gurgaon", "apartment DLF Phase 3", "PG Sohna Road", "flatmate Sector 49",
        "short stay Cyber City", "flatmate Gurgaon", "villa Golf Course Road", "apartment MG Road",
        "3BHK Sector 56", "PG DLF Phase 1", "studio Sector 29", "builder floor Sector 14",
        "penthouse Cyber City", "1BHK Sector 10A", "house Sector 21", "flatmate Sushant Lok",
        "apartment Dwarka Expressway", "PG Sector 45", "2BHK Sector 50", "villa Nirvana Country",
        "short stay MG Road", "flatmate South City", "3BHK Golf Course Extension",
        "apartment Sector 82", "PG Palam Vihar", "2BHK Sector 57", "house Manesar",
        "flatmate Sector 40", "apartment Emaar Palm Hills", "studio Udyog Vihar",
    ]
    searches = []
    for _ in range(50):
        searches.append({
            "user_id_ref": random.choice(user_emails),
            "search_query": random.choice(queries),
            "search_filters": {"purpose": random.choice(["rent", "buy"]), "bedrooms": random.randint(1, 4)},
            "results_count": random.randint(5, 100),
        })
    return searches


def generate_tour_analytics(tours: list[dict], users: list[dict]) -> list[dict]:
    """Generate tour analytics events."""
    user_emails = [u["email"] for u in users]
    events = []
    event_types = ["tour_view", "scene_navigate", "hotspot_click", "tour_share", "tour_like"]
    for _ in range(150):
        events.append({
            "tour_id": random.choice(tours)["id"] if tours else str(uuid.uuid4()),
            "user_id_ref": random.choice(user_emails) if random.random() < 0.7 else None,
            "event_type": random.choice(event_types),
            "event_data": {"device": random.choice(["mobile", "desktop", "tablet"])},
            "device_type": random.choice(["mobile", "desktop", "tablet"]),
            "country": "IN",
            "city": random.choice(CITIES),  # Gurgaon, Delhi NCR
        })
    return events


def generate_ai_conversations(users: list[dict]) -> list[dict]:
    """Generate AI agent chat sessions."""
    user_emails = [u["email"] for u in users]
    conversations = []

    chat_sessions = [
        {"title": "Property search help", "msgs": [
            {"role": "user", "content": "I'm looking for a 2BHK apartment in Gurgaon under 40k rent"},
            {"role": "assistant", "content": "I found several options in DLF Phase 3 and Sector 49. Would you like to see them?"},
            {"role": "user", "content": "Yes, show me properties near CyberHub"},
            {"role": "assistant", "content": "Here are 3 properties near CyberHub: DLF Skycourt (35k), M3M Woodshire (38k), and DLF Park Place (42k). Should I schedule a visit?"},
        ]},
        {"title": "Vastu analysis", "msgs": [
            {"role": "user", "content": "Can you check the vastu of my property?"},
            {"role": "assistant", "content": "I can help with vastu analysis. Could you share your property details or images?"},
            {"role": "user", "content": "It's a 3BHK in Sector 45, facing east"},
            {"role": "assistant", "content": "Based on the details, your property has good vastu alignment. The east-facing entrance is auspicious. Kitchen in the southeast and master bedroom in the southwest are ideal placements."},
        ]},
        {"title": "PM rent query", "msgs": [
            {"role": "user", "content": "What's the rent collection status for my properties?"},
            {"role": "assistant", "tool_name": "owner_rent_status", "content": "Checking your rent status..."},
            {"role": "assistant", "content": "You have 2 properties with active leases. Rent for May is due in 5 days for your DLF Phase 3 property. Your Sohna Road property rent was paid on the 1st."},
        ]},
    ]

    for session in chat_sessions:
        conversations.append({
            "user_id_ref": random.choice(user_emails),
            "title": session["title"],
            "_messages": session["msgs"],
        })

    return conversations


def generate_auction_alerts(users: list[dict]) -> list[dict]:
    """Generate auction alert subscriptions."""
    user_emails = [u["email"] for u in users]
    alerts = []
    for _ in range(12):
        alerts.append({
            "user_id_ref": random.choice(user_emails),
            "city": random.choice(CITIES),  # Gurgaon, Delhi NCR
            "property_type": random.choice(["residential", "commercial"]),
            "min_price": random.randint(1000000, 5000000),
            "max_price": random.randint(5000000, 30000000),
            "bank_name": random.choice(BANKS[:4]),  # SBI, PNB, HDFC Ltd, ICICI Bank
            "alert_channels": ["email"],
            "is_active": True,
        })
    return alerts


def main(seed: int = 42) -> None:
    """Generate all Category 3 activity data."""
    random.seed(seed)
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Generating Category 3 activity data (seed={seed})...")

    users = load_seed_users()
    properties = load_seed_properties()
    tours = load_seed_tours()

    # Swipes
    swipes = generate_swipes(users, properties)
    _write("01_swipes.json", swipes)

    # Matches
    matches = generate_matches(users)
    _write("02_matches.json", matches)

    # Conversations + participants + messages + QnA
    convs, participants, messages, qna = generate_conversations(users, matches)
    _write("04_conversations.json", convs)
    _write("04b_conversation_participants.json", participants)
    _write("05_messages.json", messages)
    _write("03_match_qna.json", qna)

    # Social activity
    social = generate_social_activity(users, matches)
    _write("07_blocks.json", social["blocks"])
    _write("08_reports.json", social["reports"])
    _write("06_super_like_usage.json", social["super_like_usage"])
    _write("09_profile_view_events.json", social["profile_view_events"])

    # Flatmate visits
    _write("10_flatmate_visits.json", generate_flatmate_visits(users, properties))

    # Agent interactions
    _write("11_agent_interactions.json", generate_agent_interactions(users))

    # Search history
    _write("12_search_history.json", generate_search_history(users, properties))

    # Tour analytics
    _write("13_tour_analytics.json", generate_tour_analytics(tours, users))

    # AI conversations
    _write("14_ai_conversations.json", generate_ai_conversations(users))

    # Auction alerts
    _write("15_auction_alerts.json", generate_auction_alerts(users))

    print(f"Done! Generated activity data in {GENERATED_DIR}")


def _write(filename: str, data: list[dict[str, Any]]) -> None:
    path = GENERATED_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    print(f"  Written: {filename} ({len(data)} records)")


if __name__ == "__main__":
    main()
