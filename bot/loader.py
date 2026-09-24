"""Shared Bot and Dispatcher instances (used by the bot handlers and by the backend for notifications)."""
from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from backend.config import settings

log = logging.getLogger("bot")

bot: Bot | None = None
if settings.BOT_TOKEN:
    try:
        bot = Bot(token=settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    except Exception as exc:  # invalid token format
        log.error("BOT_TOKEN is invalid: %s", exc)
        bot = None
else:
    log.warning("BOT_TOKEN is empty - the Telegram bot will not start")

dp = Dispatcher()

# filled on startup by bot.main.on_startup
BOT_INFO: dict = {"username": ""}
