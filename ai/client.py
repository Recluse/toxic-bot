"""
ai/client.py — Async Groq client singleton via Cloudflare AI Gateway.

Uses the OpenAI-compatible SDK (openai package) pointed at Groq's CF Gateway.
Groq's API is fully OpenAI-compatible — same interface, different base_url.

Exposes:
    chat_completion()    — standard text LLM call
    vision_completion()  — multimodal call with image_url content
    get_groq_client()    — raw AsyncOpenAI instance (audio transcriptions etc.)
    groq_client          — module-level alias, used by commands_public for direct calls
"""

import logging

from openai import AsyncOpenAI

from config import config

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None


def _is_over_capacity_error(exc: Exception) -> bool:
    """Detect Groq over-capacity errors for fallback routing."""
    status = getattr(exc, "status_code", None)
    msg = str(exc).lower()
    return status == 503 or "over capacity" in msg


def get_groq_client() -> AsyncOpenAI:
    """Return the shared AsyncOpenAI instance pointed at Groq, creating on first call."""
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=config.groq.api_key,
            base_url=config.groq.base_url,
        )
    return _client


async def chat_completion(messages: list[dict], **kwargs) -> str:
    """Call the standard chat completions endpoint."""
    client = get_groq_client()

    model = kwargs.get("model", config.groq.model)
    temperature = kwargs.get("temperature", config.groq.temperature)
    max_tokens = kwargs.get("max_tokens", config.groq.max_tokens)
    top_p = kwargs.get("top_p", config.groq.top_p)

    logger.debug("chat_completion request: model=%s messages=%s", model, messages)
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
        )
    except Exception as exc:
        fallback_model = config.groq.fallback_model
        if _is_over_capacity_error(exc) and model != fallback_model:
            logger.warning(
                "Primary model over capacity (%s). Falling back to %s",
                model,
                fallback_model,
            )
            response = await client.chat.completions.create(
                model=fallback_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                top_p=top_p,
            )
        else:
            raise

    reply = response.choices[0].message.content
    logger.debug("chat_completion response: %s", reply)
    return reply


async def vision_completion(messages: list[dict], **kwargs) -> str:
    """Call the vision-capable model (Llama 4 Scout)."""
    client = get_groq_client()

    logger.debug("vision_completion request: model=%s messages=%s", config.groq.vision_model, messages)
    response = await client.chat.completions.create(
        model=      config.groq.vision_model,
        messages=   messages,
        temperature=kwargs.get("temperature", config.groq.temperature),
        max_tokens= kwargs.get("max_tokens",  config.groq.max_tokens),
        top_p=      kwargs.get("top_p",       config.groq.top_p),
    )
    reply = response.choices[0].message.content
    logger.debug("vision_completion response: %s", reply)
    return reply


groq_client: AsyncOpenAI = get_groq_client()
