"""Project configuration. All secrets are read from the .env file (never hard-coded)."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "da", "ha"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


def _ids(name: str) -> set[int]:
    raw = os.getenv(name, "")
    result: set[int] = set()
    for part in raw.replace(";", ",").replace(" ", ",").split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            result.add(int(part))
    return result


class Settings:
    # Telegram
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()
    ADMIN_IDS: set[int] = _ids("ADMIN_IDS")
    WEBAPP_URL: str = os.getenv("WEBAPP_URL", "").strip().rstrip("/")
    # Chat for new-order notifications: "@public_group_username" or numeric id like -1001234567890
    NOTIFY_CHAT_ID: str = os.getenv("NOTIFY_CHAT_ID", "").strip()
    NOTIFY_ADMINS_PRIVATE: bool = _bool("NOTIFY_ADMINS_PRIVATE", True)
    ADMIN_LANGUAGE: str = os.getenv("ADMIN_LANGUAGE", "ru").strip() or "ru"
    RUN_BOT: bool = _bool("RUN_BOT", True)

    # Security
    SECRET_KEY: str = os.getenv("SECRET_KEY", "").strip()
    INITDATA_MAX_AGE: int = _int("INITDATA_MAX_AGE", 86400)
    DEV_MODE: bool = _bool("DEV_MODE", False)
    DEV_USER_ID: int = _int("DEV_USER_ID", 0)

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "").strip() or f"sqlite+aiosqlite:///{BASE_DIR / 'database' / 'shop.db'}"

    # Server
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = _int("PORT", 8000)

    # Business defaults (can be changed later from the admin panel)
    BUSINESS_NAME: str = os.getenv("BUSINESS_NAME", "BISMILLAH BARAKA")
    CURRENCY: str = os.getenv("CURRENCY", "SAR")
    PRIMARY_LANGUAGE: str = os.getenv("PRIMARY_LANGUAGE", "uz")
    TIMEZONE: str = os.getenv("TIMEZONE", "Asia/Riyadh")
    ORDER_NUMBER_OFFSET: int = _int("ORDER_NUMBER_OFFSET", 1000)

    # Files
    MAX_UPLOAD_MB: int = _int("MAX_UPLOAD_MB", 8)
    UPLOAD_DIR: Path = BASE_DIR / "uploads"
    FRONTEND_DIR: Path = BASE_DIR / "frontend"
    STATIC_DIR: Path = BASE_DIR / "static"


settings = Settings()

LANGUAGES = ("uz", "ru")
SECTIONS = ("menu", "sadaqa", "events")


def is_admin(telegram_id: int | None) -> bool:
    return telegram_id is not None and int(telegram_id) in settings.ADMIN_IDS
