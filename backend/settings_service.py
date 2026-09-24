"""Business settings stored in the `settings` table (editable from the admin panel)."""
from __future__ import annotations

from datetime import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .models import Setting
from .utils import local_now

DEFAULTS: dict[str, str] = {
    "business_name": settings.BUSINESS_NAME,
    "logo_path": "",
    "description_uz": "Makkadagi mazali uy taomlari, sadaqa va tadbirlar",
    "description_ru": "Вкусная домашняя еда, садака и мероприятия в Мекке",
    "phone": "",
    "whatsapp": "",
    "instagram": "",
    "address": "Makka",
    "work_hours_text": "",
    "bank_name": "",
    "bank_recipient": "",
    "bank_iban": "",
    "bank_account": "",
    "bank_extra": "",
    "welcome_uz": "Assalomu alaykum! {name} do'koniga xush kelibsiz. Buyurtma berish uchun quyidagi tugmani bosing.",
    "welcome_ru": "Ассаляму алейкум! Добро пожаловать в {name}. Нажмите кнопку ниже, чтобы открыть магазин.",
    "primary_language": settings.PRIMARY_LANGUAGE,
    "currency": settings.CURRENCY,
    "store_open": "1",               # master switch: 1 = open (by hours), 0 = closed
    "open_time": "08:00",
    "close_time": "23:00",
    "allow_orders_when_closed": "0",
    "delivery_enabled": "1",
    "pickup_enabled": "1",
    "low_stock_threshold": "5",
}

BOOL_KEYS = {"store_open", "allow_orders_when_closed", "delivery_enabled", "pickup_enabled"}
INT_KEYS = {"low_stock_threshold"}
PUBLIC_KEYS = [
    "business_name", "logo_path", "description_uz", "description_ru", "phone", "whatsapp",
    "instagram", "address", "work_hours_text", "primary_language", "currency", "open_time",
    "close_time", "allow_orders_when_closed", "delivery_enabled", "pickup_enabled",
    "low_stock_threshold", "store_open",
]
BANK_KEYS = ["bank_name", "bank_recipient", "bank_iban", "bank_account", "bank_extra"]


async def load_settings(session: AsyncSession) -> dict[str, str]:
    rows = (await session.execute(select(Setting))).scalars().all()
    data = dict(DEFAULTS)
    data.update({r.key: r.value for r in rows})
    return data


async def save_settings(session: AsyncSession, values: dict[str, str]) -> None:
    for key, value in values.items():
        if key not in DEFAULTS:
            continue
        row = await session.get(Setting, key)
        if row is None:
            session.add(Setting(key=key, value=str(value)))
        else:
            row.value = str(value)
    await session.commit()


def typed(data: dict[str, str]) -> dict:
    out: dict = {}
    for k, v in data.items():
        if k in BOOL_KEYS:
            out[k] = str(v) in {"1", "true", "True"}
        elif k in INT_KEYS:
            try:
                out[k] = int(v)
            except ValueError:
                out[k] = int(DEFAULTS[k])
        else:
            out[k] = v
    return out


def _parse_time(value: str, fallback: str) -> time:
    try:
        h, m = (value or fallback).split(":")[:2]
        return time(int(h), int(m))
    except (ValueError, TypeError):
        h, m = fallback.split(":")
        return time(int(h), int(m))


def is_open_now(data: dict[str, str]) -> bool:
    if str(data.get("store_open", "1")) not in {"1", "true", "True"}:
        return False
    start = _parse_time(data.get("open_time", ""), "08:00")
    end = _parse_time(data.get("close_time", ""), "23:00")
    now = local_now().time().replace(second=0, microsecond=0)
    if start == end:
        return True  # open 24h
    if start < end:
        return start <= now < end
    return now >= start or now < end  # overnight, e.g. 18:00 - 02:00


def can_order_now(data: dict[str, str]) -> bool:
    return is_open_now(data) or str(data.get("allow_orders_when_closed", "0")) in {"1", "true", "True"}
