"""
Daytona Sandbox integration for virtual tour generation.

``generate_tour_in_sandbox()`` spins up an isolated Daytona sandbox, uploads the
panoramas + a self-contained Gemini agent script (plus an optional SKILL.md-style
prompt file), runs the agent inside the sandbox, and returns the validated
tour.json plan. The sandbox is always destroyed afterwards, even on failure.

The agent script is pure Python stdlib (``urllib``) so no ``pip install`` is
needed inside the sandbox; it calls the Gemini REST API with the panoramas as
inline base64 images and writes the resulting tour plan to ``tour.json``.
"""
from __future__ import annotations

import asyncio
import json
import math
from typing import Any, cast

from app.config import settings
from app.core.http import get_general_client
from app.core.logging import get_logger
from app.services.ai import AIProviderError

logger = get_logger(__name__)

_SANDBOX_IMAGE = "python:3.11"
_WORK_DIR = "/home/daytona/tourgen"
_AGENT_FILE = f"{_WORK_DIR}/agent.py"
_PROMPT_FILE = f"{_WORK_DIR}/prompt.txt"
_IMAGES_FILE = f"{_WORK_DIR}/images.json"
_OUTPUT_FILE = f"{_WORK_DIR}/tour.json"
_MAX_OUTPUT_TOKENS = 24000

# System prompt embedded into the agent: the exact tour.json schema consumed by
# ``_apply_spatial_tour_plan`` in app/services/tour_ai/background.py.
TOUR_PLAN_SYSTEM_PROMPT = """You are an expert Matterport-style 360 tour builder.
You receive all panorama images for one property in a single request. Build one connected
tour.json plan from the pixels, not from filenames. Return strict JSON only.

Coordinate convention:
- yaw is degrees in [-180, 180], 0 at image center, positive to the right.
- pitch is degrees in [-90, 90]. Navigation pucks sit on the floor inside doorways,
  usually -25 to -40, as shallow as -12 to -20 for far open-plan passages.

Rules:
- Classify rooms from pixels. Filenames and labels are weak hints only.
- Find traversable openings: doors, archways, passages, glass/sliding balcony doors.
- Ignore windows, mirrors, walls, curtains, and furniture.
- Only link to rooms that have one of the provided panorama images.
- Make every navigation edge reciprocal. If A links to B, B must link back to A.
- Every scene must be reachable from initial_scene_id.
- At most one navigation hotspot per source scene and target scene.
- Prefer entrance as the start, then living_room, then the most connected scene.
- Write grounded real-estate metadata based on visible details.

Output shape:
{
  "title": "tour title",
  "initial_scene_id": "scene_id",
  "scenes": [
    {
      "id": "stable_scene_id",
      "image_key": "EXACT image key from the prompt",
      "room_type": "living_room|dining_room|kitchen|bedroom|master_bedroom|bathroom|balcony|terrace|hallway|entrance|study|utility|other",
      "title": "short room title",
      "description": "2-4 sentence grounded room description",
      "caption": "short caption, max 8 words",
      "narration_script": "one spoken-style guide paragraph",
      "order_index": 0,
      "metadata": {"initial_view": {"yaw": 0, "pitch": 0, "zoom": 50}},
      "hotspots": [
        {
          "id": "source->target",
          "type": "navigation",
          "target_scene_id": "target_scene_id",
          "title": "target scene title",
          "position": {"yaw": 0, "pitch": -30},
          "order_index": 0,
          "custom_data": {"auto_generated": true, "opening_type": "door|passage|open_archway|glass_sliding_door"}
        }
      ]
    }
  ]
}
"""

# Pure-stdlib agent executed inside the sandbox. Reads images.json, calls Gemini
# with inline base64 images, writes tour.json.
# The %-substitution below injects the max token count into the embedded script.
_AGENT_SCRIPT = '''\
import json
import os
import sys
import urllib.request


def call_gemini(api_key, model, prompt, images):
    parts = [{"text": prompt}]
    for image in images:
        parts.append({
            "inline_data": {
                "mime_type": image["mime_type"],
                "data": image["base64"],
            }
        })
    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "response_mime_type": "application/json",
            "maxOutputTokens": %(max_tokens)d,
        },
    }
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        + urllib.request.quote(model)
        + ":generateContent?key="
        + api_key
    )
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        data = json.loads(response.read().decode("utf-8"))
    text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


def main():
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY is not set in the sandbox", file=sys.stderr)
        sys.exit(2)
    model = os.environ.get("DAYTONA_AGENT_GEMINI_MODEL", "gemini-2.5-flash")
    with open("images.json", "r", encoding="utf-8") as handle:
        images = json.load(handle)
    prompt = ""
    if os.path.exists("prompt.txt"):
        with open("prompt.txt", "r", encoding="utf-8") as handle:
            prompt = handle.read()
    plan = call_gemini(api_key, model, prompt, images)
    with open("tour.json", "w", encoding="utf-8") as handle:
        json.dump(plan, handle, indent=2)
    print("TOUR_PLAN_WRITTEN")


if __name__ == "__main__":
    main()
''' % {"max_tokens": _MAX_OUTPUT_TOKENS}  # noqa: UP031 - deliberate script injection


def _build_agent_prompt(
    title: str,
    description: str | None,
    images: list[dict[str, Any]],
    skill_content: str,
) -> str:
    """Assemble the full prompt text uploaded to the sandbox."""
    lines = [
        TOUR_PLAN_SYSTEM_PROMPT,
        "",
        f"Requested tour title: {title}",
        f"Property/context description: {description or 'Not provided.'}",
        "Images. Use the exact image_key for each returned scene:",
    ]
    for index, image in enumerate(images, start=1):
        key = str(image.get("key") or f"image_{index}")
        hint = str(image.get("filename_hint") or image.get("image_url") or "")
        lines.append(f"{index}. image_key={key}; weak_hint={hint}")
    lines.append("Return one complete JSON object matching the schema. Do not include prose.")
    prompt = "\n".join(lines)
    if skill_content.strip():
        prompt = (
            "Additional tour-building instructions (follow these when they do not "
            f"conflict with the schema above):\n{skill_content.strip()}\n\n{prompt}"
        )
    return prompt


async def _upload_file(
    sandbox: Any,
    remote_path: str,
    file_bytes: bytes,
    mime_type: str,
) -> None:
    """Upload a file into the sandbox via its pre-signed upload URL."""
    url = await sandbox.upload_url(remote_path)
    client = get_general_client()
    response = await client.post(
        url,
        files={"file": (remote_path.rsplit("/", 1)[-1], file_bytes, mime_type)},
        timeout=180.0,
    )
    response.raise_for_status()


async def _read_output(sandbox: Any, remote_path: str) -> str:
    """Read a text file back from the sandbox via its pre-signed download URL."""
    url = await sandbox.download_url(remote_path)
    client = get_general_client()
    response = await client.get(url, timeout=120.0)
    response.raise_for_status()
    return response.text


async def generate_tour_in_sandbox(
    images_base64: list[dict[str, Any]],
    skill_content: str = "",
    title: str = "Virtual Tour",
    description: str | None = None,
) -> dict[str, Any]:
    """
    Spin up a Daytona sandbox, run the Gemini tour-planning agent on the given
    panoramas, and return the resulting tour.json plan.

    Args:
        images_base64: list of {"key", "image_base64", "mime_type", "image_url",
            "filename_hint"} — the panoramas to plan the tour from.
        skill_content: optional extra instructions (e.g. a SKILL.md) injected
            into the agent prompt.
        title: requested tour title (fallback used when the model omits one).
        description: optional property/context description.

    Returns:
        The tour plan dict (title, initial_scene_id, scenes).

    Raises:
        AIProviderError: when the sandbox cannot be provisioned, the agent fails,
            the plan is missing/invalid, or the timeout is exceeded.
    """
    if not settings.DAYTONA_API_KEY:
        raise AIProviderError(
            "DAYTONA_API_KEY is missing; cannot run sandbox tour generation",
            provider="gemini",
        )
    if not images_base64:
        raise AIProviderError(
            "No panoramas provided for sandbox tour generation",
            provider="gemini",
        )

    images = [
        {
            "key": str(image.get("key") or f"image_{index}"),
            "mime_type": str(image.get("mime_type") or "image/jpeg"),
            "base64": str(image["image_base64"]),
            "image_url": image.get("image_url"),
            "filename_hint": image.get("filename_hint"),
        }
        for index, image in enumerate(images_base64)
    ]
    prompt = _build_agent_prompt(title, description, images, skill_content)

    timeout = settings.DAYTONA_SANDBOX_TIMEOUT_SECONDS
    sandbox_id: str | None = None
    sandbox: Any = None

    try:
        from daytona import AsyncDaytona, CreateSandboxFromImageParams, DaytonaConfig

        config = DaytonaConfig(
            api_key=settings.DAYTONA_API_KEY,
            api_url=settings.DAYTONA_API_URL,
            target=settings.DAYTONA_TARGET,
        )
        client = AsyncDaytona(config)

        async def _run() -> dict[str, Any]:
            nonlocal sandbox, sandbox_id
            gemini_key = settings.GEMINI_API_KEY or settings.GOOGLE_API_KEY
            params = CreateSandboxFromImageParams(
                image=_SANDBOX_IMAGE,
                env_vars={
                    "GEMINI_API_KEY": gemini_key or "",
                    "DAYTONA_AGENT_GEMINI_MODEL": settings.DAYTONA_AGENT_GEMINI_MODEL,
                },
                auto_stop_interval=0,
                # Hard TTL backstop so a lost sandbox can never leak for long.
                ttl_minutes=max(1, math.ceil(timeout / 60) + 10),
                ephemeral=True,
            )
            sandbox = await client.create(params, timeout=min(300.0, max(30.0, timeout)))
            sandbox_id = sandbox.id
            logger.info("Daytona sandbox %s created for tour generation", sandbox.id)

            await sandbox.process.exec(f"mkdir -p {_WORK_DIR}")
            await _upload_file(sandbox, _AGENT_FILE, _AGENT_SCRIPT.encode("utf-8"), "text/plain")
            await _upload_file(sandbox, _PROMPT_FILE, prompt.encode("utf-8"), "text/plain")
            await _upload_file(
                sandbox,
                _IMAGES_FILE,
                json.dumps(images).encode("utf-8"),
                "application/json",
            )

            # Run from the workdir: the agent script reads images.json/prompt.txt
            # with relative paths, so the sandbox cwd must be the upload dir.
            run_result = await sandbox.process.exec(
                f"cd {_WORK_DIR} && python3 {_AGENT_FILE}"
            )
            if run_result.exit_code != 0:
                raise AIProviderError(
                    f"Daytona sandbox agent failed (exit {run_result.exit_code}): "
                    f"{run_result.result[:2000]}",
                    provider="gemini",
                )

            raw = await _read_output(sandbox, _OUTPUT_FILE)
            try:
                plan = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise AIProviderError(
                    f"Daytona sandbox produced invalid tour.json: {exc}",
                    provider="gemini",
                ) from exc

            scenes = plan.get("scenes") if isinstance(plan, dict) else None
            if not isinstance(scenes, list) or not scenes:
                raise AIProviderError(
                    "Daytona sandbox plan has no usable scenes",
                    provider="gemini",
                )
            return cast(dict[str, Any], plan)

        try:
            plan = await asyncio.wait_for(_run(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise AIProviderError(
                f"Daytona sandbox tour generation timed out after {timeout}s",
                provider="gemini",
            ) from exc

        logger.info("Daytona sandbox tour generation completed (sandbox %s)", sandbox_id)
        return plan

    except AIProviderError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface sandbox/SDK failures cleanly
        logger.error("Daytona sandbox tour generation failed: %s", exc, exc_info=True)
        raise AIProviderError(
            f"Daytona sandbox tour generation failed: {exc}",
            provider="gemini",
        ) from exc
    finally:
        if sandbox is not None:
            try:
                await client.delete(sandbox, wait=True)
                logger.info("Daytona sandbox %s destroyed", sandbox_id)
            except Exception:  # noqa: BLE001 - TTL backstop covers cleanup failures
                logger.warning(
                    "daytona: failed to delete sandbox %s; TTL will clean it up",
                    sandbox_id,
                    exc_info=True,
                )
        try:
            await client.close()
        except Exception:  # noqa: BLE001 - cleanup must never mask the real error
            logger.warning("daytona: failed to close client", exc_info=True)
