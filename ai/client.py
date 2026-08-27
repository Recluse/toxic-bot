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
import re

from openai import AsyncOpenAI

from config import config

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None


def _is_over_capacity_error(exc: Exception) -> bool:
    """Detect Groq over-capacity errors for fallback routing."""
    status = getattr(exc, "status_code", None)
    msg = str(exc).lower()
    return status == 503 or "over capacity" in msg


def _is_request_too_large(exc: Exception) -> bool:
    """Detect Groq 413 / TPM rate-limit / context-too-large errors."""
    status = getattr(exc, "status_code", None)
    msg = str(exc).lower()
    return (
        status == 413
        or "request too large" in msg
        or "rate_limit" in msg
        or "tokens per minute" in msg
        or "reduce your message size" in msg
    )


def _trim_messages_for_retry(messages: list[dict], keep_recent: int = 4) -> list[dict]:
    """Shrink an over-budget request: keep the system prompt (messages[0]) plus the
    most recent `keep_recent` turns, dropping older history / reply-chain context."""
    if len(messages) <= keep_recent + 1:
        return messages
    return [messages[0]] + messages[-keep_recent:]


def _trim_to_last_sentence(text: str) -> str:
    """Trim a truncated reply back to its last complete sentence so a reply that
    hit the token ceiling doesn't end mid-word. If the last sentence boundary is in
    the first half of the text, return it unchanged (better a rough cut than losing
    most of the reply)."""
    text = (text or "").rstrip()
    if not text:
        return text
    cut = max(text.rfind(c) for c in ".!?…")
    if cut < len(text) * 0.5:
        return text
    end = cut + 1
    while end < len(text) and text[end] in "»\"')]":
        end += 1
    return text[:end].rstrip()


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
        elif _is_request_too_large(exc):
            # TPM / context ceiling (Groq 413): retry once with trimmed context
            # (system prompt + most recent turns) and a smaller output budget, so
            # the bot still replies — with less memory — instead of erroring out.
            trimmed = _trim_messages_for_retry(messages)
            retry_tokens = min(max_tokens, 1024)
            logger.warning(
                "Request too large / rate-limited (%s) — retrying with %d/%d msgs, max_tokens=%d",
                exc, len(trimmed), len(messages), retry_tokens,
            )
            response = await client.chat.completions.create(
                model=model,
                messages=trimmed,
                temperature=temperature,
                max_tokens=retry_tokens,
                top_p=top_p,
            )
        else:
            raise

    choice = response.choices[0]
    reply = choice.message.content or ""
    # A reply that hit the token ceiling stops mid-word; trim back to the last
    # complete sentence so it never looks abruptly chopped. get_reply gives chat
    # replies a 2048-token budget, so this rarely triggers.
    if choice.finish_reason == "length":
        reply = _trim_to_last_sentence(reply)
        logger.info("chat_completion hit max_tokens — trimmed to last sentence (len=%d)", len(reply))
    logger.debug("chat_completion response: %s", reply)
    return reply


async def vision_completion(messages: list[dict], **kwargs) -> str:
    """Call the vision-capable model (qwen3.6-27b via Groq).

    qwen3.6 is a reasoning model: it prefixes its answer with a <think>…</think>
    block. Give it extra room so the reasoning tokens do not starve the actual
    description, and strip the reasoning block before returning so only the
    factual description reaches the text model downstream.
    """
    client = get_groq_client()

    logger.debug("vision_completion request: model=%s messages=%s", config.groq.vision_model, messages)
    response = await client.chat.completions.create(
        model=      config.groq.vision_model,
        messages=   messages,
        temperature=kwargs.get("temperature", config.groq.temperature),
        max_tokens= kwargs.get("max_tokens",  max(config.groq.max_tokens, 2048)),
        top_p=      kwargs.get("top_p",       config.groq.top_p),
    )
    reply = response.choices[0].message.content or ""
    # Strip the reasoning model's <think>…</think> preamble.
    reply = re.sub(r"(?is)<think>.*?</think>", "", reply).strip()
    logger.debug("vision_completion response: %s", reply)
    return reply


groq_client: AsyncOpenAI = get_groq_client()
