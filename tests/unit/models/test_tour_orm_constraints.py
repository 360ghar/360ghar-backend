"""ORM constraints mirror the DDL (be-tours-27). No database."""

from __future__ import annotations

from app.models.tours import CustomDomain, Tour


def test_custom_domain_name_is_unique_as_in_the_migration():
    assert CustomDomain.__table__.c.domain.unique is True


def test_short_code_is_a_partial_unique_index_as_in_the_migration():
    indexes = {index.name: index for index in Tour.__table__.indexes}
    short_code_index = indexes["idx_tours_short_code"]
    assert short_code_index.unique is True
    assert str(short_code_index.dialect_options["postgresql"]["where"]) == "short_code IS NOT NULL"
