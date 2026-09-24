"""Admin API. Every endpoint requires a valid Telegram initData of a user listed in ADMIN_IDS."""
from __future__ import annotations

import re
from datetime import timedelta

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .. import inventory, notifications
from ..config import SECTIONS
from ..database import get_session
from ..models import (
    ORDER_STATUSES, ST_CANCELLED, Category, InventoryTransaction, Order, OrderItem, Product, User,
)
from ..order_service import OrderActionError, change_status, confirm_payment, load_order, reject_payment
from ..security import CurrentUser, admin_user
from ..serializers import category_admin, order_dict, product_admin
from ..settings_service import DEFAULTS, load_settings, save_settings, typed
from ..uploads import delete_upload, save_image
from ..utils import fmt_dt, from_halalas, local_day_start_utc, local_now, money, to_halalas

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(admin_user)])
LANG = "ru"


def err(status: int, code: str, **extra):
    raise HTTPException(status, detail={"code": code, **extra})


# ------------------------------------------------------------------ statistics
@router.get("/stats")
async def stats(session: AsyncSession = Depends(get_session)):
    not_cancelled = Order.status != ST_CANCELLED

    async def period(start):
        row = (await session.execute(select(func.count(Order.id), func.coalesce(func.sum(Order.total), 0))
                                     .where(Order.created_at >= start, not_cancelled))).one()
        return {"orders": row[0], "revenue": from_halalas(row[1]), "revenue_text": money(row[1])}

    today = local_day_start_utc(0)
    week = local_day_start_utc(6)
    now = local_now()
    month = local_day_start_utc(now.day - 1)

    items_row = (await session.execute(
        select(func.coalesce(func.sum(OrderItem.quantity), 0)).join(Order).where(not_cancelled))).scalar_one()
    items_month = (await session.execute(
        select(func.coalesce(func.sum(OrderItem.quantity), 0)).join(Order)
        .where(not_cancelled, Order.created_at >= month))).scalar_one()

    top = (await session.execute(
        select(OrderItem.product_id, func.max(OrderItem.name_ru), func.max(OrderItem.name_uz),
               func.sum(OrderItem.quantity).label("q"), func.sum(OrderItem.subtotal))
        .join(Order).where(not_cancelled)
        .group_by(OrderItem.product_id).order_by(func.sum(OrderItem.quantity).desc()).limit(10))).all()

    by_status = dict((await session.execute(select(Order.status, func.count(Order.id)).group_by(Order.status))).all())

    low = typed(await load_settings(session))["low_stock_threshold"]
    stock_rows = (await session.execute(
        select(Product).where(Product.is_deleted.is_(False)).order_by(Product.stock, Product.id))).scalars().all()

    days = []
    for d in range(6, -1, -1):
        start, end = local_day_start_utc(d), local_day_start_utc(d - 1)
        row = (await session.execute(select(func.count(Order.id), func.coalesce(func.sum(Order.total), 0))
                                     .where(Order.created_at >= start, Order.created_at < end, not_cancelled))).one()
        days.append({"date": (now - timedelta(days=d)).strftime("%d.%m"), "orders": row[0],
                     "revenue": from_halalas(row[1])})

    customers = (await session.execute(select(func.count(func.distinct(Order.user_id))))).scalar_one()
    users_total = (await session.execute(select(func.count(User.id)))).scalar_one()

    return {
        "today": await period(today), "week": await period(week), "month": await period(month),
        "items_sold": int(items_row), "items_sold_month": int(items_month),
        "top_products": [{"product_id": r[0], "name": r[1] or r[2], "quantity": int(r[3]),
                          "revenue": from_halalas(r[4]), "revenue_text": money(r[4])} for r in top],
        "by_status": {s: by_status.get(s, 0) for s in ORDER_STATUSES},
        "stock": [{"id": p.id, "name": p.name_ru or p.name_uz, "section": p.section, "stock": p.stock,
                   "is_active": p.is_active, "low": p.stock <= low} for p in stock_rows],
        "days": days, "customers_with_orders": customers, "users_total": users_total,
    }


# ------------------------------------------------------------------ orders
@router.get("/orders")
async def list_orders(status: str | None = None, q: str | None = None, page: int = 1,
                      session: AsyncSession = Depends(get_session)):
    stmt = select(Order).options(selectinload(Order.items), selectinload(Order.payments), selectinload(Order.user))
    if status == "active":
        stmt = stmt.where(Order.status.notin_(["done", ST_CANCELLED]))
    elif status in ORDER_STATUSES:
        stmt = stmt.where(Order.status == status)
    if q:
        q = q.strip().lstrip("№#")
        conds = [Order.customer_name.ilike(f"%{q}%"), Order.phone.ilike(f"%{q}%")]
        if q.isdigit():
            conds += [Order.number == int(q), Order.id == int(q)]
        stmt = stmt.where(or_(*conds))
    page = max(1, page)
    rows = (await session.execute(stmt.order_by(Order.id.desc()).offset((page - 1) * 30).limit(30))).scalars().all()
    return [order_dict(o, LANG, admin=True) for o in rows]


@router.get("/orders/{order_id}")
async def get_order(order_id: int, session: AsyncSession = Depends(get_session)):
    o = await load_order(session, order_id)
    if not o:
        err(404, "not_found")
    return order_dict(o, LANG, admin=True)


class StatusIn(BaseModel):
    status: str


@router.post("/orders/{order_id}/status")
async def set_status(order_id: int, body: StatusIn, cu: CurrentUser = Depends(admin_user),
                     session: AsyncSession = Depends(get_session)):
    o = await load_order(session, order_id)
    if not o:
        err(404, "not_found")
    try:
        changed = await change_status(session, o, body.status, cu.telegram_id)
    except OrderActionError as e:
        err(400, e.code)
    if changed:
        notifications.fire(notifications.notify_client_status(order_id))
    return order_dict(await load_order(session, order_id), LANG, admin=True)


class PaymentIn(BaseModel):
    action: str  # confirm | reject
    note: str = Field(default="", max_length=500)


@router.post("/orders/{order_id}/payment")
async def payment_action(order_id: int, body: PaymentIn, cu: CurrentUser = Depends(admin_user),
                         session: AsyncSession = Depends(get_session)):
    o = await load_order(session, order_id)
    if not o:
        err(404, "not_found")
    try:
        if body.action == "confirm":
            await confirm_payment(session, o, cu.telegram_id)
            notifications.fire(notifications.notify_client_status(order_id, "pay_ok"))
        elif body.action == "reject":
            await reject_payment(session, o, cu.telegram_id, body.note)
            notifications.fire(notifications.notify_client_status(order_id, "pay_no"))
        else:
            err(400, "bad_action")
    except OrderActionError as e:
        err(400, e.code)
    return order_dict(await load_order(session, order_id), LANG, admin=True)


class NoteIn(BaseModel):
    note: str = Field(default="", max_length=2000)


@router.post("/orders/{order_id}/note")
async def order_note(order_id: int, body: NoteIn, session: AsyncSession = Depends(get_session)):
    o = await load_order(session, order_id)
    if not o:
        err(404, "not_found")
    o.admin_note = body.note
    await session.commit()
    return order_dict(await load_order(session, order_id), LANG, admin=True)


# ------------------------------------------------------------------ categories
class CategoryIn(BaseModel):
    section: str
    name_uz: str = Field(default="", max_length=128)
    name_ru: str = Field(default="", max_length=128)
    icon: str = Field(default="🍽", max_length=16)
    sort_order: int = 0
    is_active: bool = True


@router.get("/categories")
async def list_categories(session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(Category).order_by(Category.section, Category.sort_order, Category.id))).scalars().all()
    return [category_admin(c) for c in rows]


def _check_category(body: CategoryIn):
    if body.section not in SECTIONS:
        err(400, "bad_section")
    if not (body.name_uz.strip() or body.name_ru.strip()):
        err(400, "name_required")


@router.post("/categories")
async def create_category(body: CategoryIn, session: AsyncSession = Depends(get_session)):
    _check_category(body)
    c = Category(**body.model_dump())
    session.add(c)
    await session.commit()
    return category_admin(c)


@router.put("/categories/{cat_id}")
async def update_category(cat_id: int, body: CategoryIn, session: AsyncSession = Depends(get_session)):
    _check_category(body)
    c = await session.get(Category, cat_id)
    if not c:
        err(404, "not_found")
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    if c.section:
        # products follow their category's section
        for p in (await session.execute(select(Product).where(Product.category_id == c.id))).scalars():
            p.section = c.section
    await session.commit()
    return category_admin(c)


@router.delete("/categories/{cat_id}")
async def delete_category(cat_id: int, session: AsyncSession = Depends(get_session)):
    c = await session.get(Category, cat_id)
    if not c:
        err(404, "not_found")
    used = (await session.execute(select(func.count(Product.id)).where(
        Product.category_id == cat_id, Product.is_deleted.is_(False)))).scalar_one()
    if used:
        err(400, "category_not_empty", count=used)
    await session.delete(c)
    await session.commit()
    return {"ok": True}


# ------------------------------------------------------------------ products
class ProductIn(BaseModel):
    section: str
    category_id: int | None = None
    name_uz: str = Field(default="", max_length=160)
    name_ru: str = Field(default="", max_length=160)
    description_uz: str = Field(default="", max_length=4000)
    description_ru: str = Field(default="", max_length=4000)
    price: str | float
    stock: int = Field(default=0, ge=0, le=1_000_000)
    min_qty: int = Field(default=1, ge=1, le=10000)
    max_qty: int | None = Field(default=None, ge=1, le=100000)
    is_active: bool = True
    sort_order: int = 0


async def _validate_product(body: ProductIn, session: AsyncSession) -> int:
    if body.section not in SECTIONS:
        err(400, "bad_section")
    if not (body.name_uz.strip() or body.name_ru.strip()):
        err(400, "name_required")
    try:
        price = to_halalas(body.price)
    except ValueError:
        err(400, "bad_price")
    if body.max_qty and body.max_qty < body.min_qty:
        err(400, "bad_qty_limits")
    if body.category_id:
        c = await session.get(Category, body.category_id)
        if not c:
            err(400, "bad_category")
        if c.section != body.section:
            err(400, "category_section_mismatch")
    return price


async def _get_product(session: AsyncSession, pid: int) -> Product:
    p = (await session.execute(select(Product).options(selectinload(Product.category))
                               .where(Product.id == pid, Product.is_deleted.is_(False))
                               .execution_options(populate_existing=True))).scalar_one_or_none()
    if not p:
        err(404, "not_found")
    return p


@router.get("/products")
async def list_products(section: str | None = None, q: str | None = None, session: AsyncSession = Depends(get_session)):
    stmt = select(Product).options(selectinload(Product.category)).where(Product.is_deleted.is_(False))
    if section in SECTIONS:
        stmt = stmt.where(Product.section == section)
    if q:
        stmt = stmt.where(or_(Product.name_uz.ilike(f"%{q}%"), Product.name_ru.ilike(f"%{q}%")))
    rows = (await session.execute(stmt.order_by(Product.section, Product.category_id, Product.sort_order, Product.id))).scalars().all()
    return [product_admin(p) for p in rows]


@router.get("/products/{pid}")
async def get_product(pid: int, session: AsyncSession = Depends(get_session)):
    return product_admin(await _get_product(session, pid))


@router.post("/products")
async def create_product(body: ProductIn, cu: CurrentUser = Depends(admin_user),
                         session: AsyncSession = Depends(get_session)):
    price = await _validate_product(body, session)
    data = body.model_dump()
    data["price"] = price
    p = Product(**data)
    session.add(p)
    await session.flush()
    if p.stock:
        session.add(InventoryTransaction(product_id=p.id, change=p.stock, stock_after=p.stock, reason="create",
                                         admin_telegram_id=cu.telegram_id))
    await session.commit()
    return product_admin(await _get_product(session, p.id))


@router.put("/products/{pid}")
async def update_product(pid: int, body: ProductIn, cu: CurrentUser = Depends(admin_user),
                         session: AsyncSession = Depends(get_session)):
    p = await _get_product(session, pid)
    price = await _validate_product(body, session)
    data = body.model_dump()
    new_stock = data.pop("stock")
    data["price"] = price
    for k, v in data.items():
        setattr(p, k, v)
    await session.flush()
    await inventory.set_stock(session, p, new_stock, cu.telegram_id)
    await session.commit()
    return product_admin(await _get_product(session, pid))


class StockIn(BaseModel):
    set: int | None = Field(default=None, ge=0, le=1_000_000)
    delta: int | None = Field(default=None, ge=-1_000_000, le=1_000_000)


@router.post("/products/{pid}/stock")
async def product_stock(pid: int, body: StockIn, cu: CurrentUser = Depends(admin_user),
                        session: AsyncSession = Depends(get_session)):
    p = await _get_product(session, pid)
    if body.set is not None:
        await inventory.set_stock(session, p, body.set, cu.telegram_id)
    elif body.delta:
        await inventory.adjust_stock(session, p, body.delta, cu.telegram_id)
    await session.commit()
    return product_admin(await _get_product(session, pid))


class PriceIn(BaseModel):
    price: str | float


@router.post("/products/{pid}/price")
async def product_price(pid: int, body: PriceIn, session: AsyncSession = Depends(get_session)):
    p = await _get_product(session, pid)
    try:
        p.price = to_halalas(body.price)
    except ValueError:
        err(400, "bad_price")
    await session.commit()
    return product_admin(await _get_product(session, pid))


@router.post("/products/{pid}/toggle")
async def product_toggle(pid: int, session: AsyncSession = Depends(get_session)):
    p = await _get_product(session, pid)
    p.is_active = not p.is_active
    await session.commit()
    return product_admin(await _get_product(session, pid))


@router.post("/products/{pid}/image")
async def product_image(pid: int, file: UploadFile = File(...), session: AsyncSession = Depends(get_session)):
    p = await _get_product(session, pid)
    rel = await save_image(file, "products", max_side=1400)
    old = p.image_path
    p.image_path = rel
    await session.commit()
    delete_upload(old)
    return product_admin(await _get_product(session, pid))


@router.delete("/products/{pid}/image")
async def product_image_delete(pid: int, session: AsyncSession = Depends(get_session)):
    p = await _get_product(session, pid)
    old = p.image_path
    p.image_path = None
    await session.commit()
    delete_upload(old)
    return product_admin(await _get_product(session, pid))


@router.delete("/products/{pid}")
async def delete_product(pid: int, session: AsyncSession = Depends(get_session)):
    """Soft delete: the product disappears everywhere, but old orders keep their history."""
    p = await _get_product(session, pid)
    p.is_deleted = True
    p.is_active = False
    await session.commit()
    return {"ok": True}


@router.get("/inventory")
async def inventory_log(product_id: int | None = None, session: AsyncSession = Depends(get_session)):
    stmt = select(InventoryTransaction, Product.name_ru, Product.name_uz).join(Product)
    if product_id:
        stmt = stmt.where(InventoryTransaction.product_id == product_id)
    rows = (await session.execute(stmt.order_by(InventoryTransaction.id.desc()).limit(200))).all()
    return [{"id": tr.id, "product_id": tr.product_id, "name": nru or nuz, "change": tr.change,
             "stock_after": tr.stock_after, "reason": tr.reason, "order_id": tr.order_id,
             "created_local": fmt_dt(tr.created_at)} for tr, nru, nuz in rows]


# ------------------------------------------------------------------ customers
@router.get("/customers")
async def customers(q: str | None = None, session: AsyncSession = Depends(get_session)):
    not_cancelled = Order.status != ST_CANCELLED
    agg = (select(Order.user_id, func.count(Order.id).label("cnt"),
                  func.coalesce(func.sum(Order.total), 0).label("spent"), func.max(Order.created_at).label("last"))
           .where(not_cancelled).group_by(Order.user_id).subquery())
    stmt = select(User, agg.c.cnt, agg.c.spent, agg.c.last).outerjoin(agg, agg.c.user_id == User.id)
    if q:
        stmt = stmt.where(or_(User.username.ilike(f"%{q}%"), User.first_name.ilike(f"%{q}%"),
                              User.full_name.ilike(f"%{q}%"), User.phone.ilike(f"%{q}%")))
    rows = (await session.execute(stmt.order_by(func.coalesce(agg.c.spent, 0).desc(), User.id.desc()).limit(300))).all()
    return [{"id": u.id, "telegram_id": u.telegram_id, "username": u.username, "name": u.display_name,
             "phone": u.phone or "", "phone_verified": u.phone_verified, "language": u.language,
             "orders": cnt or 0, "spent": from_halalas(spent or 0), "spent_text": money(spent or 0),
             "last_order": fmt_dt(last) if last else "", "registered": fmt_dt(u.created_at)}
            for u, cnt, spent, last in rows]


@router.get("/customers/{user_id}/orders")
async def customer_orders(user_id: int, session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(Order).where(Order.user_id == user_id)
                                  .options(selectinload(Order.items), selectinload(Order.payments), selectinload(Order.user))
                                  .order_by(Order.id.desc()).limit(100))).scalars().all()
    return [order_dict(o, LANG, admin=True) for o in rows]


# ------------------------------------------------------------------ settings
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


@router.get("/settings")
async def get_settings(session: AsyncSession = Depends(get_session)):
    data = typed(await load_settings(session))
    data["logo_url"] = f"/uploads/{data['logo_path']}" if data.get("logo_path") else None
    return data


@router.put("/settings")
async def put_settings(body: dict, session: AsyncSession = Depends(get_session)):
    values: dict[str, str] = {}
    for key, value in body.items():
        if key not in DEFAULTS or key == "logo_path":
            continue
        if isinstance(value, bool):
            value = "1" if value else "0"
        value = str(value if value is not None else "").strip()[:4000]
        if key in ("open_time", "close_time") and not TIME_RE.match(value):
            err(400, "bad_time")
        if key == "primary_language" and value not in ("uz", "ru"):
            err(400, "bad_language")
        if key == "low_stock_threshold" and not value.isdigit():
            err(400, "bad_number")
        values[key] = value
    await save_settings(session, values)
    return await get_settings(session)


@router.post("/settings/logo")
async def upload_logo(file: UploadFile = File(...), session: AsyncSession = Depends(get_session)):
    rel = await save_image(file, "logo", max_side=600, keep_png=True)
    old = (await load_settings(session)).get("logo_path")
    await save_settings(session, {"logo_path": rel})
    delete_upload(old)
    return await get_settings(session)


@router.delete("/settings/logo")
async def delete_logo(session: AsyncSession = Depends(get_session)):
    old = (await load_settings(session)).get("logo_path")
    await save_settings(session, {"logo_path": ""})
    delete_upload(old)
    return await get_settings(session)
