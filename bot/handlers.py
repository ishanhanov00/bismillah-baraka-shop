"""Telegram bot handlers (aiogram 3)."""
from __future__ import annotations

import html
import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, Message,
    ReplyKeyboardMarkup, ReplyKeyboardRemove, WebAppInfo,
)

from backend import notifications
from backend.config import is_admin, settings
from backend.database import SessionLocal
from backend.i18n import t
from backend.models import ST_CANCELLED
from backend.order_service import OrderActionError, change_status, confirm_payment, load_order, reject_payment
from backend.security import upsert_user
from backend.settings_service import load_settings

log = logging.getLogger("bot.handlers")
router = Router()


def webapp_ok() -> bool:
    return settings.WEBAPP_URL.startswith("https://")


def tg_dict(u) -> dict:
    return {"id": u.id, "username": u.username, "first_name": u.first_name, "last_name": u.last_name,
            "language_code": u.language_code}


def main_keyboard(lang: str, admin: bool) -> InlineKeyboardMarkup | None:
    if not webapp_ok():
        return None
    rows = [[InlineKeyboardButton(text=t(lang, "btn.open_shop"), web_app=WebAppInfo(url=settings.WEBAPP_URL + "/"))]]
    if admin:
        rows.append([InlineKeyboardButton(text=t(lang, "btn.admin"),
                                          web_app=WebAppInfo(url=settings.WEBAPP_URL + "/admin"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def phone_keyboard(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=t(lang, "btn.share_phone"), request_contact=True)]],
                               resize_keyboard=True, one_time_keyboard=True)


@router.message(CommandStart(), F.chat.type == "private")
async def cmd_start(message: Message, command: CommandObject):
    async with SessionLocal() as s:
        user = await upsert_user(s, tg_dict(message.from_user))
        conf = await load_settings(s)
        lang, has_phone = user.language, bool(user.phone_verified)
    admin = is_admin(message.from_user.id)

    payload = (command.args or "").strip()
    if payload.startswith("order_") and admin and payload[6:].isdigit():
        await send_admin_order(message, int(payload[6:]))
        return

    name = html.escape(conf.get("business_name") or settings.BUSINESS_NAME)
    welcome = conf.get(f"welcome_{lang}") or conf.get("welcome_uz") or ""
    welcome = html.escape(welcome).replace("{name}", f"<b>{name}</b>")
    desc = html.escape(conf.get(f"description_{lang}") or "")
    text = f"🌙 <b>{name}</b>\n\n{welcome}"
    if desc:
        text += f"\n\n<i>{desc}</i>"
    kb = main_keyboard(lang, admin)
    if kb is None:
        text += "\n\n" + t(lang, "bot.no_webapp")
    await message.answer(text, reply_markup=kb)
    if not has_phone:
        hint = ("📱 Buyurtmani tezroq rasmiylashtirish uchun telefon raqamingizni yuboring."
                if lang == "uz" else "📱 Чтобы быстрее оформлять заказы, отправьте свой номер телефона.")
        await message.answer(hint, reply_markup=phone_keyboard(lang))


async def send_admin_order(message: Message, order_id: int):
    async with SessionLocal() as s:
        o = await load_order(s, order_id)
        if not o:
            await message.answer("❌ Not found")
            return
        text, kb = notifications.order_text(o, "order"), notifications.order_keyboard(o)
    if webapp_ok():
        kb.inline_keyboard.append([InlineKeyboardButton(
            text=t(settings.ADMIN_LANGUAGE, "btn.admin"),
            web_app=WebAppInfo(url=f"{settings.WEBAPP_URL}/admin#order/{order_id}"))])
    await message.answer(text, reply_markup=kb)


@router.message(F.contact, F.chat.type == "private")
async def on_contact(message: Message):
    contact = message.contact
    async with SessionLocal() as s:
        user = await upsert_user(s, tg_dict(message.from_user))
        lang = user.language
        if contact.user_id != message.from_user.id:
            await message.answer(t(lang, "bot.phone_foreign"))
            return
        phone = contact.phone_number if contact.phone_number.startswith("+") else "+" + contact.phone_number
        user.phone = phone
        user.phone_verified = True
        await s.commit()
    await message.answer(t(lang, "bot.phone_saved", phone=html.escape(phone)), reply_markup=ReplyKeyboardRemove())
    kb = main_keyboard(lang, is_admin(message.from_user.id))
    if kb:
        await message.answer("👇", reply_markup=kb)


@router.message(Command("admin"), F.chat.type == "private")
async def cmd_admin(message: Message):
    if not is_admin(message.from_user.id):
        return  # regular clients do not even know this command exists
    if not webapp_ok():
        await message.answer(t(settings.ADMIN_LANGUAGE, "bot.no_webapp"))
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=t(settings.ADMIN_LANGUAGE, "btn.admin"), web_app=WebAppInfo(url=settings.WEBAPP_URL + "/admin"))]])
    await message.answer("👨‍💼", reply_markup=kb)


@router.message(Command("chatid"))
async def cmd_chatid(message: Message):
    """Helper for setup: shows the id of the current chat (use it for NOTIFY_CHAT_ID)."""
    if not is_admin(message.from_user.id if message.from_user else None):
        return
    await message.answer(f"Chat ID: <code>{message.chat.id}</code>\nNOTIFY_CHAT_ID={message.chat.id}")


@router.message(Command("lang"), F.chat.type == "private")
async def cmd_lang(message: Message):
    async with SessionLocal() as s:
        user = await upsert_user(s, tg_dict(message.from_user))
        user.language = "ru" if user.language == "uz" else "uz"
        await s.commit()
        lang = user.language
    await message.answer(t(lang, "bot.lang_set"), reply_markup=main_keyboard(lang, is_admin(message.from_user.id)))


@router.message(F.chat.type == "private")
async def any_message(message: Message):
    async with SessionLocal() as s:
        user = await upsert_user(s, tg_dict(message.from_user))
        lang = user.language
    await message.answer(t(lang, "bot.help"), reply_markup=main_keyboard(lang, is_admin(message.from_user.id)))


# ----------------------------------------------------------------- admin buttons under order messages
@router.callback_query(F.data.startswith("o:"))
async def order_callback(call: CallbackQuery):
    lang = settings.ADMIN_LANGUAGE
    if not is_admin(call.from_user.id):
        await call.answer("⛔ Только для администраторов" if lang == "ru" else "⛔ Faqat adminlar uchun", show_alert=True)
        return
    try:
        _, oid, action = call.data.split(":", 2)
        order_id = int(oid)
    except ValueError:
        await call.answer()
        return

    if action == "ask_cancel":
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Да, отменить" if lang == "ru" else "✅ Ha, bekor qilish",
                                 callback_data=f"o:{order_id}:st_{ST_CANCELLED}"),
            InlineKeyboardButton(text="↩️ Назад" if lang == "ru" else "↩️ Orqaga", callback_data=f"o:{order_id}:back"),
        ]])
        try:
            await call.message.edit_reply_markup(reply_markup=kb)
        except Exception:
            pass
        await call.answer()
        return

    kind = "status"
    async with SessionLocal() as s:
        o = await load_order(s, order_id)
        if not o:
            await call.answer("Not found", show_alert=True)
            return
        try:
            if action == "pay_ok":
                await confirm_payment(s, o, call.from_user.id)
                kind = "pay_ok"
            elif action == "pay_no":
                await reject_payment(s, o, call.from_user.id)
                kind = "pay_no"
            elif action.startswith("st_"):
                if not await change_status(s, o, action[3:], call.from_user.id):
                    kind = None
            elif action == "back":
                kind = None
        except OrderActionError as e:
            await call.answer(f"⚠️ {e.code}", show_alert=True)
            return
        o = await load_order(s, order_id)
        header = "order"
        text = notifications.order_text(o, header)
        kb = notifications.order_keyboard(o)

    try:
        if call.message.photo:
            await call.message.edit_caption(caption=text[:1024], reply_markup=kb)
        else:
            await call.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
    except Exception as exc:
        log.debug("edit failed: %s", exc)
    if kind:
        notifications.fire(notifications.notify_client_status(order_id, kind))
    await call.answer("✅")
