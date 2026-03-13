"""
utils/admin_check.py — Admin privilege verification.

is_chat_admin() is called before every admin action.
Works for both groups and supergroups.
In private chats it always returns True (the user is the only participant).

SUPERADMIN_IDS — personal numeric user IDs (bypass all checks).
SUPERADMIN_CHANNELS — channel IDs (e.g. -1001067810422) or usernames
    (e.g. popyachsa) whose posts are treated as superadmin actions.
"""

import os
import logging
from telegram import Update
from telegram.constants import ChatMemberStatus

logger = logging.getLogger(__name__)

_ADMIN_STATUSES = {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER}

# Personal user IDs — numeric only, no negatives
_raw_ids = os.getenv("SUPERADMIN_IDS", "")
_SUPERADMIN_IDS: frozenset[int] = frozenset(
    int(x.strip())
    for x in _raw_ids.split(",")
    if x.strip().lstrip("-").isdigit() and not x.strip().startswith("-")
)

# Channel IDs and/or usernames whose messages are treated as superadmin.
# Accepts both numeric IDs (-1001067810422) and usernames (popyachsa).
_raw_channels = os.getenv("SUPERADMIN_CHANNELS", "")
_SUPERADMIN_CHANNEL_IDS: frozenset[int] = frozenset(
    int(x.strip())
    for x in _raw_channels.split(",")
    if x.strip().lstrip("-").isdigit()
)
_SUPERADMIN_CHANNEL_USERNAMES: frozenset[str] = frozenset(
    x.strip().lstrip("@").lower()
    for x in _raw_channels.split(",")
    if x.strip() and not x.strip().lstrip("-").isdigit()
)

if _SUPERADMIN_IDS or _SUPERADMIN_CHANNEL_IDS or _SUPERADMIN_CHANNEL_USERNAMES:
    logger.info(
        "Superadmins loaded — user_ids=%s channel_ids=%s channel_usernames=%s",
        _SUPERADMIN_IDS, _SUPERADMIN_CHANNEL_IDS, _SUPERADMIN_CHANNEL_USERNAMES,
    )


def _is_superadmin_channel(update: Update) -> bool:
    """
    Check if the message was sent on behalf of a superadmin channel.
    Telegram puts the channel in message.sender_chat when a user posts
    as their channel rather than as themselves.
    """
    message = update.effective_message
    if message is None:
        return False

    sender_chat = message.sender_chat
    if sender_chat is None:
        return False

    if sender_chat.id in _SUPERADMIN_CHANNEL_IDS:
        logger.debug("Superadmin channel match by ID: %d", sender_chat.id)
        return True

    if sender_chat.username and sender_chat.username.lower() in _SUPERADMIN_CHANNEL_USERNAMES:
        logger.debug("Superadmin channel match by username: %s", sender_chat.username)
        return True

    return False


async def is_chat_admin(update: Update) -> bool:
    """
    Return True if the update author has admin privileges.

    Priority order:
        1. Message sent as a superadmin channel (sender_chat check)
        2. User ID is in _SUPERADMIN_IDS
        3. Private chat → always True
        4. Group/supergroup → check Telegram member status
    """
    chat = update.effective_chat
    user = update.effective_user

    if chat is None:
        return False

    if _is_superadmin_channel(update):
        return True

    if user is None:
        return False

    if user.id in _SUPERADMIN_IDS:
        logger.debug("Superadmin access granted user_id=%d", user.id)
        return True

    if chat.type == chat.PRIVATE:
        return True

    try:
        member = await chat.get_member(user.id)
        result = member.status in _ADMIN_STATUSES
        if not result:
            logger.debug(
                "Non-admin action attempt user_id=%d chat_id=%d status=%s",
                user.id, chat.id, member.status,
            )
        return result
    except Exception as exc:
        err = str(exc).lower()

        # Supergroup without bot admin rights — getChatMember is unavailable.
        # This is a known Telegram limitation, not an error worth alerting on.
        if "chat_admin_required" in err:
            logger.debug(
                "getChatMember unavailable (bot lacks admin rights) "
                "user_id=%d chat_id=%d — treating as non-admin",
                user.id, chat.id,
            )
            return False

        # Unexpected errors still get logged at WARNING
        logger.warning(
            "Admin check failed user_id=%d chat_id=%d: %s",
            user.id, chat.id, exc,
        )
        return False
