"""Telegram notifications: new orders to the group/admins, receipts, status updates to clients."""
from __future__ import annotations

import asyncio
import html
import logging

from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from bot import loader
from .config import settings
from .database import SessionLocal
from .i18n import t
from .models import (
    PAY_TRANSFER, PS_SUBMITTED, ST_CANCELLED, ST_COOKING, ST_DELIVERING, ST_DONE, ST_READY, Order,
)
from .order_service import load_order
from .utils import fmt_dt, money

log = logging.getLogger("notify")

SECTION_ICON = {"menu": "🍽", "sadaqa": "🤲", "events": "🏞"}

L = {
    "ru": {"new": "🔔 <b>НОВЫЙ ЗАКАЗ №{n}</b>", "order": "🧾 <b>Заказ №{n}</b>", "client": "👤 Клиент",
           "tg": "💬 Telegram", "phone": "📞 Телефон", "addr": "📍 Адрес", "type": "🚗 Получение",
           "items": "🛒 Товары", "total": "💰 Итого", "pay": "Оплата", "comment": "📝 Комментарий",
           "status": "📌 Статус", "date": "🕒 Дата", "receipt": "📎 <b>Чек по заказу №{n}</b>",
           "receipt_hint": "Проверьте поступление денег и нажмите кнопку.", "no_username": "нет username",
           "pay_ok": "✅ Подтвердить оплату", "pay_no": "❌ Отклонить оплату", "cancel": "❌ Отменить",
           "receipt_attached": "📎 Чек прикреплён", "receipt_wait": "⏳ Ожидается чек"},
    "uz": {"new": "🔔 <b>YANGI BUYURTMA №{n}</b>", "order": "🧾 <b>Buyurtma №{n}</b>", "client": "👤 Mijoz",
           "tg": "💬 Telegram", "phone": "📞 Telefon", "addr": "📍 Manzil", "type": "🚗 Olish usuli",
           "items": "🛒 Mahsulotlar", "total": "💰 Jami", "pay": "To'lov", "comment": "📝 Izoh",
           "status": "📌 Holati", "date": "🕒 Sana", "receipt": "📎 <b>Buyurtma №{n} cheki</b>",
           "receipt_hint": "Pul tushganini tekshirib, tugmani bosing.", "no_username": "username yo'q",
           "pay_ok": "✅ To'lovni tasdiqlash", "pay_no": "❌ To'lovni rad etish", "cancel": "❌ Bekor qilish",
           "receipt_attached": "📎 Chek biriktirilgan", "receipt_wait": "⏳ Chek kutilmoqda"},
}


def _l(key: str, **kw) -> str:
    lang = settings.ADMIN_LANGUAGE if settings.ADMIN_LANGUAGE in L else "ru"
    text = L[lang][key]
    return text.format(**kw) if kw else text


def order_text(o: Order, header: str = "new") -> str:
    lang = settings.ADMIN_LANGUAGE
    e = html.escape
    u = o.user
    tg_name = f"@{e(u.username)}" if u and u.username else _l("no_username")
    tg_line = f"{tg_name} (ID <code>{u.telegram_id}</code>)" if u else tg_name
    lines = [_l(header, n=o.number), "",
             f"{_l('client')}: {e(o.customer_name)}",
             f"{_l('tg')}: {tg_line}",
             f"{_l('phone')}: {e(o.phone)}",
             f"{_l('date')}: {fmt_dt(o.created_at)}",
             f"{_l('type')}: {t(lang, 'delivery.' + o.delivery_type)}"]
    if o.address:
        lines.append(f"{_l('addr')}: {e(o.address)}")
    lines += ["", f"{_l('items')}:"]
    for i in o.items:
        name = (i.name_ru if lang == "ru" else i.name_uz) or i.name_uz or i.name_ru
        lines.append(f"{SECTION_ICON.get(i.section, '•')} {e(name)} × {i.quantity} — {money(i.subtotal)}")
    lines += ["", f"{_l('total')}: <b>{money(o.total)}</b>",
              f"{t(lang, 'pay.' + o.payment_method)}"]
    if o.payment_method == PAY_TRANSFER:
        pay = o.payment
        lines.append(_l("receipt_attached") if pay and pay.receipt_path else _l("receipt_wait"))
    if o.comment:
        lines.append(f"{_l('comment')}: {e(o.comment)}")
    lines.append(f"{_l('status')}: <b>{t(lang, 'status.' + o.status)}</b>")
    return "\n".join(lines)


def order_keyboard(o: Order) -> InlineKeyboardMarkup:
    lang = settings.ADMIN_LANGUAGE
    rows: list[list[InlineKeyboardButton]] = []
    pay = o.payment
    if o.status != ST_CANCELLED:
        if o.payment_method == PAY_TRANSFER and pay and pay.status == PS_SUBMITTED:
            rows.append([InlineKeyboardButton(text=_l("pay_ok"), callback_data=f"o:{o.id}:pay_ok"),
                         InlineKeyboardButton(text=_l("pay_no"), callback_data=f"o:{o.id}:pay_no")])
        st = [ST_COOKING, ST_READY, ST_DELIVERING, ST_DONE]
        btns = [InlineKeyboardButton(text=("• " if o.status == s else "") + t(lang, f"status.{s}"),
                                     callback_data=f"o:{o.id}:st_{s}") for s in st]
        rows += [btns[0:2], btns[2:4]]
        rows.append([InlineKeyboardButton(text=_l("cancel"), callback_data=f"o:{o.id}:ask_cancel")])
    if loader.BOT_INFO.get("username"):
        rows.append([InlineKeyboardButton(text=t(lang, "btn.open_order"),
                                          url=f"https://t.me/{loader.BOT_INFO['username']}?start=order_{o.id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _targets() -> list[str | int]:
    targets: list[str | int] = []
    if settings.NOTIFY_CHAT_ID:
        cid = settings.NOTIFY_CHAT_ID
        targets.append(int(cid) if cid.lstrip("-").isdigit() else cid)
    if settings.NOTIFY_ADMINS_PRIVATE or not targets:
        targets += sorted(settings.ADMIN_IDS)
    return targets


async def _send_all(text: str, kb: InlineKeyboardMarkup, photo: str | None = None) -> None:
    if loader.bot is None:
        return
    for chat in _targets():
        try:
            if photo:
                await loader.bot.send_photo(chat, FSInputFile(photo), caption=text[:1024], reply_markup=kb)
            else:
                await loader.bot.send_message(chat, text, reply_markup=kb, disable_web_page_preview=True)
        except Exception as exc:
            log.warning("notify %s failed: %s", chat, exc)


async def notify_new_order(order_id: int) -> None:
    async with SessionLocal() as s:
        o = await load_order(s, order_id)
        if not o:
            return
        text, kb = order_text(o, "new"), order_keyboard(o)
        client_id, lang = o.user.telegram_id, o.language
        client_text = t(lang, "client.order_created", number=o.number, total=money(o.total),
                        status=t(lang, f"status.{o.status}"))
    await _send_all(text, kb)
    await send_to_client(client_id, client_text)


async def notify_receipt(order_id: int) -> None:
    async with SessionLocal() as s:
        o = await load_order(s, order_id)
        if not o or not o.payment or not o.payment.receipt_path:
            return
        text = _l("receipt", n=o.number) + "\n" + _l("receipt_hint") + "\n\n" + order_text(o, "order")
        kb = order_keyboard(o)
        photo = str(settings.UPLOAD_DIR / o.payment.receipt_path)
    await _send_all(text, kb, photo=photo)


async def send_to_client(telegram_id: int, text: str) -> None:
    if loader.bot is None:
        return
    try:
        await loader.bot.send_message(telegram_id, text)
    except Exception as exc:  # user never started the bot, blocked it, etc.
        log.info("client %s not notified: %s", telegram_id, exc)


async def notify_client_status(order_id: int, kind: str = "status") -> None:
    async with SessionLocal() as s:
        o = await load_order(s, order_id)
        if not o:
            return
        lang = o.language
        if kind == "pay_ok":
            text = t(lang, "client.payment_confirmed", number=o.number)
        elif kind == "pay_no":
            text = t(lang, "client.payment_rejected", number=o.number)
        else:
            text = t(lang, "client.status_changed", number=o.number, status=t(lang, f"status.{o.status}"))
        tid = o.user.telegram_id
    await send_to_client(tid, text)


def fire(coro) -> None:
    """Run a notification in the background without blocking the API response."""
    try:
        asyncio.get_running_loop().create_task(coro)
    except RuntimeError:
        pass
