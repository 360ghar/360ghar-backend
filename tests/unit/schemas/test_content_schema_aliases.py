"""Response fields in the content domain carry no aliases: the attribute is the wire name."""

from __future__ import annotations

from types import SimpleNamespace

from pydantic import BaseModel

from app.schemas import data_hub as data_hub_schemas
from app.schemas.flatmates import MessageOut


def test_data_hub_response_fields_have_no_aliases() -> None:
    offenders = []
    for name in dir(data_hub_schemas):
        obj = getattr(data_hub_schemas, name)
        if (
            isinstance(obj, type)
            and issubclass(obj, BaseModel)
            and obj.__module__ == data_hub_schemas.__name__
        ):
            for field_name, info in obj.model_fields.items():
                if info.alias or info.serialization_alias or info.validation_alias:
                    offenders.append(f"{name}.{field_name}")
    assert offenders == []


def test_message_out_serializes_metadata_from_orm_column() -> None:
    row = SimpleNamespace(
        id=1,
        conversation_id=2,
        sender_id=3,
        body="hi",
        attachment_url=None,
        message_type="text",
        message_metadata={"k": "v"},
        read_at=None,
        created_at="2026-10-14T10:00:00+00:00",
    )
    out = MessageOut.model_validate(row, from_attributes=True).model_dump(mode="json")
    assert out["metadata"] == {"k": "v"}
    assert "message_metadata" not in out
