"""Database creation and default data (categories, settings, admins)."""
from __future__ import annotations

import logging

from sqlalchemy import func, select

from . import models  # noqa: F401  (register tables)
from .config import settings
from .database import Base, SessionLocal, engine
from .models import AdminUser, Category

log = logging.getLogger("seed")

DEFAULT_CATEGORIES = [
    # section, slug, icon, name_uz, name_ru
    ("menu", "set", "⭐", "Bizning set", "Наш сет"),
    ("menu", "breakfast", "🍳", "Nonushta", "Завтрак"),
    ("menu", "first", "🍲", "Birinchi taomlar", "Первые блюда"),
    ("menu", "second", "🍛", "Ikkinchi taomlar", "Вторые блюда"),
    ("menu", "salads", "🥗", "Salatlar", "Салаты"),
    ("menu", "drinks", "🥤", "Ichimliklar", "Напитки"),
    ("sadaqa", "sadaqa_food", "🍱", "Taom sadaqasi", "Садака едой"),
    ("sadaqa", "sadaqa_drinks", "💧", "Ichimlik sadaqasi", "Садака напитками"),
    ("sadaqa", "sadaqa_lunch", "🍛", "Tushlik sadaqasi", "Садака обедом"),
    ("sadaqa", "sadaqa_other", "🤲", "Boshqa sadaqalar", "Другие виды садака"),
    ("events", "events", "🎉", "Tadbirlar", "Мероприятия"),
]


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as s:
        if (await s.execute(select(func.count(Category.id)))).scalar_one() == 0:
            for i, (section, slug, icon, uz, ru) in enumerate(DEFAULT_CATEGORIES):
                s.add(Category(section=section, slug=slug, icon=icon, name_uz=uz, name_ru=ru, sort_order=i))
            log.info("default categories created")
        existing = set((await s.execute(select(AdminUser.telegram_id))).scalars().all())
        for tid in settings.ADMIN_IDS - existing:
            s.add(AdminUser(telegram_id=tid))
        await s.commit()
