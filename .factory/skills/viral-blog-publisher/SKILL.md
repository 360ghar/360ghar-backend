---
name: viral-blog-publisher
description: "Discover trending real estate news, gossip, and viral topics from the web; check 360 Ghar's existing blog coverage in Supabase (past 1 week); deep-research the topic with unique 360 Ghar platform angles; perform SEO keyword analysis; write a human-sounding (non-AI) SEO-optimized blog post with structured sources and citations; publish to Supabase via direct DB insert. Use when the user asks to write a blog, find trending topics, create viral content, research and publish a blog post, or generate SEO-optimized real estate articles for 360 Ghar."
---

# Viral Blog Publisher

End-to-end pipeline to discover, research, write, and publish trending real estate blog posts for 360 Ghar.

## Workflow

```mermaid
flowchart TD
    A[1. Trend Discovery] --> B[2. Dedup Check]
    B --> C[3. Topic Selection]
    C --> D[4. Deep Research]
    D --> E[5. SEO Optimization]
    E --> F[6. Image Research]
    F --> G[7. Human-Sounding Writing]
    G --> H[8. Source Compilation]
    H --> I[9. Publish to Supabase]
```

### Step 1: Trend Discovery

Use `WebSearch` with multiple queries to find what's trending RIGHT NOW:

- `"Gurgaon real estate news today 2026"` — latest news
- `"Gurugram property market trending"` — viral discussions
- `"site:news.google.com Gurgaon property"` — Google News
- `"Haryana RERA latest update"` — policy changes
- `"Delhi NCR real estate viral"` — gossip/famous topics
- `"Gurgaon circle rate change 2026"` — data-driven stories

Target 5-10 candidate topics per run. Prioritize stories with:
- High search volume indicators (multiple outlets covering same story)
- Recency (published today or yesterday)
- 360 Ghar platform relevance (areas/sectors where we have listings, data hub coverage)

### Step 2: Dedup Check

Fetch existing blog posts from the last 7 days using one of:

**Option A — REST API (preferred when server is running):**
```
GET /api/v1/blog/posts?limit=50
```
Filter to posts with `created_at` within last 7 days.

**Option B — Direct DB query (when running script locally):**
Run `scripts/publish_blog.py --dry-run` to verify DB access, then query:
```python
from app.models.blogs import BlogPost
# SELECT title, slug, focus_keyword FROM blog_posts WHERE active=true AND created_at >= NOW() - INTERVAL '7 days'
```

Compare discovered topics against existing posts by:
- Title similarity (exact match and keyword overlap of 3+ shared terms)
- Source URL overlap
- Focus keyword overlap

Skip any topic already covered.

### Step 3: Topic Selection

From remaining candidates, rank by scoring:
- **Relevance to 360 Ghar** (0-3): Does the topic connect to sectors/areas where we have listings? Can we reference data hub, RERA, circle rates?
- **Search volume** (0-3): Are multiple outlets covering this? Does Google Trends show a spike?
- **Unique angle potential** (0-3): Can we offer something competitors can't (platform data, listings, tours)?
- **Timeliness** (0-1): Is this breaking news or a hot topic right now?

Select the highest-scoring topic.

### Step 4: Deep Research

Use `WebSearch` + `FetchUrl` to research deeply:

1. **Main story**: Search the topic, read top 5 articles via FetchUrl
2. **Data angle**: Search for related data on 360 Ghar platform:
   - `"site:360ghar.com [sector name]"` — existing listings
   - Circle rate data, RERA project status, neighbourhood scores
3. **Unique insight**: Find a specific fact, number, or perspective NOT in competitor articles
4. **Quotes/data**: Extract specific numbers, policy names, project details, dates

Record every source URL with name and type for structured sourcing.

### Step 5: SEO Optimization

Read `references/seo-playbook.md` for detailed methodology.

Determine for the selected topic:
1. **focus_keyword**: Primary target (e.g., "dwarka expressway property rates 2026")
2. **secondary_keywords**: 3-5 related terms for `seo_metadata.secondary_keywords`
3. **meta_title**: Max 60 chars, keyword-frontloaded
4. **meta_description**: Max 155 chars, includes keyword + CTA
5. **slug**: Focus keyword, hyphenated, max 5 words
6. **schema_markup type**: Article (default), FAQPage (if Q&A section), or HowTo (if guide)
7. **tags**: 5-8 specific tags including locality, topic, year
8. **categories**: 1-2 broad categories
9. **internal_links**: 3-5 slugs of related existing blog posts
10. **trending_score**: 0-100 based on current buzz level

### Step 6: Image Research & Selection

Every blog post MUST have a cover image. Search for a high-quality, free-to-use image:

1. **Search Pexels API first** (provides 1200×627 landscape — perfect for OG tags):
   ```
   GET https://api.pexels.com/v1/search?query={search_query}&per_page=5&orientation=landscape
   Header: Authorization: {PEXELS_API_KEY}
   ```
   Use `src.landscape` from the best result. Rate limit: 200 requests/hour.

2. **Fallback to Pixabay** (up to 1280px wide, higher rate limit — 5000 requests/hour):
   ```
   GET https://pixabay.com/api/?key={PIXABAY_API_KEY}&q={search_query}&image_type=photo&orientation=horizontal&min_width=800&min_height=400&per_page=5&safesearch=true
   ```
   Use `largeImageURL` from the best result.

3. **Search query strategy**: Derive from title + focus_keyword. Use the topic map in `scripts/blog_image_acquisition.py` to convert specific titles into generic real estate search terms. Examples:
   - "Inside Jasprit Bumrah's Home in Ahmedabad" → "luxury home interior"
   - "Sector 56 vs Sector 57 Gurgaon" → "residential area buildings"
   - "Vastu for Photo Frames" → "vastu home interior"

4. **Download and upload**: Download the image, verify it's a valid image file (not HTML), then upload to Supabase Storage `blog-covers/` bucket:
   ```bash
   # Using the acquisition script
   uv run python scripts/blog_image_acquisition.py --phase acquire --limit 1
   ```
   Or use `publish_blog.py --image-path local_image.jpg` when publishing a new blog.

5. **Set in payload**: `cover_image_url` and `og_image_url` = Supabase Storage public URL

6. **Add image source** to the sources array:
   ```json
   {"url": "https://www.pexels.com/photo/...", "name": "Pexels", "type": "image", "retrieved_at": "2026-05-13"}
   ```

### Step 7: Human-Sounding Writing

Read `references/writing-style.md` for detailed anti-AI patterns.

Write the blog following these rules:
- **Varied sentence length**: Mix 5-word and 25-word sentences
- **No banned AI phrases**: No "furthermore", "in today's landscape", "it's important to note"
- **Hook opening**: Start with a surprising stat, provocative question, or specific scene — never a generic intro
- **Specific over generic**: "Sector 79" not "certain sectors", "2.3 crore" not "significant prices"
- **Indian English**: Use "lakh/crore" (never "hundred thousand"), "Gurgaon/Gurugram" interchangeably
- **Opinions with confidence**: "This is the best sector for..." not "This could potentially..."
- **Honest uncertainty**: "The exact impact is unclear" when you don't know
- **Max 2 soft CTAs**: "Check live listings on 360 Ghar" — not aggressive sales
- **FAQ section**: 3-5 questions matching "People Also Ask" results

Output as clean HTML: `<p>`, `<h2>`, `<h3>`, `<ul>`, `<ol>`, `<li>`, `<strong>`, `<em>`, `<a>`, `<blockquote>`.

### Step 8: Source Compilation

Build structured sources array. Each source is:
```json
{"url": "https://...", "name": "Economic Times", "type": "article", "retrieved_at": "2026-05-13"}
```

Rules:
- Minimum 3 credible sources per post
- Block social-only sources: facebook.com, instagram.com, x.com, reddit.com, youtube.com
- Source types: `"primary"` (main story), `"article"`, `"government"`, `"data"`, `"image"`, `"video"`
- Include `retrieved_at` date for every source

### Step 9: Publish

Prepare a JSON file with all blog data and publish via the script:

```bash
# Dry run first to validate
uv run python .factory/skills/viral-blog-publisher/scripts/publish_blog.py --file blog_data.json --dry-run

# Publish for real
uv run python .factory/skills/viral-blog-publisher/scripts/publish_blog.py --file blog_data.json
```

The script does direct SQLAlchemy insert, auto-computes reading_time and word_count, handles slug uniqueness, and auto-creates categories/tags.

Alternatively, when the API server is running, POST to `/api/v1/blog/posts` with the same payload.

## Blog Data Schema

The complete JSON structure for `publish_blog.py`:

```json
{
  "title": "Catchy Display Title (can be longer)",
  "content": "<h2>Section</h2><p>HTML content...</p>",
  "excerpt": "Short summary for SERP and cards",
  "cover_image_url": "https://...",
  "meta_title": "SEO Title max 60 chars",
  "meta_description": "SERP snippet max 160 chars with keyword",
  "focus_keyword": "primary-target-keyword",
  "canonical_url": null,
  "og_image_url": "https://...",
  "categories": ["Real Estate", "Gurgaon"],
  "tags": ["dwarka-expressway", "property-rates", "2026", "gurgaon"],
  "sources": [
    {"url": "https://...", "name": "Source", "type": "primary", "retrieved_at": "2026-05-13"}
  ],
  "seo_metadata": {
    "schema_markup": {"@type": "Article", ...},
    "keyword_analysis": {"volume": "high", "difficulty": "medium"},
    "trending_score": 85.0,
    "secondary_keywords": ["kw2", "kw3"],
    "internal_links": ["existing-blog-slug-1", "existing-blog-slug-2"]
  },
  "active": true,
  "published_at": null,
  "publisher_user_id": null
}
```

## Existing Infrastructure

The blog system already has:
- **Auto-publish scheduler** (`app/services/blog_auto_publish.py`): Perplexity-based daily publisher — the skill is an on-demand upgrade to that
- **REST API** (`app/api/api_v1/endpoints/blog.py`): Full CRUD with categories, tags, and AI generation
- **Blog service** (`app/services/blog.py`): Core CRUD with auto slug, reading time, word count
- **Database model** (`app/models/blogs.py`): BlogPost with SEO fields (meta_title, meta_description, focus_keyword, canonical_url, og_image_url, reading_time_minutes, word_count, published_at, sources JSONB, seo_metadata JSONB)
