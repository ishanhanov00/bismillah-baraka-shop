"""Convert DB objects to JSON for the API."""
from __future__ import annotations

from .i18n import t
from .models import Category, Order, Product
from .security import sign_file
from .utils import fmt_dt, from_halalas, localized, money


def image_url(path: str | None) -> str | None:
    return f"/uploads/{path}" if path else None


def category_public(c: Category, lang: str) -> dict:
    return {"id": c.id, "section": c.section, "name": localized(c, "name", lang), "icon": c.icon,
            "slug": c.slug, "sort_order": c.sort_order}


def product_public(p: Product, lang: str, low_threshold: int) -> dict:
    return {
        "id": p.id,
        "section": p.section,
        "category_id": p.category_id,
        "name": localized(p, "name", lang),
        "description": localized(p, "description", lang),
        "price": from_halalas(p.price),
        "price_text": money(p.price),
        "stock": p.stock,
        "low_stock": 0 < p.stock <= low_threshold,
        "min_qty": max(1, p.min_qty or 1),
        "max_qty": p.max_qty,
        "image_url": image_url(p.image_path),
        "icon": p.category.icon if p.category else None,
    }


def product_admin(p: Product) -> dict:
    return {
        "id": p.id, "section": p.section, "category_id": p.category_id,
        "category_name": (p.category.name_ru or p.category.name_uz) if p.category else "",
        "name_uz": p.name_uz, "name_ru": p.name_ru,
        "description_uz": p.description_uz, "description_ru": p.description_ru,
        "price": from_halalas(p.price), "price_text": money(p.price),
        "stock": p.stock, "min_qty": p.min_qty, "max_qty": p.max_qty,
        "image_url": image_url(p.image_path), "is_active": p.is_active, "sort_order": p.sort_order,
    }


def category_admin(c: Category) -> dict:
    return {"id": c.id, "section": c.section, "slug": c.slug, "name_uz": c.name_uz, "name_ru": c.name_ru,
            "icon": c.icon, "sort_order": c.sort_order, "is_active": c.is_active}


def order_dict(o: Order, lang: str, admin: bool = False) -> dict:
    pay = o.payment
    data = {
        "id": o.id,
        "number": o.number,
        "status": o.status,
        "status_text": t(lang, f"status.{o.status}"),
        "created_at": o.created_at.isoformat() + "Z",
        "created_local": fmt_dt(o.created_at),
        "customer_name": o.customer_name,
        "phone": o.phone,
        "delivery_type": o.delivery_type,
        "address": o.address,
        "comment": o.comment,
        "payment_method": o.payment_method,
        "payment_text": t(lang, f"pay.{o.payment_method}"),
        "payment_status": pay.status if pay else None,
        "has_receipt": bool(pay and pay.receipt_path),
        "total": from_halalas(o.total),
        "total_text": money(o.total),
        "items_count": o.items_count,
        "items": [
            {"product_id": i.product_id, "section": i.section,
             "name": (i.name_ru if lang == "ru" else i.name_uz) or i.name_uz or i.name_ru,
             "price": from_halalas(i.price), "price_text": money(i.price), "quantity": i.quantity,
             "subtotal": from_halalas(i.subtotal), "subtotal_text": money(i.subtotal)}
            for i in o.items
        ],
    }
    if pay and pay.receipt_path:
        data["receipt_url"] = f"/api/files/receipt/{pay.id}?{sign_file('receipt', pay.id)}"
    if admin:
        u = o.user
        data.update({
            "admin_note": o.admin_note,
            "stock_returned": o.stock_returned,
            "payment_note": pay.note if pay else "",
            "user": {"id": u.id, "telegram_id": u.telegram_id, "username": u.username,
                     "name": " ".join(x for x in [u.first_name, u.last_name] if x)} if u else None,
        })
    return data
