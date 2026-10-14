import pytest
from pydantic import ValidationError

from app.schemas.lead import LeadCreate, normalize_mobile


@pytest.mark.parametrize(
    "raw",
    ["9876543210", "+91 98765 43210", "919876543210", "09876543210", "98765-43210"],
)
def test_normalize_mobile_accepts_indian_formats(raw):
    assert normalize_mobile(raw) == "9876543210"


@pytest.mark.parametrize("raw", ["", "12345", "5876543210", "98765432100", "abcdefghij"])
def test_normalize_mobile_rejects_bad_numbers(raw):
    with pytest.raises(ValueError):
        normalize_mobile(raw)


def test_lead_create_cleans_text_and_keeps_honeypot():
    lead = LeadCreate(phone="+91 9876543210", name="  Asha ", note="   ", website="spam.example")
    assert lead.phone == "9876543210"
    assert lead.name == "Asha"
    assert lead.note is None
    assert lead.website == "spam.example"


def test_lead_create_rejects_long_note_and_bad_phone():
    with pytest.raises(ValidationError):
        LeadCreate(phone="9876543210", note="x" * 501)
    with pytest.raises(ValidationError):
        LeadCreate(phone="123")
