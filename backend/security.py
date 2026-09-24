"""Telegram Mini App authentication.

Every API request from the Mini App carries the header `X-Telegram-Init-Data`.
The server checks its HMAC signature with BOT_TOKEN (https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app),
so nobody can fake a user id. The user is registered automatically on the first request.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import is_admin, settings
from .database import get_session, utcnow
from .models import User


class InitDataError(Exception):
    pass


def validate_init_data(init_data: str, bot_token: str, max_age: int = 86400) -> dict:
    if not init_data or not bot_token:
        raise InitDataError("empty")
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        raise InitDataError("malformed")
    data = dict(pairs)
    received_hash = data.pop("hash", None)
    if not received_hash:
        raise InitDataError("no hash")
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received_hash):
        raise InitDataError("bad hash")
    try:
        auth_date = int(data.get("auth_date", "0"))
    except ValueError:
        raise InitDataError("bad auth_date")
    if max_age and time.time() - auth_date > max_age:
        raise InitDataError("expired")
    try:
        user = json.loads(data.get("user", "{}"))
    except json.JSONDecodeError:
        raise InitDataError("bad user")
    if not isinstance(user, dict) or not isinstance(user.get("id"), int):
        raise InitDataError("no user")
    data["user"] = user
    return data


@dataclass
class CurrentUser:
    user: User
    tg: dict
    is_admin: bool

    @property
    def telegram_id(self) -> int:
        return self.user.telegram_id


async def upsert_user(session: AsyncSession, tg_user: dict) -> User:
    """Automatic registration / profile refresh from Telegram data."""
    tg_id = int(tg_user["id"])
    user = (await session.execute(select(User).where(User.telegram_id == tg_id))).scalar_one_or_none()
    now = utcnow()
    if user is None:
        lang = (tg_user.get("language_code") or "")[:2]
        user = User(
            telegram_id=tg_id,
            username=tg_user.get("username"),
            first_name=tg_user.get("first_name"),
            last_name=tg_user.get("last_name"),
            language=lang if lang in ("ru", "uz") else settings.PRIMARY_LANGUAGE,
            created_at=now,
            last_seen_at=now,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user
    changed = False
    for field in ("username", "first_name", "last_name"):
        value = tg_user.get(field)
        if value is not None and getattr(user, field) != value:
            setattr(user, field, value)
            changed = True
    if changed or not user.last_seen_at or (now - user.last_seen_at).total_seconds() > 300:
        user.last_seen_at = now
        await session.commit()
    return user


async def current_user(
    request: Request,
    x_telegram_init_data: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> CurrentUser:
    init_data = x_telegram_init_data or ""
    if not init_data and settings.DEV_MODE and settings.DEV_USER_ID:
        # Local browser testing only. NEVER enable DEV_MODE on the real server.
        tg = {"id": settings.DEV_USER_ID, "first_name": "Dev", "username": "dev_user", "language_code": "ru"}
    else:
        try:
            tg = validate_init_data(init_data, settings.BOT_TOKEN, settings.INITDATA_MAX_AGE)["user"]
        except InitDataError:
            raise HTTPException(status_code=401, detail={"code": "unauthorized"})
    user = await upsert_user(session, tg)
    if user.is_blocked:
        raise HTTPException(status_code=403, detail={"code": "blocked"})
    return CurrentUser(user=user, tg=tg, is_admin=is_admin(user.telegram_id))


async def admin_user(cu: CurrentUser = Depends(current_user)) -> CurrentUser:
    if not cu.is_admin:
        raise HTTPException(status_code=403, detail={"code": "forbidden"})
    return cu


# ---- signed short-lived links for private files (payment receipts) ----

def sign_file(kind: str, obj_id: int, ttl: int = 3600) -> str:
    exp = int(time.time()) + ttl
    msg = f"{kind}:{obj_id}:{exp}".encode()
    sig = hmac.new((settings.SECRET_KEY or settings.BOT_TOKEN).encode(), msg, hashlib.sha256).hexdigest()[:32]
    return f"exp={exp}&sig={sig}"


def check_file_sig(kind: str, obj_id: int, exp: int, sig: str) -> bool:
    if exp < time.time():
        return False
    msg = f"{kind}:{obj_id}:{exp}".encode()
    good = hmac.new((settings.SECRET_KEY or settings.BOT_TOKEN).encode(), msg, hashlib.sha256).hexdigest()[:32]
    return hmac.compare_digest(good, sig or "")
