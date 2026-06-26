from __future__ import annotations

import csv
import json
import re

ROUTES = json.load(open("/tmp/routes.json"))

# tag -> (module, product area)
TAG_MODULE = {
    "properties": "Ghar Core",
    "swipes": "Ghar Core",
    "visits": "Ghar Core",
    "agents": "Ghar Core",
    "amenities": "Ghar Core",
    "dashboard": "Ghar Core",
    "bookings": "360 Stays",
    "payments": "360 Stays",
    "flatmates": "Flatmates",
    "flatmates-admin": "Flatmates",
    "pm-dashboard": "Property Management",
    "pm-properties": "Property Management",
    "pm-assignments": "Property Management",
    "pm-applications": "Property Management",
    "pm-public": "Property Management",
    "pm-tenants": "Property Management",
    "pm-leases": "Property Management",
    "pm-rent": "Property Management",
    "pm-expenses": "Property Management",
    "pm-maintenance": "Property Management",
    "pm-documents": "Property Management",
    "pm-inspections": "Property Management",
    "pm-reports": "Property Management",
    "tours": "Virtual Tours",
    "scenes": "Virtual Tours",
    "hotspots": "Virtual Tours",
    "floor-plans": "Virtual Tours",
    "public-tours": "Virtual Tours",
    "custom-domains": "Virtual Tours",
    "ai": "Virtual Tours",
    "design-studio": "AI / Design Studio",
    "vastu": "Vastu",
    "data-hub": "Data Hub",
    "blog": "Blog",
    "ai-agent": "AI Agent",
    "notifications": "Notifications",
    "auth": "Auth & Identity",
    "users": "Auth & Identity",
    "oauth": "Auth & Identity",
    "upload": "Media & Upload",
    "core": "Core / Platform",
    "share": "Core / Platform",
    "webhooks": "Core / Platform",
}


def role_of(deps: list[str]) -> str:
    if "get_current_admin" in deps:
        return "Admin"
    if "get_current_agent" in deps:
        return "Agent / RM"
    if "get_current_active_user" in deps or "get_current_user" in deps or "get_current_user_sse" in deps:
        return "Authenticated user"
    if "get_current_user_optional" in deps:
        return "Public (auth optional)"
    return "Public"


VERB = {
    "GET": "view",
    "POST": "create / submit",
    "PUT": "update",
    "PATCH": "update",
    "DELETE": "delete",
}


def humanize(summary: str, doc: str) -> str:
    s = (summary or "").strip()
    if not s:
        s = (doc or "").strip().split(".")[0]
    return s


def user_story(role: str, summary: str, method: str) -> str:
    action = humanize(summary, "")
    action = action[0].lower() + action[1:] if action else "use this endpoint"
    return f"As {role.lower()}, I want to {action}."


def main() -> None:
    rows = []
    for i, r in enumerate(sorted(ROUTES, key=lambda x: (TAG_MODULE.get(x["tags"][0] if x["tags"] else "", "ZZ"), x["path"])), start=1):
        tag = r["tags"][0] if r["tags"] else "none"
        module = TAG_MODULE.get(tag, "Other")
        if module == "Other":
            p = r["path"]
            if "oauth" in p or "openid" in p or ".well-known" in p:
                module, tag = "Auth & Identity", "oauth"
            elif p.startswith("/mcp"):
                module, tag = "MCP / AI Surfaces", "mcp"
            elif "/health" in p:
                module, tag = "Core / Platform", "core"
        method = r["methods"][0] if r["methods"] else "?"
        role = role_of(r["deps"])
        summary = humanize(r["summary"], r["doc"])
        doc = r["doc"]
        # expected behaviour text
        eb = doc if doc else summary
        eb = re.sub(r"\s+", " ", eb).strip()
        if r["status_code"]:
            eb += f" [HTTP {r['status_code']} on success]"
        params = ",".join(r["params"]) if r["params"] else ""
        rows.append(
            {
                "ID": f"US-{i:03d}",
                "Module": module,
                "Feature Group": tag,
                "Endpoint": f"{method} {r['path']}",
                "Role": role,
                "User Story": user_story(role, summary, method),
                "Expected Behaviour": eb,
                "Params": params,
                "Status": "Pending",
                "Test Result / Errors": "",
                "Automated Test Coverage": "",
                "Notes": "",
            }
        )

    fields = [
        "ID",
        "Module",
        "Feature Group",
        "Endpoint",
        "Role",
        "User Story",
        "Expected Behaviour",
        "Params",
        "Status",
        "Test Result / Errors",
        "Automated Test Coverage",
        "Notes",
    ]
    out = "qa/feature_user_stories.csv"
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} rows to {out}")
    from collections import Counter

    c = Counter(r["Module"] for r in rows)
    for k, v in sorted(c.items()):
        print(f"  {v:3d}  {k}")


if __name__ == "__main__":
    main()
