"""Добавляет несколько примерных товаров, чтобы сразу увидеть, как выглядит магазин.

Запуск:  python scripts/seed_demo.py
Повторный запуск ничего не дублирует. Примеры потом можно изменить или удалить в админ-панели.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select  # noqa: E402

from backend.database import SessionLocal  # noqa: E402
from backend.models import Category, Product  # noqa: E402
from backend.seed import init_db  # noqa: E402

# slug категории, name_uz, name_ru, desc_uz, desc_ru, цена SAR, остаток
DEMO = [
    ("set", "Baraka seti", "Сет «Барака»", "Palov, salat, non va ichimlik — bir kishiga to‘liq tushlik.",
     "Плов, салат, лепёшка и напиток — полноценный обед на одного.", 35, 15),
    ("breakfast", "Qaymoq bilan non", "Лепёшка с каймаком", "Issiq tandir non, qaymoq va asal.",
     "Горячая лепёшка из тандыра, каймак и мёд.", 12, 10),
    ("first", "Mastava", "Мастава", "Guruchli an’anaviy o‘zbek sho‘rvasi.", "Традиционный узбекский рисовый суп.", 18, 12),
    ("second", "Palov", "Плов", "Mol go‘shti, sabzi va nohatli toshkent palovi.", "Ташкентский плов с говядиной, морковью и нутом.", 25, 20),
    ("salads", "Achchiq-chuchuk", "Ачичук", "Pomidor, piyoz va rayhon salati.", "Салат из помидоров, лука и базилика.", 8, 3),
    ("drinks", "Ko‘k choy", "Зелёный чай", "Choynakda ko‘k choy.", "Чайник зелёного чая.", 5, 30),
    ("sadaqa_food", "Muhtojlarga ovqat", "Обед для нуждающихся", "Bir kishilik issiq ovqat muhtojlarga tarqatiladi.",
     "Горячий обед на одного человека, раздаётся нуждающимся.", 15, 100),
    ("sadaqa_drinks", "Suv sadaqasi (24 dona)", "Садака водой (24 бутылки)", "Ziyoratchilarga suv tarqatiladi.",
     "Вода раздаётся паломникам.", 20, 50),
]


async def main() -> None:
    await init_db()
    async with SessionLocal() as s:
        cats = {c.slug: c for c in (await s.execute(select(Category))).scalars()}
        added = 0
        for slug, nuz, nru, duz, dru, price, stock in DEMO:
            cat = cats.get(slug)
            if not cat:
                continue
            exists = (await s.execute(select(func.count(Product.id)).where(Product.name_ru == nru))).scalar_one()
            if exists:
                continue
            s.add(Product(section=cat.section, category_id=cat.id, name_uz=nuz, name_ru=nru, description_uz=duz,
                          description_ru=dru, price=price * 100, stock=stock))
            added += 1
        await s.commit()
    print(f"✅ Добавлено примерных товаров: {added}")


if __name__ == "__main__":
    asyncio.run(main())
