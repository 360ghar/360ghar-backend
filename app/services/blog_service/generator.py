import json
from typing import Any

import httpx

from app.config import settings
from app.core.exceptions import BaseAPIException, ExternalServiceError, ServiceUnavailableException
from app.core.logging import get_logger
from app.schemas.blog import BlogPostCreate
from app.services.blog import create_blog_post
from app.utils.validators import ValidationUtils

logger = get_logger(__name__)

BLOG_CATEGORIES = [
    "Buyer & Seller Guides (First-time Homebuyer, Step-by-step Process, How to Sell Faster, Home Loan Tips)",
    "Finance & Pricing (Interest Rate Updates, Stamp Duty & Registration, Budget-based Picks, Tax Benefits)",
    "Construction & Home Improvement (Cost Updates, Interior Design Trends, Renovation Guides, Floor Plans)",
    "Locality Deep Dives (Connectivity, Infrastructure, Ratings, Future Development)",
    "Developer & Project Reviews (Reputation Analysis, Project Comparisons, Delivery History, RERA)",
    "Lifestyle & Living (Gated Communities, Amenities Trends, Community Stories, Green Living)",
    "Real Estate for Businesses (Commercial Guides, Co-working Trends, Warehouse/Industrial, Retail Insights)",
    "Niche & Special Segments (Luxury, Affordable Housing, Senior Living, Student Housing, Holiday Homes)",
    "Tools, Tips & DIY (How to Read Floor Plans, Maintenance Tips, Verification Checklists, Negotiation)",
    "Tech in Real Estate (PropTech, AI & VR, Smart Homes, Digital Transactions)",
    "Opinion & Editorials (Expert Interviews, Predictions, Trends, Myths vs. Facts)",
    "Scam & Fraud Awareness (Common Scams, Verifying Builders, Legal Red Flags, Online Safety)",
    "Relocation & NRI (NRI Buying Guides, Returning to India, State-to-State Relocation)"
]


def _build_excerpt_from_html(html: str, max_len: int = 280) -> str:
    try:
        import re
        # Strip tags quickly; we don't need perfect HTML parsing for an excerpt
        text = re.sub(r"<[^>]+>", " ", html or "")
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_len].rstrip()
    except Exception:
        return (html or "")[:max_len]


async def _perplexity_generate(topic: str) -> dict[str, str]:
    if not settings.PERPLEXITY_API_KEY:
        raise ServiceUnavailableException(detail="PERPLEXITY_API_KEY not configured")

    url = "https://api.perplexity.ai/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.PERPLEXITY_API_KEY}",
        "Content-Type": "application/json",
    }

    system = (
        "You are an expert real estate content strategist and SEO copywriter for '360 Ghar', "
        "India's premier VR-first real estate platform in Gurgaon. "
        "Your goal is to write highly engaging, authoritative, and SEO-optimized blog posts that rank well on Google "
        "and provide immense value to readers (buyers, sellers, tenants, investors).\n\n"
        "**Voice & Tone:**\n"
        "- Trustworthy, professional, yet accessible and human.\n"
        "- Data-driven but easy to understand.\n"
        "- Localized: Use Gurgaon-specific terminology and context.\n\n"
        "**Key Value Propositions to Weave In (Subtly):**\n"
        "- 360° Virtual Tours (immersive, save time).\n"
        "- Verified Listings (no fakes, no duplicates).\n"
        "- Relationship Managers (expert guidance, not just a broker).\n"
        "- Map-based Discovery.\n\n"
        "**Formatting Rules:**\n"
        "- Use clear H2 and H3 headings to break up text.\n"
        "- Use short paragraphs (2-3 sentences).\n"
        "- Use bullet points and numbered lists heavily for readability.\n"
        "- Include a 'Key Takeaways' section at the start or end.\n"
        "- **Return ONLY valid JSON** with keys: 'title', 'content_html'."
    )

    user_prompt = (
        f"Write a comprehensive, high-quality blog post on the topic: '{topic}'.\n\n"
        "**Requirements:**\n"
        "1. **Scope:** Focus specifically on the Gurgaon (Gurugram) real estate market context for 2024-2025.\n"
        "2. **Structure:**\n"
        "   - **Catchy Title:** (If the provided topic is plain, make the title punchy and SEO-friendly).\n"
        "   - **Introduction:** Hook the reader, state the problem/opportunity.\n"
        "   - **Body:** 4-6 detailed sections using H2/H3 tags. Include real-world examples, recent trends, or data if available.\n"
        "   - **FAQ Section:** 3-5 common questions related to the topic, strictly relevant to Gurgaon.\n"
        "   - **Conclusion:** Summarize and include a soft Call-to-Action (CTA) to explore properties on 360 Ghar.\n"
        "3. **SEO:** naturally include keywords related to '{topic}', 'Gurgaon real estate', 'property in Gurgaon', etc.\n"
        "4. **Output:** valid HTML string (no markdown, no ```html blocks). Use tags: <p>, <h2>, <h3>, <ul>, <ol>, <li>, <strong>, <em>, <blockquote>.\n"
    )

    payload = {
        "model": settings.PERPLEXITY_MODEL or "sonar",
        "temperature": 0.7,
        "max_tokens": 8000,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
        # Always request structured JSON output via JSON Schema
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "blog_post",
                "schema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "content_html": {"type": "string"},
                    },
                    "required": ["title", "content_html"],
                    "additionalProperties": False,
                },
                "strict": True,
            },
        },
    }

    async with httpx.AsyncClient(timeout=120) as client:  # Increased timeout for longer generation
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code >= 400:
            logger.error("Perplexity API error %s: %s", resp.status_code, resp.text)
            raise ExternalServiceError(detail="Perplexity generation failed")

        data = resp.json()

    # Perplexity uses OpenAI-like schema; extract structured JSON content
    try:
        content = data["choices"][0]["message"]["content"]
    except Exception:
        logger.error("Unexpected Perplexity response schema: %s", data)
        raise ExternalServiceError(detail="Invalid Perplexity response") from None

    try:
        parsed = json.loads(content)
    except Exception as e:
        logger.error("Failed to parse Perplexity JSON content: %s | content=%s", e, content)
        raise ExternalServiceError(detail="Invalid JSON from Perplexity") from None

    if not isinstance(parsed, dict):
        logger.error("Perplexity JSON root is not an object: %s", parsed)
        raise ExternalServiceError(detail="Invalid Perplexity JSON shape")

    title = parsed.get("title")
    content_html = parsed.get("content_html")

    if not title or not content_html:
        raise ExternalServiceError(detail="Perplexity did not return content")

    # Final HTML sanitization for safety
    safe_html = ValidationUtils.sanitize_html(content_html)

    return {"title": title.strip(), "content_html": safe_html}


async def _serpapi_image_search(query: str, count: int = 5) -> list[str]:
    """
    Best-effort image search using SerpAPI's Google Images engine.
    Returns a list of direct image URLs (original where possible).
    """
    if not settings.SERPAPI_API_KEY:
        logger.warning("SERPAPI_API_KEY not configured; skipping image search")
        return []

    # Clamp requested count between 1 and 10 for safety
    count = min(max(count, 1), 10)

    params = {
        "engine": "google_images",
        "q": query,
        "api_key": settings.SERPAPI_API_KEY,
        # Localize to India / English for Gurgaon-focused content
        "google_domain": "google.co.in",
        "gl": "in",
        "hl": "en",
        # Enable SafeSearch on Google Images
        "safe": "active",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(settings.SERPAPI_SEARCH_ENDPOINT, params=params)
        if resp.status_code >= 400:
            logger.error("SerpAPI Google Images error %s: %s", resp.status_code, resp.text)
            return []
        data = resp.json()

    # SerpAPI Google Images returns results under "images_results"
    values = data.get("images_results") or []
    urls: list[str] = []
    for item in values:
        # Prefer full-size image when available, otherwise thumbnail
        url = item.get("original") or item.get("thumbnail")
        if url:
            urls.append(url)
        if len(urls) >= count:
            break
    return urls


async def generate_draft_from_topic(db, *, topic: str, actor) -> dict[str, Any]:
    # Generate title + content
    result = await _perplexity_generate(topic)
    title = result["title"]
    content_html = result["content_html"]

    # Find images (best effort)
    images = await _serpapi_image_search(f"{topic} Gurgaon real estate")
    cover_image = images[0] if images else None

    # Build excerpt
    excerpt = _build_excerpt_from_html(content_html)

    # Persist as draft
    payload = BlogPostCreate(
        title=title,
        content=content_html,
        excerpt=excerpt,
        cover_image_url=cover_image,
        categories=["Gurgaon", "Real Estate", "Virtual Tours", "360 Ghar"],
        tags=["Gurgaon", "Real Estate", "Virtual Tours", "VR Real Estate", "360 Ghar"],
        active=False,
        meta_title=None,
        meta_description=None,
        focus_keyword=None,
        canonical_url=None,
        og_image_url=None,
        seo_metadata=None,
        published_at=None,
    )

    created = await create_blog_post(db, payload, actor)

    return {"blog": created, "images": images}


async def generate_bulk_blogs(db, *, count: int, actor) -> list[dict[str, Any]]:
    # Generate topic ideas first
    if not settings.PERPLEXITY_API_KEY:
        raise ServiceUnavailableException(detail="PERPLEXITY_API_KEY not configured")

    categories_str = "\n- ".join(BLOG_CATEGORIES)
    url = "https://api.perplexity.ai/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.PERPLEXITY_API_KEY}",
        "Content-Type": "application/json",
    }

    system = (
        "You are a senior editor for a leading Gurgaon real estate news portal (360 Ghar). "
        "Your job is to assign high-traffic, timely, and relevant blog topics to your writers. "
        "You focus on: Breaking News, Market Data Analysis, New Govt Policies, Infrastructure Projects (Metro, Roads), "
        "and helpful guides for buyers/tenants."
    )
    prompt = (
        f"Generate {count} unique, engaging, and search-worthy blog topics about Gurgaon Real Estate.\n\n"
        f"**Source Inspiration from these Categories:**\n- {categories_str}\n\n"
        "**Critical Instructions:**\n"
        "1. **News Hook:** At least 40% of the topics MUST be about recent developments in Gurgaon (last 3-6 months) - e.g., new RERA rules, specific highway openings, circle rate changes, upcoming commercial corridors.\n"
        "2. **Specificity:** No generic titles like 'How to buy a house'. Instead use: 'Impact of Dwarka Expressway Opening on Sector 102 Property Rates'.\n"
        "3. **User Intent:** target what people actually type into Google (e.g., 'best society in Golf Course Ext Road', 'rent vs buy in Gurgaon 2025').\n"
        "4. **Format:** Return a JSON object of the shape: {\"topics\": [\"topic 1\", \"topic 2\", ...]}."
    )
    payload = {
        "model": settings.PERPLEXITY_MODEL or "sonar",
        "temperature": 0.7,
        "max_tokens": 8000,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        # Always request structured JSON output via JSON Schema
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "blog_topics",
                "schema": {
                    "type": "object",
                    "properties": {
                        "topics": {
                            "type": "array",
                            "items": {"type": "string"},
                        }
                    },
                    "required": ["topics"],
                    "additionalProperties": False,
                },
                "strict": True,
            },
        },
    }

    async with httpx.AsyncClient(timeout=45) as client:
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code >= 400:
            logger.error("Perplexity topic generation error %s: %s", resp.status_code, resp.text)
            raise ExternalServiceError(detail="Perplexity topic generation failed")
        data = resp.json()

    try:
        content = data["choices"][0]["message"]["content"]
    except Exception:
        logger.error("Unexpected Perplexity response schema for topics: %s", data)
        raise ExternalServiceError(detail="Invalid Perplexity response") from None

    try:
        parsed = json.loads(content)
    except Exception as e:
        logger.error("Failed to parse Perplexity topics JSON content: %s | content=%s", e, content)
        raise ExternalServiceError(detail="Invalid JSON from Perplexity") from None

    if not isinstance(parsed, dict):
        logger.error("Perplexity topics JSON root is not an object: %s", parsed)
        raise ExternalServiceError(detail="Invalid Perplexity JSON shape")

    raw_topics = parsed.get("topics") or []
    if not isinstance(raw_topics, list):
        logger.error("Perplexity topics JSON 'topics' is not a list: %s", parsed)
        raise ExternalServiceError(detail="Invalid Perplexity topics JSON")

    topics: list[str] = [str(t).strip() for t in raw_topics if str(t).strip()]

    # Deduplicate and cap to requested count
    uniq: list[str] = []
    seen = set()
    for t in topics:
        key = t.lower().strip()
        if key and key not in seen:
            uniq.append(t)
            seen.add(key)
        if len(uniq) >= count:
            break

    results: list[dict[str, Any]] = []
    for t in uniq:
        try:
            draft = await generate_draft_from_topic(db, topic=t, actor=actor)
            results.append(draft)
        except BaseAPIException:
            raise
        except Exception as e:
            logger.error("Failed to generate draft for topic '%s': %s", t, e)
    return results
