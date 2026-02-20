"""
Response formatter for ChatGPT App responses.

ChatGPT Apps expect tool responses in a specific format:
- structuredContent: JSON data visible to both model and widget
- content: Narrative text for the model to use in responses
- _meta: Data only the widget sees (for large/sensitive data)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from app.mcp.apps_sdk import AppsSDKToolResult


def format_chatgpt_response(
    data: Dict[str, Any],
    content_summary: str,
    meta: Optional[Dict[str, Any]] = None,
    *,
    is_error: bool = False,
) -> AppsSDKToolResult:
    """Format tool response for ChatGPT App consumption.

    Args:
        data: Structured data for both model and widget (structuredContent).
              Keep this concise (<4k tokens) as it's sent to the model.
        content_summary: Narrative text for the model to incorporate in responses.
        meta: Data only the widget sees (_meta). Use for large data like images,
              map coordinates, or sensitive info not needed by the model.

    Returns:
        ToolResult with structuredContent, content, and optional result-level _meta.
    """
    return AppsSDKToolResult(
        content=content_summary,
        structured_content=data,
        result_meta=meta,
        is_error=is_error,
    )


def format_auth_required_response(
    action: str,
    message: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> None:
    """Format a response that prompts the user to authenticate.

    Raises an AuthRequiredError which will be turned into a CallToolResult with
    `_meta["mcp/www_authenticate"]` to trigger the OAuth flow in ChatGPT's UI.

    Args:
        action: The action that requires authentication (e.g., "swipe", "schedule_visit")
        message: Optional custom message. Defaults to a standard prompt.
        context: Optional context data to include (e.g., property_id being acted on)

    Returns:
        None (always raises).
    """
    from app.mcp.apps_sdk import AuthRequiredError

    if message is None:
        message = (
            "To use this feature, please log in to your 360Ghar account. "
            "You can log in with your phone number."
        )

    data = {
        "requires_auth": True,
        "action": action,
    }
    if context:
        data.update(context)

    raise AuthRequiredError(
        message=message,
        www_authenticate='Bearer error="invalid_token"',
        structured_content=data,
    )


def format_property_list_summary(
    properties: List[Dict[str, Any]],
    total: int,
    filters: Optional[Dict[str, Any]] = None,
) -> str:
    """Generate natural language summary of property search results.

    Args:
        properties: List of property dicts
        total: Total count of matching properties
        filters: Applied filters for context

    Returns:
        Human-readable summary string.
    """
    if not properties:
        return "No properties found matching your criteria."

    # Extract price range
    prices = [p.get("base_price") or p.get("monthly_rent") for p in properties if p.get("base_price") or p.get("monthly_rent")]
    if prices:
        min_price = min(prices)
        max_price = max(prices)
        price_range = f"₹{_format_price(min_price)} to ₹{_format_price(max_price)}"
    else:
        price_range = "various prices"

    # Extract property types
    types = set(p.get("property_type", "property") for p in properties)
    type_str = ", ".join(types) if len(types) <= 3 else "various types"

    # Extract locations
    locations = set(p.get("locality") or p.get("city", "") for p in properties if p.get("locality") or p.get("city"))
    location_str = ", ".join(list(locations)[:3]) if locations else "your search area"

    showing = len(properties)
    return f"Found {total} properties. Showing {showing} {type_str} in {location_str}, with prices ranging from {price_range}."


def format_property_detail_summary(property_data: Dict[str, Any]) -> str:
    """Generate natural language summary of a single property.

    Args:
        property_data: Property dict with details

    Returns:
        Human-readable summary string.
    """
    title = property_data.get("title", "Property")
    locality = property_data.get("locality", "")
    city = property_data.get("city", "")
    location = f"{locality}, {city}" if locality and city else locality or city or "Unknown location"

    bedrooms = property_data.get("bedrooms")
    bathrooms = property_data.get("bathrooms")
    area = property_data.get("area_sqft")

    specs = []
    if bedrooms:
        specs.append(f"{bedrooms} bedrooms")
    if bathrooms:
        specs.append(f"{bathrooms} bathrooms")
    if area:
        specs.append(f"{area:,.0f} sq ft")
    specs_str = ", ".join(specs) if specs else ""

    price = property_data.get("base_price") or property_data.get("monthly_rent")
    purpose = property_data.get("purpose", "")
    if price:
        if purpose == "rent" or property_data.get("monthly_rent"):
            price_str = f"₹{_format_price(price)}/month"
        else:
            price_str = f"₹{_format_price(price)}"
    else:
        price_str = "Price on request"

    return f"{title} in {location}. {specs_str}. {price_str}."


def format_visit_summary(visit_data: Dict[str, Any]) -> str:
    """Generate natural language summary of a visit.

    Args:
        visit_data: Visit dict with details

    Returns:
        Human-readable summary string.
    """
    property_title = visit_data.get("property", {}).get("title", "property")
    scheduled_date = visit_data.get("scheduled_date", "")
    status = visit_data.get("status", "scheduled")

    return f"Visit to {property_title} {status} for {scheduled_date}."


def format_visits_list_summary(visits: List[Dict[str, Any]], counts: Dict[str, int]) -> str:
    """Generate natural language summary of visits list.

    Args:
        visits: List of visit dicts
        counts: Dict with upcoming, completed, cancelled counts

    Returns:
        Human-readable summary string.
    """
    total = counts.get("total", len(visits))
    upcoming = counts.get("upcoming", 0)
    completed = counts.get("completed", 0)

    if total == 0:
        return "You don't have any property visits scheduled."

    parts = []
    if upcoming:
        parts.append(f"{upcoming} upcoming")
    if completed:
        parts.append(f"{completed} completed")

    return f"You have {total} visits: {', '.join(parts)}."


def _format_price(price: Union[int, float]) -> str:
    """Format price in Indian numbering system (lakhs/crores)."""
    if price >= 10000000:  # 1 crore
        return f"{price / 10000000:.2f} Cr"
    elif price >= 100000:  # 1 lakh
        return f"{price / 100000:.2f} L"
    else:
        return f"{price:,.0f}"


# ============================================================================
# Property Management Response Formatters
# ============================================================================


def format_lease_list_summary(
    leases: List[Dict[str, Any]],
    stats: Dict[str, Any],
) -> str:
    """Generate natural language summary of lease list.

    Args:
        leases: List of lease dicts
        stats: Stats dict with active_leases, total_monthly_rent

    Returns:
        Human-readable summary string.
    """
    total = len(leases)
    active = stats.get("active_leases", 0)
    monthly_rent = stats.get("total_monthly_rent", 0)

    if total == 0:
        return "You don't have any leases for your properties."

    return f"You have {total} leases ({active} active) generating ₹{_format_price(monthly_rent)}/month in rent."


def format_rent_status_summary(
    charges: List[Dict[str, Any]],
    totals: Dict[str, Any],
) -> str:
    """Generate natural language summary of rent collection status.

    Args:
        charges: List of rent charge dicts
        totals: Dict with total_due, total_paid, overdue_count

    Returns:
        Human-readable summary string.
    """
    total_due = totals.get("total_due", 0)
    total_paid = totals.get("total_paid", 0)
    overdue = totals.get("overdue_count", 0)

    if total_due == 0:
        return "All rent is current. No outstanding balances."

    summary = f"Rent status: ₹{_format_price(total_paid)} collected, ₹{_format_price(total_due)} outstanding."
    if overdue > 0:
        summary += f" {overdue} overdue charges require attention."
    return summary


def format_maintenance_list_summary(
    requests: List[Dict[str, Any]],
    stats: Dict[str, Any],
) -> str:
    """Generate natural language summary of maintenance requests.

    Args:
        requests: List of maintenance request dicts
        stats: Dict with open, urgent counts

    Returns:
        Human-readable summary string.
    """
    total = len(requests)
    open_count = stats.get("open", 0)
    urgent = stats.get("urgent", 0)

    if total == 0:
        return "No maintenance requests for your properties."

    summary = f"Found {total} maintenance requests."
    if open_count > 0:
        summary += f" {open_count} require attention."
    if urgent > 0:
        summary += f" {urgent} are marked urgent!"
    return summary


def format_dashboard_summary(dashboard: Dict[str, Any]) -> str:
    """Generate natural language summary of owner dashboard.

    Args:
        dashboard: Dashboard data dict

    Returns:
        Human-readable summary string.
    """
    props = dashboard.get("properties", {})
    rent = dashboard.get("rent", {})
    maintenance = dashboard.get("maintenance", {})

    total_props = props.get("total", 0)
    occupied = props.get("occupied", 0)
    vacant = props.get("vacant", 0)
    expected = rent.get("expected_monthly", 0)
    collected = rent.get("collected_this_month", 0)
    open_maint = maintenance.get("open", 0)

    parts = [
        f"{total_props} properties ({occupied} occupied, {vacant} vacant)",
    ]

    if expected > 0:
        collection_rate = (collected / expected * 100) if expected else 0
        parts.append(f"₹{_format_price(collected)}/₹{_format_price(expected)} rent collected ({collection_rate:.0f}%)")

    if open_maint > 0:
        parts.append(f"{open_maint} open maintenance requests")

    return "Dashboard: " + ". ".join(parts) + "."


def format_tenant_rent_dues_summary(
    charges: List[Dict[str, Any]],
    total_due: float,
    overdue_count: int,
) -> str:
    """Generate natural language summary of tenant's rent dues.

    Args:
        charges: List of rent charge dicts
        total_due: Total amount due
        overdue_count: Number of overdue charges

    Returns:
        Human-readable summary string.
    """
    if total_due == 0:
        return "Your rent is up to date! No outstanding payments."

    summary = f"You have ₹{_format_price(total_due)} in outstanding rent."
    if overdue_count > 0:
        summary += f" {overdue_count} payment(s) are overdue. Please pay as soon as possible."
    return summary
