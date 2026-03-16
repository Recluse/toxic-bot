"""
ai/modes.py — Bot operating mode constants.

BotMode determines which system prompt and reply pipeline is used.
Keeping this as a StrEnum allows direct comparison with string literals
and safe serialisation without extra conversion.
"""

from enum import Enum


class BotMode(str, Enum):
    CHAT    = "chat"    # Toxic Wednesday persona, level 1-5
    EXPLAIN = "explain" # Scientific pedant, no toxicity, factual analysis
