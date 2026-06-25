from __future__ import annotations

import json
import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test_user:test_password@localhost:5432/test_db")
os.environ.setdefault("ASYNC_DATABASE_URL", "postgresql+psycopg://test_user:test_password@localhost:5432/test_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SUPABASE_URL", "https://mock.supabase.co")
os.environ.setdefault("SUPABASE_PUBLISHABLE_KEY", "mock")
os.environ.setdefault("SUPABASE_SECRET_KEY", "mock")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("CI", "true")

from fastapi.routing import APIRoute  # noqa: E402

from app.factory import create_app  # noqa: E402

app = create_app()

rows = []
for route in app.routes:
    if isinstance(route, APIRoute):
        methods = sorted(m for m in route.methods if m not in ("HEAD", "OPTIONS"))
        deps = []
        for d in route.dependant.dependencies:
            if d.call is not None:
                deps.append(getattr(d.call, "__name__", str(d.call)))
        full_doc = " ".join((route.endpoint.__doc__ or "").split()).strip()
        params = []
        for p in route.dependant.path_params + route.dependant.query_params:
            params.append(p.name)
        rows.append(
            {
                "path": route.path,
                "methods": methods,
                "name": route.name,
                "tags": [str(t) for t in (route.tags or [])],
                "summary": route.summary or "",
                "doc": full_doc,
                "deps": deps,
                "params": params,
                "status_code": route.status_code,
                "response_model": getattr(route.response_model, "__name__", str(route.response_model)) if route.response_model else "",
            }
        )

rows.sort(key=lambda r: (r["tags"][0] if r["tags"] else "zzz", r["path"]))
print(json.dumps(rows, indent=2, default=str))
print(f"\nTOTAL_ROUTES={len(rows)}", flush=True)
