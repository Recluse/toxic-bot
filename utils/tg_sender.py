"""
utils/tg_sender.py — Resolve sender identity for Telegram messages.

Telegram messages in groups can be authored either by a user (`from_user`)
or on behalf of a channel (`sender_chat`).
This helper normalizes both cases into a single (id, display_name) tuple.
"""

from telegram import Message, User


def resolve_message_actor(
    message: Message,
    fallback_user: User | None = None,
) -> tuple[int | None, str | None, bool]:
    """Return normalized actor identity for a message.

    Returns:
        actor_id: numeric Telegram ID (user ID or sender_chat ID)
        actor_name: preferred display name ("@username" if available)
        is_channel_sender: True when the message is sent via sender_chat
    """

    sender_chat = getattr(message, "sender_chat", None)
    if sender_chat is not None:
        channel_username = getattr(sender_chat, "username", None)
        actor_name = (
            channel_username
            if channel_username
            else (sender_chat.title or f"channel_{abs(sender_chat.id)}")
        )
        return sender_chat.id, actor_name, True

    user = message.from_user or fallback_user
    if user is None:
        return None, None, False

    actor_name = user.username or user.full_name or f"user_{user.id}"
    return user.id, actor_name, False
