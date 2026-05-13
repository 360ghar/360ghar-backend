import hashlib
import logging
import re
import unicodedata

logger = logging.getLogger(__name__)


def normalize_address(addr: str) -> str:
    """Lowercase, collapse whitespace, standardize 'sector', 'gurgaon'/'gurugram'."""
    addr = addr.lower().strip()
    addr = unicodedata.normalize("NFKD", addr)
    addr = re.sub(r"\s+", " ", addr)
    # Standardize gurgaon/gurugram
    addr = re.sub(r"\bgurgaon\b", "gurugram", addr)
    # Standardize sector notation: sec-57, sec 57 → sector 57
    addr = re.sub(r"\bsec(?:tor)?[\s\-\.]+(\d+)", r"sector \1", addr)
    return addr


def address_hash(addr: str) -> str:
    """SHA-256 of normalized address for dedup."""
    return hashlib.sha256(normalize_address(addr).encode()).hexdigest()


def generate_slug(*parts: str) -> str:
    """Kebab-case URL slug from parts."""
    combined = " ".join(str(p) for p in parts if p is not None)
    slug = combined.lower()
    slug = unicodedata.normalize("NFKD", slug)
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract text from PDF bytes using pdfplumber."""
    try:
        import io

        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    except Exception as e:
        logger.warning("PDF text extraction failed: %s", e)
        return ""


# Keywords for gazette relevance classification
_GAZETTE_KEYWORDS: dict[str, list[str]] = {
    "land_acquisition": ["land acquisition", "section 4", "section 6", "compensation", "award"],
    "rate_revision": ["circle rate", "collector rate", "revised rate", "dlc rate"],
    "policy": ["master plan", "policy", "regulation", "act", "ordinance", "amendment"],
    "clu_change": ["change of land use", "clu", "zoning", "land use change", "conversion"],
}


def classify_gazette_relevance(text: str) -> tuple[list[str], float]:
    """
    Keyword-match gazette text to categories.
    Returns (tags: list[str], relevance_score: float 0.0-1.0).
    """
    text_lower = text.lower()
    matched_tags = []
    total_hits = 0
    for tag, keywords in _GAZETTE_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in text_lower)
        if hits:
            matched_tags.append(tag)
            total_hits += hits
    # Score: capped at 1.0, scales with keyword density
    score = min(1.0, total_hits / 5.0)
    return matched_tags, round(score, 2)


# Haryana stamp duty rates
_STAMP_DUTY_RATES = {
    "male": 0.07,    # 7%
    "female": 0.05,  # 5%
    "joint": 0.06,   # 6%
}
_REGISTRATION_FEE_RATE = 0.01  # 1%


def calculate_stamp_duty(value: float, buyer_type: str) -> float:
    """Calculate Haryana stamp duty. buyer_type: 'male'|'female'|'joint'."""
    rate = _STAMP_DUTY_RATES.get(buyer_type.lower(), _STAMP_DUTY_RATES["male"])
    return round(value * rate, 2)


def calculate_registration_fee(value: float) -> float:
    """Registration fee = 1% of property value."""
    return round(value * _REGISTRATION_FEE_RATE, 2)


def calculate_builder_score(total_complaints: int, total_projects: int) -> float:
    """
    0-100 composite builder score.
    Starts at 100, deducted by complaint ratio.
    Zero projects → score of 50 (unknown).
    """
    if total_projects == 0:
        return 50.0
    complaint_ratio = total_complaints / total_projects
    # Each complaint per project deducts 15 points, capped at 0
    score = max(0.0, 100.0 - (complaint_ratio * 15.0))
    return round(score, 1)
