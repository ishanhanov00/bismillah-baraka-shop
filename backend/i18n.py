"""Server-side texts (bot messages, notifications). The Mini App has its own dictionary in frontend/js/i18n.js."""
from __future__ import annotations

TEXTS: dict[str, dict[str, str]] = {
    "uz": {
        "status.new": "🆕 Yangi",
        "status.awaiting_payment": "💳 To'lov kutilmoqda",
        "status.payment_review": "🔎 To'lov tekshirilmoqda",
        "status.paid": "✅ To'langan",
        "status.cooking": "👨‍🍳 Tayyorlanmoqda",
        "status.ready": "📦 Tayyor",
        "status.delivering": "🚚 Yetkazilmoqda",
        "status.done": "✅ Bajarildi",
        "status.cancelled": "❌ Bekor qilindi",
        "pay.cash": "💵 Naqd pul",
        "pay.transfer": "🏦 Bank o'tkazmasi",
        "delivery.delivery": "🚚 Yetkazib berish",
        "delivery.pickup": "🏃 Olib ketish",
        "btn.open_shop": "🛍 Do'konni ochish",
        "btn.admin": "👨‍💼 Admin panel",
        "btn.share_phone": "📱 Telefon raqamni yuborish",
        "btn.open_order": "🧾 Buyurtmani ochish",
        "bot.phone_saved": "✅ Rahmat! Telefon raqamingiz saqlandi: {phone}",
        "bot.phone_foreign": "Iltimos, o'zingizning raqamingizni yuboring.",
        "bot.no_webapp": "⚠️ Do'kon hali sozlanmagan (WEBAPP_URL ko'rsatilmagan).",
        "bot.help": "🛍 Do'konni ochish uchun /start buyrug'ini yuboring.",
        "bot.lang_set": "✅ Til o'zgartirildi: O'zbekcha",
        "client.status_changed": "🔔 Buyurtma №{number}\nHolati: {status}",
        "client.payment_confirmed": "✅ Buyurtma №{number} bo'yicha to'lov tasdiqlandi. Rahmat!",
        "client.payment_rejected": "❌ Buyurtma №{number} bo'yicha chek tasdiqlanmadi. Iltimos, to'g'ri chekni ilovada qayta yuboring yoki biz bilan bog'laning.",
        "client.order_created": "✅ Buyurtmangiz qabul qilindi!\nBuyurtma №{number}\nJami: {total}\nHolati: {status}",
    },
    "ru": {
        "status.new": "🆕 Новый",
        "status.awaiting_payment": "💳 Ожидает оплаты",
        "status.payment_review": "🔎 Проверка оплаты",
        "status.paid": "✅ Оплачен",
        "status.cooking": "👨‍🍳 Готовится",
        "status.ready": "📦 Готов",
        "status.delivering": "🚚 Доставляется",
        "status.done": "✅ Выполнен",
        "status.cancelled": "❌ Отменён",
        "pay.cash": "💵 Наличными",
        "pay.transfer": "🏦 Банковский перевод",
        "delivery.delivery": "🚚 Доставка",
        "delivery.pickup": "🏃 Самовывоз",
        "btn.open_shop": "🛍 Открыть магазин",
        "btn.admin": "👨‍💼 Админ-панель",
        "btn.share_phone": "📱 Отправить номер телефона",
        "btn.open_order": "🧾 Открыть заказ",
        "bot.phone_saved": "✅ Спасибо! Ваш номер сохранён: {phone}",
        "bot.phone_foreign": "Пожалуйста, отправьте свой собственный номер.",
        "bot.no_webapp": "⚠️ Магазин ещё не настроен (не указан WEBAPP_URL).",
        "bot.help": "🛍 Чтобы открыть магазин, отправьте команду /start.",
        "bot.lang_set": "✅ Язык изменён: Русский",
        "client.status_changed": "🔔 Заказ №{number}\nСтатус: {status}",
        "client.payment_confirmed": "✅ Оплата по заказу №{number} подтверждена. Спасибо!",
        "client.payment_rejected": "❌ Чек по заказу №{number} не принят. Пожалуйста, отправьте правильный чек в приложении или свяжитесь с нами.",
        "client.order_created": "✅ Ваш заказ принят!\nЗаказ №{number}\nИтого: {total}\nСтатус: {status}",
    },
}


def t(lang: str, key: str, **kwargs) -> str:
    table = TEXTS.get(lang) or TEXTS["ru"]
    text = table.get(key) or TEXTS["ru"].get(key) or key
    return text.format(**kwargs) if kwargs else text
