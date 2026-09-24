"""Client orders: create order (server-side prices & stock), history, receipt upload."""
from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .. import inventory, notifications
from ..config import settings
from ..database import get_session, utcnow
from ..models import (
    PAY_CASH, PAY_TRANSFER, PS_CASH, PS_PENDING, PS_REJECTED, PS_SUBMITTED, ST_AWAITING_PAYMENT, ST_NEW,
    ST_PAYMENT_REVIEW, Order, OrderItem, Payment, Product,
)
from ..order_service import load_order
from ..security import CurrentUser, check_file_sig, current_user
from ..serializers import order_dict
from ..settings_service import can_order_now, load_settings, typed
from ..uploads import delete_upload, save_image
from ..utils import norm_lang
from .public import valid_phone

log = logging.getLogger("orders")
router = APIRouter(prefix="/api", tags=["orders"])


class OrderItemIn(BaseModel):
    product_id: int
    quantity: int = Field(ge=1, le=1000)


class OrderIn(BaseModel):
    items: list[OrderItemIn] = Field(min_length=1, max_length=50)
    customer_name: str = Field(min_length=1, max_length=80)
    phone: str = Field(min_length=5, max_length=24)
    delivery_type: Literal["delivery", "pickup"] = "delivery"
    address: str = Field(default="", max_length=500)
    comment: str = Field(default="", max_length=1000)
    payment_method: Literal["cash", "transfer"]
    language: str | None = None


def err(status: int, code: str, **extra):
    raise HTTPException(status, detail={"code": code, **extra})


@router.post("/orders")
async def create_order(body: OrderIn, cu: CurrentUser = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    lang = norm_lang(body.language or cu.user.language)
    conf = await load_settings(session)
    tconf = typed(conf)
    if not can_order_now(conf):
        err(400, "store_closed")
    name = body.customer_name.strip()
    phone = body.phone.strip()
    address = body.address.strip()
    if not name:
        err(400, "name_required")
    if not valid_phone(phone):
        err(400, "bad_phone")
    if body.delivery_type == "delivery" and not tconf["delivery_enabled"]:
        err(400, "delivery_disabled")
    if body.delivery_type == "pickup" and not tconf["pickup_enabled"]:
        err(400, "pickup_disabled")
    if body.delivery_type == "delivery" and len(address) < 3:
        err(400, "address_required")

    # merge duplicate lines
    wanted: dict[int, int] = {}
    for it in body.items:
        wanted[it.product_id] = wanted.get(it.product_id, 0) + it.quantity

    products = {p.id: p for p in (await session.execute(
        select(Product).where(Product.id.in_(list(wanted))))).scalars().all()}
    for pid, qty in wanted.items():
        p = products.get(pid)
        if not p or p.is_deleted or not p.is_active:
            err(409, "product_unavailable", product_id=pid)
        if qty < max(1, p.min_qty or 1):
            err(409, "min_qty", product_id=pid, name_uz=p.name_uz, name_ru=p.name_ru, min_qty=p.min_qty)
        if p.max_qty and qty > p.max_qty:
            err(409, "max_qty", product_id=pid, name_uz=p.name_uz, name_ru=p.name_ru, max_qty=p.max_qty)
    # plain snapshot (DB objects expire after rollback)
    snap = {pid: SimpleNamespace(id=p.id, price=p.price, section=p.section, name_uz=p.name_uz, name_ru=p.name_ru)
            for pid, p in products.items()}
    # finish the read transaction so the write transaction starts with a fresh lock
    await session.commit()

    for attempt in range(3):
        try:
            order = Order(
                user_id=cu.user.id, customer_name=name, phone=phone, delivery_type=body.delivery_type,
                address=address if body.delivery_type == "delivery" else "", comment=body.comment.strip(),
                payment_method=body.payment_method, language=lang,
                status=ST_NEW if body.payment_method == PAY_CASH else ST_AWAITING_PAYMENT,
                created_at=utcnow(),
            )
            session.add(order)
            await session.flush()
            order.number = order.id + settings.ORDER_NUMBER_OFFSET
            total, count = 0, 0
            for pid in sorted(wanted):  # fixed order avoids deadlocks on PostgreSQL
                p, qty = snap[pid], wanted[pid]
                await inventory.reserve(session, p, qty, order_id=order.id)
                price = p.price  # ALWAYS the price from the database
                session.add(OrderItem(order_id=order.id, product_id=p.id, section=p.section, name_uz=p.name_uz,
                                      name_ru=p.name_ru, price=price, quantity=qty, subtotal=price * qty))
                total += price * qty
                count += qty
            order.total, order.items_count = total, count
            session.add(Payment(order_id=order.id, method=body.payment_method, amount=total,
                                status=PS_CASH if body.payment_method == PAY_CASH else PS_PENDING))
            # remember contact data in the profile for next time
            cu.user.full_name = name
            if phone != (cu.user.phone or ""):
                cu.user.phone = phone
                cu.user.phone_verified = False
            cu.user.language = lang
            await session.commit()
            break
        except inventory.StockError as e:
            await session.rollback()
            err(409, "insufficient_stock", product_id=e.product_id, available=e.available,
                name_uz=e.name_uz, name_ru=e.name_ru)
        except OperationalError as e:  # SQLite "database is locked" under heavy load -> retry
            await session.rollback()
            log.warning("order retry %s: %s", attempt, e)
            if attempt == 2:
                err(503, "busy")
            await session.refresh(cu.user)

    order_id = order.id
    notifications.fire(notifications.notify_new_order(order_id))
    o = await load_order(session, order_id)
    return order_dict(o, lang)


@router.get("/orders")
async def my_orders(lang: str | None = None, cu: CurrentUser = Depends(current_user),
                    session: AsyncSession = Depends(get_session)):
    """Only the orders of the current Telegram user."""
    lang = norm_lang(lang or cu.user.language)
    rows = (await session.execute(
        select(Order).where(Order.user_id == cu.user.id)
        .options(selectinload(Order.items), selectinload(Order.payments))
        .order_by(Order.id.desc()).limit(100))).scalars().all()
    return [order_dict(o, lang) for o in rows]


async def _own_order(session: AsyncSession, order_id: int, cu: CurrentUser) -> Order:
    o = await load_order(session, order_id)
    if not o or (o.user_id != cu.user.id and not cu.is_admin):
        err(404, "not_found")
    return o


@router.get("/orders/{order_id}")
async def get_order(order_id: int, lang: str | None = None, cu: CurrentUser = Depends(current_user),
                    session: AsyncSession = Depends(get_session)):
    o = await _own_order(session, order_id, cu)
    return order_dict(o, norm_lang(lang or cu.user.language))


@router.post("/orders/{order_id}/receipt")
async def upload_receipt(order_id: int, file: UploadFile = File(...), lang: str | None = None,
                         cu: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)):
    o = await _own_order(session, order_id, cu)
    if o.user_id != cu.user.id:
        err(403, "forbidden")
    if o.payment_method != PAY_TRANSFER:
        err(400, "not_transfer")
    if o.status not in (ST_AWAITING_PAYMENT, ST_PAYMENT_REVIEW):
        err(400, "receipt_not_allowed")
    rel = await save_image(file, "receipts", max_side=2000)
    pay = o.payment
    if pay is None:
        pay = Payment(order_id=o.id, method=PAY_TRANSFER, amount=o.total, status=PS_PENDING)
        session.add(pay)
    elif pay.status == PS_REJECTED:
        # keep the rejected payment for history, create a new attempt
        pay = Payment(order_id=o.id, method=PAY_TRANSFER, amount=o.total, status=PS_PENDING)
        session.add(pay)
    else:
        delete_upload(pay.receipt_path)
    pay.receipt_path = rel
    pay.status = PS_SUBMITTED
    pay.submitted_at = utcnow()
    o.status = ST_PAYMENT_REVIEW
    await session.commit()
    notifications.fire(notifications.notify_receipt(o.id))
    o = await load_order(session, o.id)
    return order_dict(o, norm_lang(lang or cu.user.language))


@router.get("/files/receipt/{payment_id}")
async def receipt_file(payment_id: int, exp: int = 0, sig: str = "", session: AsyncSession = Depends(get_session)):
    """Receipts are private: available only through a signed link that expires in 1 hour."""
    if not check_file_sig("receipt", payment_id, exp, sig):
        err(403, "forbidden")
    pay = await session.get(Payment, payment_id)
    if not pay or not pay.receipt_path:
        err(404, "not_found")
    path = settings.UPLOAD_DIR / pay.receipt_path
    if not path.exists():
        err(404, "not_found")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=3600"})
