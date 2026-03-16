"""
ai/transcriber.py — Voice/audio transcription via Groq Whisper.

Uses the shared OpenAI-compatible client from ai.client.
Groq's audio endpoint is identical to OpenAI's — same SDK, different model name.
"""

import logging

from telegram import Bot

from ai.client import get_groq_client
from config import config

logger = logging.getLogger(__name__)

_VOICE_FILENAME = "voice.ogg"
_AUDIO_FILENAME = "audio.mp3"


async def transcribe(bot: Bot, file_id: str, is_voice: bool = True) -> str:
    """
    Download a Telegram voice/audio file and return its transcription.

    Args:
        bot:      Telegram bot instance for file download.
        file_id:  Telegram file_id of the voice or audio message.
        is_voice: True for voice messages (.ogg), False for audio files.

    Returns:
        Transcribed text stripped of whitespace, or empty string on failure.
    """
    tg_file    = await bot.get_file(file_id)
    file_bytes = bytes(await tg_file.download_as_bytearray())
    filename   = _VOICE_FILENAME if is_voice else _AUDIO_FILENAME

    client        = get_groq_client()
    transcription = await client.audio.transcriptions.create(
        file=(filename, file_bytes),
        model=config.groq.whisper_model,
        temperature=0.0,
    )

    return transcription.text.strip() if transcription.text else ""
