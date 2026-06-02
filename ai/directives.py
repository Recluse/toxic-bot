"""
ai/directives.py — maintain the owner's GLOBAL standing instructions.

When the owner replies to the bot, update_directives() runs as a fire-and-forget
task: a lightweight model decides whether the message contains a lasting
instruction/correction/preference/fact, and if so integrates it into the stored
directives blob (db/owner_directives.py). The blob is injected into every system
prompt by ai/responder.py, so the owner can steer the bot's behaviour everywhere
just by talking to it ("don't swear so much", "call me Ruslan", "stop doing X",
"forget the rule about Y").
"""

import logging

from ai.client import groq_client
import db.owner_directives as directives_db
from config import config

logger = logging.getLogger(__name__)

_SENTINEL = "NONE"

_SYSTEM = """You maintain the STANDING INSTRUCTIONS that the bot's owner (its
creator) has given about how the bot should behave and reply. These are lasting
corrections, preferences, rules, and facts-to-remember that apply to ALL future
replies in every chat.

You receive the current instruction list and a new message the owner just sent
to the bot (by replying to it). Decide:

- If the message contains a NEW lasting instruction, correction, preference, or
  fact to remember (examples: "don't swear so much", "call me Ruslan", "always
  use metric units", "stop doing X", "remember that Y", "be shorter"), output the
  FULL updated list with the new item integrated: merge duplicates, drop items
  the owner explicitly cancels or reverses, keep it concise (max ~180 words), as
  short imperative lines, one instruction per line, no numbering, no preamble.
- If the message is just banter, a one-off question, or chit-chat with nothing to
  remember long-term, output exactly: NONE

Write each instruction in the language the owner used. Output ONLY the updated
list, or the single word NONE."""


async def update_directives(owner_id: int, new_message: str, existing: str) -> None:
    """
    Fire-and-forget: integrate a possible new owner directive into the stored
    blob. Exceptions are swallowed — this must never affect the reply flow.
    """
    if not owner_id or not (new_message or "").strip():
        return
    try:
        messages = [
            {"role": "system", "content": _SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Current standing instructions:\n{existing or '(none yet)'}\n\n"
                    f"New message from the owner:\n{new_message}"
                ),
            },
        ]
        response = await groq_client.chat.completions.create(
            model=config.summarizer.model,
            messages=messages,
            temperature=0.2,
            max_tokens=400,
        )
        out = (response.choices[0].message.content or "").strip()
        if not out or out.strip().upper() == _SENTINEL:
            return  # nothing worth remembering in this message
        await directives_db.set_directives(owner_id, out)
        logger.info("Owner directive captured owner_id=%d len=%d", owner_id, len(out))
    except Exception as exc:
        logger.warning("Directive update failed owner_id=%d: %s", owner_id, exc)
