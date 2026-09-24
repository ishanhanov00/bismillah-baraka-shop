"""Order status / payment logic shared by the web admin panel and the Telegram bot buttons."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from . import inventory
from .database import utcnow
from .models import (
    ORDER_STATUSES, PAY_TRANSFER, PS_CONFIRMED, PS_REJECTED, PS_SUBMITTED, PS_PENDING,
    ST_AWAITING_PAYMENT, ST_CANCELLED, ST_PAID, ST_PAYMENT_REVIEW, Order,
)


class OrderActionError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


async def load_order(session: AsyncSession, order_id: int) -> Order | None:
    return (await session.execute(
        select(Order).where(Order.id == order_id)
        .options(selectinload(Order.items), selectinload(Order.payments), selectinload(Order.user))
        .execution_options(populate_existing=True)
    )).scalar_one_or_none()


async def change_status(session: AsyncSession, order: Order, new_status: str, admin_id: int | None) -> bool:
    """Returns True if the status was changed. Cancelling returns reserved items to stock."""
    if new_status not in ORDER_STATUSES:
        raise OrderActionError("bad_status")
    if order.status == new_status:
        return False
    if order.status == ST_CANCELLED:
        raise OrderActionError("order_cancelled")  # cancelled orders are final (stock already returned)
    if new_status == ST_CANCELLED:
        await inventory.release_order(session, order, admin_id)
    order.status = new_status
    order.updated_at = utcnow()
    await session.commit()
    return True


async def confirm_payment(session: AsyncSession, order: Order, admin_id: int | None) -> None:
    if order.status == ST_CANCELLED:
        raise OrderActionError("order_cancelled")
    pay = order.payment
    if order.payment_method != PAY_TRANSFER or pay is None:
        raise OrderActionError("not_transfer")
    if pay.status == PS_CONFIRMED:
        raise OrderActionError("already_confirmed")
    pay.status = PS_CONFIRMED
    pay.reviewed_by = admin_id
    pay.reviewed_at = utcnow()
    if order.status in (ST_AWAITING_PAYMENT, ST_PAYMENT_REVIEW):
        order.status = ST_PAID
    order.updated_at = utcnow()
    await session.commit()


async def reject_payment(session: AsyncSession, order: Order, admin_id: int | None, note: str = "") -> None:
    if order.status == ST_CANCELLED:
        raise OrderActionError("order_cancelled")
    pay = order.payment
    if order.payment_method != PAY_TRANSFER or pay is None:
        raise OrderActionError("not_transfer")
    if pay.status not in (PS_SUBMITTED, PS_PENDING, PS_CONFIRMED):
        raise OrderActionError("nothing_to_reject")
    pay.status = PS_REJECTED
    pay.reviewed_by = admin_id
    pay.reviewed_at = utcnow()
    pay.note = note or ""
    order.status = ST_AWAITING_PAYMENT  # client can upload a new receipt
    order.updated_at = utcnow()
    await session.commit()
