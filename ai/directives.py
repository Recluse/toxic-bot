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

_SYSTEM = """You maintain the STANDING INSTRUCTIONS the bot's owner (its creator) has
EXPLICITLY given about how the bot ITSELF should behave in future replies. These are
lasting, deliberate directives the owner states TO THE BOT: corrections of the bot,
preferences about the bot's behaviour, rules for the bot to follow, or a fact the owner
explicitly tells the bot to remember.

You receive the current instruction list and a new message the owner just sent to the bot.

Capture a new item ONLY when the message is an EXPLICIT, DELIBERATE instruction to the
bot, e.g.:
  - "don't swear so much" / "be shorter" / "stop doing X"
  - "call me Ruslan"  (an explicit request about how to address the owner)
  - "always use metric units" / "remember to always do Y"
  - "forget the rule about Z"  (cancels an existing item — drop it)

Do NOT infer instructions from what the owner is merely TALKING ABOUT. If the owner is
discussing a topic, a movie, a show, a person or an event, telling a joke, asking a
one-off question, correcting a FACT in the bot's answer, or just chatting — there is
NOTHING to store. In particular, a name that appears in the conversation (a character, a
show's title, someone else) is NOT a request to be called that name. When in any doubt,
or when the message is not a clear, direct order about the bot's own behaviour, output
exactly: NONE.

When you DO capture something, output the FULL updated list with the new item integrated:
merge duplicates, drop items the owner cancels or reverses, keep it concise (max ~180
words), as short imperative lines, one per line, no numbering, no preamble. Write each
line in the language the owner used.

Output ONLY the updated list, or the single word NONE. Bias strongly toward NONE."""


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
