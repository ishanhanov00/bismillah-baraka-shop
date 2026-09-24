"""Small helpers: money, time, localisation of admin-entered fields."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from .config import LANGUAGES, settings

TZ = ZoneInfo(settings.TIMEZONE)


def to_halalas(value) -> int:
    """'25', '25.5', 25.5 -> 2550. Raises ValueError for bad input."""
    try:
        d = Decimal(str(value).replace(",", ".").strip())
    except (InvalidOperation, AttributeError):
        raise ValueError("bad price")
    if d < 0 or d > Decimal("1000000"):
        raise ValueError("bad price")
    return int((d * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def from_halalas(value: int) -> float:
    return round((value or 0) / 100, 2)


def money(value: int, currency: str | None = None) -> str:
    amount = (value or 0) / 100
    text = f"{amount:,.0f}" if amount == int(amount) else f"{amount:,.2f}"
    return f"{text.replace(',', ' ')} {currency or settings.CURRENCY}"


def local_now() -> datetime:
    return datetime.now(TZ)


def to_local(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).astimezone(TZ)


def fmt_dt(dt: datetime | None) -> str:
    loc = to_local(dt)
    return loc.strftime("%d.%m.%Y %H:%M") if loc else ""


def local_day_start_utc(days_ago: int = 0) -> datetime:
    """Start of the local (Mecca) day `days_ago` days back, as naive UTC."""
    now = local_now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_ago)
    return start.astimezone(timezone.utc).replace(tzinfo=None)


def norm_lang(lang: str | None) -> str:
    lang = (lang or "").lower()[:2]
    return lang if lang in LANGUAGES else settings.PRIMARY_LANGUAGE


def localized(obj, field: str, lang: str, primary: str | None = None) -> str:
    """Return obj.<field>_<lang>, falling back to the primary language, then any language."""
    primary = primary or settings.PRIMARY_LANGUAGE
    for code in (lang, primary, *LANGUAGES):
        value = getattr(obj, f"{field}_{code}", None)
        if value:
            return value
    return ""
