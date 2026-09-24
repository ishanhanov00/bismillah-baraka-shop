"""Client API: shop info, catalog, cart validation, profile."""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import SECTIONS
from ..database import get_session
from ..models import Category, Product
from ..security import CurrentUser, current_user
from ..serializers import category_public, image_url, product_public
from ..settings_service import BANK_KEYS, PUBLIC_KEYS, can_order_now, is_open_now, load_settings, typed
from ..utils import from_halalas, money, norm_lang

router = APIRouter(prefix="/api", tags=["public"])

PHONE_RE = re.compile(r"^\+?[0-9\s\-()]{7,24}$")


def valid_phone(phone: str) -> bool:
    return bool(PHONE_RE.match(phone or "")) and 7 <= len(re.sub(r"\D", "", phone)) <= 15


def profile_dict(cu: CurrentUser) -> dict:
    u = cu.user
    return {"telegram_id": u.telegram_id, "username": u.username, "first_name": u.first_name,
            "last_name": u.last_name, "full_name": u.full_name or " ".join(x for x in [u.first_name, u.last_name] if x),
            "phone": u.phone or "", "phone_verified": u.phone_verified, "language": u.language,
            "is_admin": cu.is_admin}


@router.get("/health")
async def health():
    return {"ok": True}


@router.get("/bootstrap")
async def bootstrap(lang: str | None = None, cu: CurrentUser = Depends(current_user),
                    session: AsyncSession = Depends(get_session)):
    lang = norm_lang(lang or cu.user.language)
    data = await load_settings(session)
    pub = typed({k: data[k] for k in PUBLIC_KEYS})
    pub["logo_url"] = image_url(data["logo_path"])
    pub["description"] = data.get(f"description_{lang}") or data.get(f"description_{data['primary_language']}", "")
    counts = {}
    for section in SECTIONS:
        rows = (await session.execute(select(Category).where(Category.section == section, Category.is_active.is_(True))
                                      .order_by(Category.sort_order, Category.id))).scalars().all()
        counts[section] = [category_public(c, lang) for c in rows]
    return {
        "user": profile_dict(cu),
        "settings": pub,
        "bank": {k.replace("bank_", ""): data[k] for k in BANK_KEYS},
        "is_open": is_open_now(data),
        "can_order": can_order_now(data),
        "categories": counts,
    }


@router.get("/catalog/{section}")
async def catalog(section: str, lang: str | None = None, cu: CurrentUser = Depends(current_user),
                  session: AsyncSession = Depends(get_session)):
    if section not in SECTIONS:
        raise HTTPException(404, detail={"code": "not_found"})
    lang = norm_lang(lang or cu.user.language)
    low = typed(await load_settings(session))["low_stock_threshold"]
    cats = (await session.execute(select(Category).where(Category.section == section, Category.is_active.is_(True))
                                  .order_by(Category.sort_order, Category.id))).scalars().all()
    active_ids = {c.id for c in cats}
    prods = (await session.execute(
        select(Product).options(selectinload(Product.category))
        .where(Product.section == section, Product.is_active.is_(True), Product.is_deleted.is_(False))
        .order_by(Product.sort_order, Product.id))).scalars().all()
    prods = [p for p in prods if p.category_id is None or p.category_id in active_ids]
    return {"categories": [category_public(c, lang) for c in cats],
            "products": [product_public(p, lang, low) for p in prods]}


@router.get("/products/{product_id}")
async def product(product_id: int, lang: str | None = None, cu: CurrentUser = Depends(current_user),
                  session: AsyncSession = Depends(get_session)):
    lang = norm_lang(lang or cu.user.language)
    p = (await session.execute(select(Product).options(selectinload(Product.category))
                               .where(Product.id == product_id))).scalar_one_or_none()
    if not p or p.is_deleted or not p.is_active:
        raise HTTPException(404, detail={"code": "not_found"})
    low = typed(await load_settings(session))["low_stock_threshold"]
    return product_public(p, lang, low)


class CartItem(BaseModel):
    product_id: int
    quantity: int = Field(ge=0, le=10000)


class CartIn(BaseModel):
    items: list[CartItem] = Field(default_factory=list, max_length=100)


@router.post("/cart/validate")
async def cart_validate(body: CartIn, lang: str | None = None, cu: CurrentUser = Depends(current_user),
                        session: AsyncSession = Depends(get_session)):
    """Returns real prices and stock for the items in the client's cart (the client never decides the price)."""
    lang = norm_lang(lang or cu.user.language)
    low = typed(await load_settings(session))["low_stock_threshold"]
    ids = list({i.product_id for i in body.items})
    prods = {p.id: p for p in (await session.execute(select(Product).options(selectinload(Product.category))
                                                     .where(Product.id.in_(ids)))).scalars().all()} if ids else {}
    out, total = [], 0
    for item in body.items:
        p = prods.get(item.product_id)
        if not p or p.is_deleted or not p.is_active:
            out.append({"product_id": item.product_id, "available": False, "stock": 0, "quantity": 0})
            continue
        info = product_public(p, lang, low)
        qty = min(item.quantity, p.stock)
        if p.max_qty:
            qty = min(qty, p.max_qty)
        ok = p.stock > 0 and qty >= max(1, p.min_qty or 1)
        sub = p.price * qty if ok else 0
        total += sub
        out.append({**info, "product_id": p.id, "available": ok, "quantity": qty if ok else 0,
                    "requested": item.quantity, "subtotal": from_halalas(sub), "subtotal_text": money(sub)})
    return {"items": out, "total": from_halalas(total), "total_text": money(total)}


@router.get("/me")
async def me(cu: CurrentUser = Depends(current_user)):
    return profile_dict(cu)


class ProfileIn(BaseModel):
    full_name: str | None = Field(default=None, max_length=80)
    phone: str | None = Field(default=None, max_length=24)
    language: str | None = None


@router.patch("/me")
async def update_me(body: ProfileIn, cu: CurrentUser = Depends(current_user),
                    session: AsyncSession = Depends(get_session)):
    u = cu.user
    if body.full_name is not None:
        u.full_name = body.full_name.strip()[:80] or None
    if body.phone is not None:
        phone = body.phone.strip()
        if phone and not valid_phone(phone):
            raise HTTPException(400, detail={"code": "bad_phone"})
        if phone != (u.phone or ""):
            u.phone = phone or None
            u.phone_verified = False
    if body.language is not None:
        u.language = norm_lang(body.language)
    await session.commit()
    return profile_dict(cu)
