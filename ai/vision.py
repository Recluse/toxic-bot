"""
ai/vision.py — Image extraction helpers for Groq vision API.

Downloads a Telegram photo by file_id, encodes it as base64,
and builds a multimodal message dict ready for chat.completions.
Max base64 payload accepted by Groq is 4 MB — Telegram photo sizes
are always well within that limit.
"""

import base64
import logging

from telegram import Bot

logger = logging.getLogger(__name__)


async def get_image_base64(bot: Bot, file_id: str) -> str:
    """Download a Telegram file and return it as a base64-encoded string."""
    tg_file    = await bot.get_file(file_id)
    file_bytes = await tg_file.download_as_bytearray()
    return base64.b64encode(bytes(file_bytes)).decode("utf-8")


def build_vision_message(image_base64: str, prompt: str) -> dict:
    """
    Build a single user message with an inline base64 image and text prompt.
    The image must come before the text in the content array — Groq requires
    this ordering for correct multimodal processing.
    """
    return {
        "role": "user",
        "content": [
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{image_base64}",
                },
            },
            {
                "type": "text",
                "text": prompt,
            },
        ],
    }
