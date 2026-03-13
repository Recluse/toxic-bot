"""
ai/client.py — Singleton AsyncOpenAI client routed through Cloudflare AI Gateway.

Both the main responder and the background summarizer import the same client instance.
The Cloudflare gateway URL replaces the standard Groq base URL transparently —
the openai SDK does not know the difference.
"""

import logging
from openai import AsyncOpenAI
from config import config

logger = logging.getLogger(__name__)

logger.info(
    "Initialising Groq client via CF gateway: %s model=%s",
    config.groq.base_url,
    config.groq.model,
)

# Single client instance shared across the whole application.
# Thread-safe for asyncio (one event loop, multiple coroutines).
groq_client = AsyncOpenAI(
    api_key=config.groq.api_key,
    base_url=config.groq.base_url,
)
