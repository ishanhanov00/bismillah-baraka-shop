"""Inventory (stock) operations.

Stock is decreased with ONE atomic SQL statement:
    UPDATE products SET stock = stock - :q WHERE id = :id AND stock >= :q
If two clients try to buy the last item at the same moment, the database executes these
statements one after another; the second one updates 0 rows and the order is refused.
Stock can never become negative (there is also a CHECK constraint in the table).
"""
from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import InventoryTransaction, Order, Product


class StockError(Exception):
    def __init__(self, product_id: int, available: int, name_uz: str = "", name_ru: str = ""):
        super().__init__("insufficient stock")
        self.product_id = product_id
        self.available = available
        self.name_uz = name_uz
        self.name_ru = name_ru


async def reserve(session: AsyncSession, product: Product, qty: int, order_id: int | None = None) -> int:
    """Atomically take `qty` items. Must be called inside the order transaction."""
    result = await session.execute(
        update(Product)
        .where(Product.id == product.id, Product.stock >= qty,
               Product.is_active.is_(True), Product.is_deleted.is_(False))
        .values(stock=Product.stock - qty)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        available = (await session.execute(select(Product.stock).where(Product.id == product.id))).scalar_one_or_none() or 0
        raise StockError(product.id, int(available), product.name_uz, product.name_ru)
    new_stock = (await session.execute(select(Product.stock).where(Product.id == product.id))).scalar_one()
    session.add(InventoryTransaction(product_id=product.id, change=-qty, stock_after=new_stock,
                                     reason="order", order_id=order_id))
    return new_stock


async def release_order(session: AsyncSession, order: Order, admin_id: int | None = None) -> None:
    """Return the items of a cancelled order back to stock (only once)."""
    if order.stock_returned:
        return
    for item in order.items:
        if not item.product_id:
            continue
        await session.execute(
            update(Product).where(Product.id == item.product_id)
            .values(stock=Product.stock + item.quantity)
            .execution_options(synchronize_session=False)
        )
        new_stock = (await session.execute(select(Product.stock).where(Product.id == item.product_id))).scalar_one_or_none()
        if new_stock is not None:
            session.add(InventoryTransaction(product_id=item.product_id, change=item.quantity, stock_after=new_stock,
                                             reason="cancel", order_id=order.id, admin_telegram_id=admin_id))
    order.stock_returned = True


async def set_stock(session: AsyncSession, product: Product, new_stock: int, admin_id: int | None,
                    reason: str = "admin_set") -> None:
    new_stock = max(0, int(new_stock))
    old = (await session.execute(select(Product.stock).where(Product.id == product.id))).scalar_one()
    await session.execute(update(Product).where(Product.id == product.id).values(stock=new_stock)
                          .execution_options(synchronize_session=False))
    if new_stock != old:
        session.add(InventoryTransaction(product_id=product.id, change=new_stock - old, stock_after=new_stock,
                                         reason=reason, admin_telegram_id=admin_id))


async def adjust_stock(session: AsyncSession, product: Product, delta: int, admin_id: int | None) -> int:
    """Admin +/- adjustment, atomic and never below zero."""
    delta = int(delta)
    if delta < 0:
        res = await session.execute(update(Product).where(Product.id == product.id, Product.stock >= -delta)
                                    .values(stock=Product.stock + delta).execution_options(synchronize_session=False))
        if res.rowcount != 1:
            await session.execute(update(Product).where(Product.id == product.id).values(stock=0)
                                  .execution_options(synchronize_session=False))
    else:
        await session.execute(update(Product).where(Product.id == product.id).values(stock=Product.stock + delta)
                              .execution_options(synchronize_session=False))
    new_stock = (await session.execute(select(Product.stock).where(Product.id == product.id))).scalar_one()
    session.add(InventoryTransaction(product_id=product.id, change=delta, stock_after=new_stock,
                                     reason="admin_adjust", admin_telegram_id=admin_id))
    return new_stock
