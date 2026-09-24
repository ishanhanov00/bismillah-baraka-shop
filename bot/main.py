"""Bot startup (long polling). Started automatically by run.py together with the web server."""
from __future__ import annotations

import asyncio
import logging

from aiogram.exceptions import TelegramUnauthorizedError

from aiogram.types import BotCommand, BotCommandScopeChat, MenuButtonWebApp, WebAppInfo

from backend.config import settings
from . import loader
from .handlers import router

log = logging.getLogger("bot")
_router_added = False


async def on_startup() -> None:
    bot = loader.bot
    me = await bot.get_me()
    loader.BOT_INFO["username"] = me.username
    log.info("Bot started: @%s", me.username)
    await bot.set_my_commands([BotCommand(command="start", description="🛍 Do'kon / Магазин"),
                               BotCommand(command="lang", description="🌐 Til / Язык")])
    for admin_id in settings.ADMIN_IDS:
        try:
            await bot.set_my_commands([BotCommand(command="start", description="🛍 Do'kon / Магазин"),
                                       BotCommand(command="admin", description="👨‍💼 Admin panel"),
                                       BotCommand(command="lang", description="🌐 Til / Язык")],
                                      scope=BotCommandScopeChat(chat_id=admin_id))
        except Exception:
            pass  # the admin has not started the bot yet
    if settings.WEBAPP_URL.startswith("https://"):
        await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(
            text="🛍 Do'kon", web_app=WebAppInfo(url=settings.WEBAPP_URL + "/")))
    else:
        log.warning("WEBAPP_URL must start with https:// - Mini App buttons are disabled")


async def start_polling() -> None:
    global _router_added
    if loader.bot is None:
        log.error("Bot is not started: BOT_TOKEN is missing or invalid")
        return
    if not _router_added:
        loader.dp.include_router(router)
        _router_added = True
    delay = 5
    while True:
        try:
            await on_startup()
            await loader.dp.start_polling(loader.bot, handle_signals=False)
            return
        except TelegramUnauthorizedError:
            log.error("❌ Неверный BOT_TOKEN: Telegram отклонил токен. Проверьте .env и перезапустите. Сайт продолжает работать.")
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # no internet / Telegram unavailable - try again later
            log.error("Бот не смог подключиться к Telegram (%s). Повтор через %s сек.", exc, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 120)


async def stop_polling() -> None:
    try:
        await loader.dp.stop_polling()
    except Exception:
        pass
    if loader.bot is not None:
        await loader.bot.session.close()
