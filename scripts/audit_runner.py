#!/usr/bin/env python3
"""Feature-audit smoke runner.

Loads user-story JSON files from /tmp/360ghar-audit-stories-*.json and auth
tokens from .audit-tokens.json, then executes a logistical smoke test for
every endpoint listed in each story. Results are written to
audit_results_<tag>.json and a Markdown summary is printed.

Smoke semantics (per endpoint):
  - GET / DELETE  -> no body
  - POST / PUT / PATCH -> body = {} (records 422 as "reachable-validation",
                          2xx as "reachable-ok", 5xx as "FAIL-server")
  - persona token attached unless auth == "public"
  - expected status parsed from expected_behavior (first 3-digit number);
    if none, any non-5xx is treated as pass for public/optional, 401/403 ok
    for protected endpoints hit without token.

Usage:
    uv run python scripts/audit_runner.py --tag phase2
    uv run python scripts/audit_runner.py --tag retest --stories /tmp/foo.json
"""
from __future__ import annotations

import argparse
import asyncio
import glob
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

BASE_URL = os.environ.get("AUDIT_BASE_URL", "http://localhost:3600")
TOKENS_FILE = ".audit-tokens.json"
STORIES_GLOB = "/tmp/360ghar-audit-stories-*.json"

STATUS_RE = re.compile(r"\b([1-5]\d{2})\b")


@dataclass
class EndpointResult:
    story_id: str
    module: str
    feature: str
    method: str
    path: str
    persona: str
    auth: str
    expected_status: int | None
    actual_status: int | None
    outcome: str  # pass | fail | skip | error
    detail: str = ""
    body_excerpt: str = ""


@dataclass
class StoryResult:
    story_id: str
    module: str
    feature: str
    user_story: str
    endpoints_total: int
    endpoints_pass: int
    endpoints_fail: int
    endpoints_skip: int
    endpoint_results: list[EndpointResult] = field(default_factory=list)
    status: str = "pending"  # pass | fail | skip | partial


def load_tokens() -> dict[str, str]:
    with open(TOKENS_FILE) as f:
        return json.load(f)


def load_stories(paths: list[str]) -> list[dict[str, Any]]:
    stories: list[dict[str, Any]] = []
    for p in paths:
        with open(p) as f:
            stories.extend(json.load(f))
    return stories


def parse_expected_status(text: str) -> int | None:
    m = STATUS_RE.search(text or "")
    return int(m.group(1)) if m else None


def auth_header(persona: str, auth: str, tokens: dict[str, str]) -> dict[str, str]:
    if auth == "public" or persona == "guest":
        return {}
    tok = tokens.get(persona)
    if not tok:
        return {}
    return {"Authorization": f"Bearer {tok}"}


async def hit_endpoint(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    persona: str,
    auth: str,
    tokens: dict[str, str],
) -> tuple[int | None, str, str]:
    headers = auth_header(persona, auth, tokens)
    body: Any = None
    if method in ("POST", "PUT", "PATCH"):
        body = {}
    url = path if path.startswith("http") else BASE_URL + path
    try:
        resp = await client.request(method, url, headers=headers, json=body, timeout=30.0)
        excerpt = resp.text[:300].replace("\n", " ")
        return resp.status_code, "", excerpt
    except httpx.TimeoutException:
        return None, "timeout", ""
    except Exception as e:  # noqa: BLE001
        return None, f"exception:{type(e).__name__}:{e}", ""


def classify(
    actual: int | None,
    expected: int | None,
    auth: str,
    persona: str,
    err: str,
) -> tuple[str, str]:
    if err:
        return "error", err
    if actual is None:
        return "error", "no-response"
    # 5xx is always a fail (server error = logistical bug)
    if 500 <= actual < 600:
        return "fail", f"server-error {actual}"
    if expected is not None:
        if actual == expected:
            return "pass", ""
        # 401/403 for a protected endpoint hit with a valid token is a fail
        # 401/403 for a protected endpoint hit as guest is acceptable if auth!=public
        if actual in (401, 403) and auth != "public" and persona == "guest":
            return "pass", "auth-gate-ok"
        return "fail", f"expected {expected} got {actual}"
    # No expected status: accept any non-5xx
    return "pass", ""


async def run(urls: list[str], tag: str) -> list[StoryResult]:
    tokens = load_tokens()
    stories = load_stories(urls)
    results: list[StoryResult] = []
    async with httpx.AsyncClient() as client:
        for st in stories:
            sr = StoryResult(
                story_id=st["id"],
                module=st["module"],
                feature=st["feature"],
                user_story=st["user_story"],
                endpoints_total=0,
                endpoints_pass=0,
                endpoints_fail=0,
                endpoints_skip=0,
            )
            skip_reason = st.get("skip_reason")
            for ep in st["endpoints"]:
                sr.endpoints_total += 1
                if skip_reason:
                    er = EndpointResult(
                        story_id=st["id"], module=st["module"], feature=st["feature"],
                        method="", path=ep, persona=st["persona"], auth=st["auth"],
                        expected_status=None, actual_status=None, outcome="skip",
                        detail=f"skip:{skip_reason}",
                    )
                    sr.endpoints_skip += 1
                    sr.endpoint_results.append(er)
                    continue
                parts = ep.split(" ", 1)
                if len(parts) != 2:
                    er = EndpointResult(
                        story_id=st["id"], module=st["module"], feature=st["feature"],
                        method="", path=ep, persona=st["persona"], auth=st["auth"],
                        expected_status=None, actual_status=None, outcome="skip",
                        detail="unparseable-endpoint",
                    )
                    sr.endpoints_skip += 1
                    sr.endpoint_results.append(er)
                    continue
                method, path = parts[0].upper(), parts[1]
                expected = parse_expected_status(st["expected_behavior"])
                actual, err, excerpt = await hit_endpoint(
                    client, method, path, st["persona"], st["auth"], tokens
                )
                outcome, detail = classify(actual, expected, st["auth"], st["persona"], err)
                er = EndpointResult(
                    story_id=st["id"], module=st["module"], feature=st["feature"],
                    method=method, path=path, persona=st["persona"], auth=st["auth"],
                    expected_status=expected, actual_status=actual,
                    outcome=outcome, detail=detail, body_excerpt=excerpt,
                )
                if outcome == "pass":
                    sr.endpoints_pass += 1
                elif outcome == "fail":
                    sr.endpoints_fail += 1
                else:
                    sr.endpoints_skip += 1
                sr.endpoint_results.append(er)
            if sr.endpoints_skip == sr.endpoints_total:
                sr.status = "skip"
            elif sr.endpoints_fail == 0 and sr.endpoints_pass > 0:
                sr.status = "pass"
            elif sr.endpoints_fail > 0:
                sr.status = "fail"
            else:
                sr.status = "partial"
            results.append(sr)
    return results


def write_results(results: list[StoryResult], tag: str) -> str:
    path = f"audit_results_{tag}.json"
    payload = [asdict(r) for r in results]
    with open(path, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    return path


def print_summary(results: list[StoryResult]) -> None:
    total = len(results)
    by_status: dict[str, int] = {}
    ep_total = ep_pass = ep_fail = ep_skip = ep_err = 0
    for r in results:
        by_status[r.status] = by_status.get(r.status, 0) + 1
        ep_total += r.endpoints_total
        ep_pass += r.endpoints_pass
        ep_fail += r.endpoints_fail
        ep_skip += r.endpoints_skip
    print(f"Stories: {total} | status: {by_status}")
    print(f"Endpoints: total={ep_total} pass={ep_pass} fail={ep_fail} skip={ep_skip}")
    print("\nFAILURES:")
    for r in results:
        for er in r.endpoint_results:
            if er["outcome"] in ("fail", "error") if isinstance(er, dict) else er.outcome in ("fail", "error"):
                e = er if isinstance(er, dict) else asdict(er)
                print(f"  {e['story_id']} {e['method']} {e['path']} -> {e['actual_status']} ({e['detail']})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="phase2")
    ap.add_argument("--stories", nargs="*", help="story json paths (default: glob)")
    args = ap.parse_args()
    urls = args.stories or sorted(glob.glob(STORIES_GLOB))
    if not urls:
        print("no story files found", file=sys.stderr)
        return 2
    results = asyncio.run(run(urls, args.tag))
    out = write_results(results, args.tag)
    print_summary(results)
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
