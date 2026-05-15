import asyncio
import logging
import os
import re
from typing import Any

import litellm
from litellm import acompletion as _acompletion

from config import settings

logger = logging.getLogger(__name__)

# Set provider keys for LiteLLM
os.environ.setdefault("ANTHROPIC_API_KEY", settings.anthropic_api_key)
os.environ.setdefault("GROQ_API_KEY", settings.groq_api_key)

litellm.drop_params = True  # ignore unsupported params per provider

RETRY_AFTER_RE = re.compile(
    r"try again in ((?:\d+(?:\.\d+)?h)?(?:\d+(?:\.\d+)?m)?(?:\d+(?:\.\d+)?s)?)",
    re.IGNORECASE,
)
RETRY_DURATION_RE = re.compile(
    r"^(?:(?P<hours>[\d.]+)h)?(?:(?P<minutes>[\d.]+)m)?(?:(?P<seconds>[\d.]+)s)?$",
    re.IGNORECASE,
)
TOOL_USE_FAILED_MESSAGE = (
    "The previous response used malformed tool-call syntax. "
    "If a tool is needed, call it through the structured function-calling API only. "
    "Do not write XML tags, markdown links, or inline text that imitates a tool call."
)


def _normalize_tool_choice(tool_choice: dict | str | None) -> dict | str | None:
    if (
        isinstance(tool_choice, dict)
        and tool_choice.get("type") == "function"
        and "name" in tool_choice
        and "function" not in tool_choice
    ):
        return {"type": "function", "function": {"name": tool_choice["name"]}}
    return tool_choice


def _rate_limit_delay(error: Exception, attempt: int) -> float:
    match = RETRY_AFTER_RE.search(str(error))
    if match:
        duration = match.group(1).strip()
        duration_match = RETRY_DURATION_RE.match(duration)
        if duration_match:
            hours = float(duration_match.group("hours") or 0)
            minutes = float(duration_match.group("minutes") or 0)
            seconds = float(duration_match.group("seconds") or 0)
            return hours * 3600 + minutes * 60 + seconds + 0.5
    return min(2 ** attempt, 30.0)


async def acompletion(
    model: str,
    messages: list[dict],
    tools: list[dict] | None = None,
    tool_choice: dict | str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 4096,
) -> Any:
    kwargs: dict[str, Any] = dict(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = _normalize_tool_choice(tool_choice) or "auto"

    max_attempts = 4
    tool_retry_used = False
    for attempt in range(max_attempts):
        try:
            return await _acompletion(**kwargs)
        except litellm.RateLimitError as e:
            delay = _rate_limit_delay(e, attempt)
            if attempt == max_attempts - 1:
                raise
            if delay > 300:
                raise
            logger.warning(
                "LiteLLM rate limited for model=%s; retrying in %.2fs (attempt %d/%d)",
                model,
                delay,
                attempt + 1,
                max_attempts,
            )
            await asyncio.sleep(delay)
        except litellm.BadRequestError as e:
            if "tool_use_failed" not in str(e) or tool_retry_used:
                raise
            tool_retry_used = True
            logger.warning("LiteLLM tool call failed for model=%s; retrying with stricter tool instructions", model)
            kwargs["messages"] = [
                *kwargs["messages"],
                {"role": "user", "content": TOOL_USE_FAILED_MESSAGE},
            ]

    raise RuntimeError("unreachable")


def build_tool_defs(tool_registry: dict) -> list[dict]:
    """Convert TOOL_REGISTRY entries to LiteLLM-compatible function definitions."""
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": entry["schema"].get("description", name),
                "parameters": entry["schema"],
            },
        }
        for name, entry in tool_registry.items()
    ]
