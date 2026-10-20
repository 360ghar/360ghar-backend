"""Property service package — re-exports all public symbols for backward compatibility.

All public functions from the original ``app.services.property`` module are available
here so that existing ``from app.services.property import X`` statements continue
to work unchanged.
"""

from app.services.property.crud import (
    attach_owner_agents,
    create_property,
    delete_property,
    get_all_amenities,
    get_property,
    increment_property_view_count,
    list_user_properties,
    update_property,
)
from app.services.property.helpers import (
    _validate_listing_contract,
    build_location_wkt,
    validate_listing_contract,
)
from app.services.property.recommendations import get_property_recommendations
from app.services.property.search import (
    TEXT_WEIGHT,
    VECTOR_WEIGHT,
    get_unified_properties_optimized,
)
from app.services.property.search_orchestration import (
    build_property_search_filters,
    run_property_search,
)

# ``property_embeddings_table`` is intentionally NOT re-exported eagerly: it is
# built lazily (via ``search._get_property_embeddings_table``) on first semantic
# search so that ``pgvector``/``numpy`` stay out of startup RAM. Access it via
# ``app.services.property.search.property_embeddings_table`` (PEP 562 lazy) or
# ``search._get_property_embeddings_table()``.

__all__ = [
    # CRUD
    "attach_owner_agents",
    "create_property",
    "delete_property",
    "get_all_amenities",
    "get_property",
    "increment_property_view_count",
    "list_user_properties",
    "update_property",
    # Search
    "get_unified_properties_optimized",
    "build_property_search_filters",
    "run_property_search",
    "VECTOR_WEIGHT",
    "TEXT_WEIGHT",
    # Recommendations
    "get_property_recommendations",
    # Helpers
    "validate_listing_contract",
    "_validate_listing_contract",
    "build_location_wkt",
]
