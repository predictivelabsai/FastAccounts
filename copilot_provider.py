"""xAI Grok chat-completions client.

The API key is supplied server-side; it never enters prompts, logs,
audits or responses. Usage token counts are returned for quota accounting and
audits. Calls run through an injectable HTTP client factory so tests never
touch the network.
"""
from __future__ import annotations

import os

import httpx

BASE_URL = "https://api.x.ai/v1/chat/completions"
DEFAULT_MODEL = "grok-4-1-fast-reasoning"
MAX_OUTPUT_TOKENS = 2048
TIMEOUT_SECONDS = 60

HTTP_CLIENT_FACTORY = lambda: httpx.Client(timeout=TIMEOUT_SECONDS)


class CopilotProviderError(RuntimeError):
    """Provider call failed (HTTP error, timeout or malformed reply)."""


def configured() -> bool:
    return bool(os.getenv("FASTACCOUNTS_GROK_API_KEY", "").strip())


def model() -> str:
    return os.getenv("FASTACCOUNTS_GROK_MODEL", "").strip() or DEFAULT_MODEL


def chat_completion(messages: list[dict], *, client: httpx.Client | None = None, api_key=None, model_id=None) -> dict:
    """Send one chat-completions request and return {content, model, tokens_in, tokens_out}."""
    key = api_key or os.getenv("FASTACCOUNTS_GROK_API_KEY", "").strip()
    payload = {
        "model": model_id or model(),
        "messages": messages,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "temperature": 0.2,
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    owned = client is None
    try:
        with (client or HTTP_CLIENT_FACTORY()) as http:
            response = http.post(BASE_URL, json=payload, headers=headers)
    except httpx.HTTPError:
        raise CopilotProviderError("The AI provider did not respond in time. Try again later.")
    finally:
        payload.clear()
        headers.clear()
    if response.status_code in (401, 403):
        raise CopilotProviderError("The AI provider rejected the configured API key.")
    if response.status_code != 200:
        raise CopilotProviderError("The AI provider returned an error. Try again later.")
    try:
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        usage = body.get("usage") or {}
        tokens_in = int(usage.get("prompt_tokens") or 0)
        tokens_out = int(usage.get("completion_tokens") or 0)
        reply_model = str(body.get("model") or model_id or model())
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise CopilotProviderError("The AI provider returned an unexpected reply.") from exc
    if not isinstance(content, str):
        raise CopilotProviderError("The AI provider returned an unexpected reply.")
    return {"content": content, "model": reply_model, "tokens_in": tokens_in, "tokens_out": tokens_out}
