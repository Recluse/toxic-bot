"""
bot.py — Application entry point.

Responsibilities:
    - Load config and validate environment on startup
    - Run DB migrations
    - Initialise the DB connection pool
    - Register all command and message handlers
    - Register the single global CallbackQueryHandler
    - Start polling
"""

import asyncio
import logging
import os
import socket
import time
from datetime import datetime

import httpx
from telegram import Update
from telegram.error import NetworkError
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    ChatMemberHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    TypeHandler,
    filters,
)

from config import config
from db.pool import init_pool, close_pool
from db.migrations import run_migrations

# --- Handlers ---
from handlers.commands_public import (
    cmd_start,
    cmd_help,
    cmd_about,
    cmd_reset,
    cmd_toxic,
    cmd_dont_touch_me,
)
from handlers.commands_explain import cmd_explain
from handlers.messages import handle_message
from handlers.admin_menu.router import route_callback
from handlers.lifecycle import handle_my_chat_member
from handlers.superadmin import (
    cmd_sa_chats,
    cmd_sa_stats,
    cmd_directives,
    broadcast_conversation,
)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Network resilience (added 2026-07-26 after a 22-day wedge).
#
# Failure that took the bot silent while systemd still reported "active":
# the egress proxy (10.42.42.2:10809) silently tore down the long-poll tunnels,
# but httpx left the sockets half-closed (CLOSE-WAIT). Over weeks they piled up
# and filled the connection pool, so every getUpdates/send failed with
# "Pool timeout: All connections in the connection pool are occupied" — the bot
# could neither receive nor send. Finite read timeouts alone didn't catch it
# because the dead sockets never produced a read to time out.
#
# The combo below:
#   (a) keepalive_expiry — recycle idle pooled connections before the proxy kills
#       them (httpx.Limits on our own transport);
#   (b) TCP keepalive socket options — the kernel probes the peer and errors a
#       silently-dropped connection within ~1 min, so httpx reconnects instead of
#       lingering in CLOSE-WAIT;
#   (c) a liveness watchdog (see _watchdog) as a last-resort backstop.
# ---------------------------------------------------------------------------

_WATCHDOG_INTERVAL = 60.0      # seconds between liveness probes
_WATCHDOG_MAX_FAILS = 3        # consecutive failed probes → force restart (~3 min)

# Startup network-flap resilience (added 2026-08-23). PTB's Application.initialize()
# calls get_me() BEFORE the polling bootstrap, and that call is NOT covered by
# bootstrap_retries — so a proxy/TLS ConnectTimeout at startup raised an unhandled
# telegram.error.TimedOut and killed the process, which systemd then crash-looped
# until the proxy recovered (observed 2026-08-23: ~04:20 and ~11:58 MSK, ~5 and ~15
# restarts). main() now retries startup in-process (fresh event loop + rebuilt
# Application) and reports the flap to superadmins once it comes back up.
_STARTUP_BACKOFF_START = 5.0    # seconds before the first retry
_STARTUP_BACKOFF_MAX = 60.0     # backoff cap
_startup_flap_attempts = 0      # failed startup attempts before the current successful start


def _keepalive_socket_options() -> list[tuple]:
    """TCP-keepalive setsockopt tuples. The Linux-specific knobs are guarded with
    hasattr so the module still imports on dev boxes (Windows/macOS lack them)."""
    opts: list[tuple] = [(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)]
    if hasattr(socket, "TCP_KEEPIDLE"):
        opts.append((socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30))   # idle → first probe
    if hasattr(socket, "TCP_KEEPINTVL"):
        opts.append((socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10))  # probe interval
    if hasattr(socket, "TCP_KEEPCNT"):
        opts.append((socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3))     # 3 misses → dead (~60s)
    return opts


def _build_transport(proxy: str | None, pool_size: int) -> httpx.AsyncHTTPTransport:
    """A dedicated httpx transport carrying the proxy, TCP keepalive and a finite
    keepalive_expiry. NOTE: because PTB hands a custom transport to httpx, the
    client-level `proxy` and `limits` are ignored — so BOTH must live here or the
    bot would bypass the RKN egress proxy and lose its pool caps."""
    return httpx.AsyncHTTPTransport(
        proxy=proxy or None,
        http1=True,
        http2=False,
        retries=1,
        limits=httpx.Limits(
            max_connections=pool_size,
            max_keepalive_connections=pool_size,
            keepalive_expiry=30.0,
        ),
        socket_options=_keepalive_socket_options(),
    )


async def _watchdog(application: Application) -> None:
    """Active liveness backstop. Periodically calls get_me() through the same
    request pool the bot uses to send. If it fails _WATCHDOG_MAX_FAILS times in a
    row the request path is wedged (e.g. pool exhausted by dead proxy sockets) —
    log CRITICAL and exit so systemd (Restart=always, 5s) restarts us. The 60s
    spacing keeps us well under the unit's StartLimitBurst, so this never
    crash-loops the service."""
    fails = 0
    while True:
        await asyncio.sleep(_WATCHDOG_INTERVAL)
        try:
            await application.bot.get_me(
                read_timeout=15, connect_timeout=15, pool_timeout=15
            )
            fails = 0
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            fails += 1
            logger.warning(
                "Watchdog probe failed (%d/%d): %s", fails, _WATCHDOG_MAX_FAILS, exc
            )
            if fails >= _WATCHDOG_MAX_FAILS:
                logger.critical(
                    "Watchdog: %d consecutive failed probes — request path wedged; "
                    "forcing exit for systemd to restart.",
                    fails,
                )
                os._exit(1)


async def _on_startup(application: Application) -> None:
    """
    Post-init hook: runs after the Application is built but before polling starts.
    Order matters: pool first, migrations second.
    """
    await init_pool()
    await run_migrations()
    logger.info(
        "Bot started — model=%s vision=%s whisper=%s gateway=%s superadmins=%s",
        config.groq.model,
        config.groq.vision_model,
        config.groq.whisper_model,
        config.groq.base_url,
        list(config.superadmin_ids),
    )
    await _notify_superadmins_startup(application)

    # Start the liveness watchdog on the polling loop (cancelled on shutdown).
    application.bot_data["_watchdog_task"] = asyncio.create_task(_watchdog(application))


async def _notify_superadmins_startup(application: Application) -> None:
    """
    Send a one-shot "bot is up" PM to every SUPERADMIN_ID.
    Failures (blocked bot, never-PMd-bot, etc.) are logged but do not
    interrupt startup — the bot must keep coming up regardless.
    """
    if not config.superadmin_ids:
        return

    text = (
        "🟢 <b>TOXIC bot started</b>\n"
        f"Model: <code>{config.groq.model}</code>\n"
        f"Time:  <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>"
    )
    # If we only came up after retrying through a network flap, say so — a silent
    # restart otherwise looks mysterious (see main()'s startup-retry loop).
    if _startup_flap_attempts > 0:
        text += (
            f"\n⚠️ <b>Был флап сети:</b> поднялись с попытки "
            f"№{_startup_flap_attempts + 1} — прокси/TLS не отвечал на старте, "
            f"переподключились."
        )

    for sa_id in config.superadmin_ids:
        try:
            await application.bot.send_message(
                chat_id=sa_id,
                text=text,
                parse_mode="HTML",
            )
        except Exception as exc:
            # Most common: superadmin has never PMd the bot, or blocked it.
            logger.warning(
                "Startup notification to superadmin %d failed: %s",
                sa_id, exc,
            )


async def _on_shutdown(application: Application) -> None:
    """Graceful shutdown: stop the watchdog, then drain the DB pool."""
    task = application.bot_data.get("_watchdog_task")
    if task is not None:
        task.cancel()
    await close_pool()
    logger.info("Bot stopped, DB pool closed")


async def _error_handler(update: object, context) -> None:
    """
    Global error handler — catches all unhandled exceptions from any handler.
    Prevents silent crashes and missing tracebacks in logs.
    """
    logger.error(
        "Unhandled exception processing update: %s",
        context.error,
        exc_info=context.error,
    )


def _add_settings_command(app: Application) -> None:
    """
    Register /settings as an alias that opens the main admin menu directly.
    Defined here to avoid a circular import between bot.py and admin_menu/.
    """
    from handlers.admin_menu.main_menu import send_main_menu
    from handlers.pm_settings import send_pm_settings_menu
    import db.chat_settings as settings_db
    from utils.admin_check import is_chat_admin
    from i18n import get_text
    from telegram.constants import ChatType

    async def cmd_settings(update, context):
        if update.effective_chat.type == ChatType.PRIVATE:
            settings = await settings_db.get_or_create(update.effective_chat.id)
            await send_pm_settings_menu(update, context, lang=settings["lang"], edit=False)
            return

        if not await is_chat_admin(update):
            try:
                await update.message.delete()
            except Exception:
                pass
            return

        settings = await settings_db.get_or_create(update.effective_chat.id)
        await send_main_menu(update, context, lang=settings["lang"], edit=False)

        # Remove the /settings command message in group chats to keep chat clean.
        try:
            await update.message.delete()
        except Exception:
            pass

    app.add_handler(CommandHandler("settings", cmd_settings))


# --- Duplicate-update guard (added 2026-08-24) ---
# Telegram getUpdates can redeliver an update if the offset ack didn't land (the
# egress proxy blipping is enough). Without dedup the same message is processed
# twice — observed 2026-08-24 as a full reply followed by a stray "one question a
# minute" cooldown quip on the SAME message (msg 818149). We drop any update_id
# already handled, before any other handler runs.
_SEEN_UPDATE_MAX = 2048
_seen_update_ids: dict[int, None] = {}


async def _dedupe_guard(update: Update, context) -> None:
    """Drop a redelivered update (same update_id) before any handler runs."""
    uid = getattr(update, "update_id", None)
    if uid is None:
        return
    if uid in _seen_update_ids:
        logger.warning("Duplicate update_id=%d dropped (getUpdates redelivery)", uid)
        raise ApplicationHandlerStop
    _seen_update_ids[uid] = None
    if len(_seen_update_ids) > _SEEN_UPDATE_MAX:
        # dict preserves insertion order → the first key is the oldest
        _seen_update_ids.pop(next(iter(_seen_update_ids)))


# --- anti-flood / ban guard (added 2026-06-03) ---
_BANNED_IDS = {376895691}
_flood_hits = {}
_FLOOD_MAX = 12
_FLOOD_WINDOW = 10.0


async def _antiflood_guard(update: Update, context) -> None:
    user = update.effective_user
    if user is None:
        return
    uid = user.id
    if uid in _BANNED_IDS:
        raise ApplicationHandlerStop
    import time as _t
    now = _t.monotonic()
    hits = _flood_hits.setdefault(uid, [])
    cutoff = now - _FLOOD_WINDOW
    while hits and hits[0] < cutoff:
        hits.pop(0)
    hits.append(now)
    if len(hits) > _FLOOD_MAX:
        raise ApplicationHandlerStop


def _build_application() -> Application:
    """Construct a fresh Application with all handlers wired up.

    Called once per startup attempt (see main()), so a start retried after a
    network flap begins from clean state.
    """
    # Explicit finite timeouts so a wedged long-poll (e.g. the egress proxy silently
    # dropping the getUpdates connection) raises ReadTimeout and PTB reconnects, instead
    # of hanging forever in epoll_wait. get_updates read_timeout must exceed run_polling's
    # `timeout`. Proxy is taken from HTTPS_PROXY/HTTP_PROXY env (the k8s/recluse egress proxy)
    # and carried on a custom transport together with TCP keepalive + keepalive_expiry — see
    # _build_transport for why proxy MUST live on the transport, not the client.
    _proxy = (os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
              or os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy") or None)
    _req_kw = dict(connect_timeout=10.0, write_timeout=20.0, pool_timeout=10.0)
    app = (
        Application.builder()
        .token(config.telegram_token)
        .request(HTTPXRequest(
            read_timeout=20.0,
            httpx_kwargs={"transport": _build_transport(_proxy, pool_size=8)},
            **_req_kw,
        ))
        .get_updates_request(HTTPXRequest(
            read_timeout=45.0,
            httpx_kwargs={"transport": _build_transport(_proxy, pool_size=2)},
            **_req_kw,
        ))
        .post_init(_on_startup)
        .post_shutdown(_on_shutdown)
        .build()
    )

    app.add_error_handler(_error_handler)

    # --- Track bot membership changes in all chats ---
    app.add_handler(
        ChatMemberHandler(handle_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER)
    )

    # --- Superadmin commands (PM only) ---
    app.add_handler(broadcast_conversation)
    app.add_handler(CommandHandler("sa_chats",    cmd_sa_chats,    filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("sa_stats",    cmd_sa_stats,    filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("directives",  cmd_directives,  filters=filters.ChatType.PRIVATE))

    # --- Public commands ---
    app.add_handler(CommandHandler("start",         cmd_start))
    app.add_handler(CommandHandler("help",          cmd_help))
    app.add_handler(CommandHandler("about",         cmd_about))
    app.add_handler(CommandHandler("reset",         cmd_reset))
    app.add_handler(CommandHandler("toxic",         cmd_toxic))
    app.add_handler(CommandHandler("dont_touch_me", cmd_dont_touch_me))
    app.add_handler(CommandHandler("explain",       cmd_explain))

    # --- Admin settings menu ---
    _add_settings_command(app)

    # --- All inline keyboard callbacks routed through a single handler ---
    app.add_handler(CallbackQueryHandler(route_callback))

    # --- Main message handler — text, photos, voice, audio ---
    app.add_handler(
        MessageHandler(
            (filters.TEXT | filters.PHOTO | filters.VOICE | filters.AUDIO)
            & ~filters.COMMAND,
            handle_message,
        )
    )

    # duplicate-update dedup runs before everything (group -2), so a redelivered
    # update is dropped before it can trigger a second reply.
    app.add_handler(TypeHandler(Update, _dedupe_guard), group=-2)

    # anti-flood / ban guard runs before all other handlers (group -1)
    app.add_handler(TypeHandler(Update, _antiflood_guard), group=-1)
    return app


def main() -> None:
    """Build and run the bot, retrying startup across network flaps.

    PTB's run_polling runs Application.initialize() (which calls get_me()) BEFORE the
    polling bootstrap, and that get_me() is NOT covered by bootstrap_retries. A
    proxy/TLS ConnectTimeout there used to raise an unhandled telegram.error.TimedOut
    and drop the process into a systemd crash-loop until the proxy recovered. Here we
    instead catch NetworkError, back off, and retry in-process with a fresh event loop
    (run_polling does get_event_loop() then loop.close(), so a retry must supply a new,
    open loop) and a freshly-built Application. Non-network errors (bad token, bugs)
    still propagate and crash loudly. On the successful start after >=1 failed attempt,
    _on_startup reports the flap to superadmins.
    """
    global _startup_flap_attempts
    _startup_flap_attempts = 0
    backoff = _STARTUP_BACKOFF_START
    while True:
        asyncio.set_event_loop(asyncio.new_event_loop())
        app = _build_application()
        try:
            logger.info("Starting polling")
            app.run_polling(
                allowed_updates=Update.ALL_TYPES,
                timeout=30,            # long-poll seconds (< get_updates read_timeout=45)
                poll_interval=1.0,
                bootstrap_retries=-1,  # retry forever on the getUpdates bootstrap
            )
            return  # clean shutdown (SIGTERM/SIGINT) — do not retry
        except NetworkError as exc:
            _startup_flap_attempts += 1
            logger.warning(
                "Startup network error (attempt %d): %s — retrying in %.0fs",
                _startup_flap_attempts, exc, backoff,
            )
            time.sleep(backoff)
            backoff = min(backoff * 2, _STARTUP_BACKOFF_MAX)


if __name__ == "__main__":
    main()
