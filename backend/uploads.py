"""Safe image uploads: size limit, real image check, re-encoding to JPEG/PNG (removes any hidden payload)."""
from __future__ import annotations

import io
import secrets

from fastapi import HTTPException, UploadFile
from PIL import Image, ImageOps

from .config import settings

try:  # iPhone HEIC photos (optional)
    from pillow_heif import register_heif_opener  # type: ignore
    register_heif_opener()
except Exception:  # pragma: no cover
    pass

Image.MAX_IMAGE_PIXELS = 40_000_000


async def save_image(file: UploadFile, folder: str, max_side: int = 1600, keep_png: bool = False) -> str:
    """Save an uploaded image to uploads/<folder>/ and return the relative path 'folder/name.jpg'."""
    limit = settings.MAX_UPLOAD_MB * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status_code=413, detail={"code": "file_too_large", "max_mb": settings.MAX_UPLOAD_MB})
    if not data:
        raise HTTPException(status_code=400, detail={"code": "bad_image"})
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        img = ImageOps.exif_transpose(img)
    except Exception:
        raise HTTPException(status_code=400, detail={"code": "bad_image"})
    img.thumbnail((max_side, max_side))
    target_dir = settings.UPLOAD_DIR / folder
    target_dir.mkdir(parents=True, exist_ok=True)
    name = secrets.token_hex(12)
    if keep_png and img.mode in ("RGBA", "LA", "P"):
        filename = f"{name}.png"
        img.convert("RGBA").save(target_dir / filename, "PNG", optimize=True)
    else:
        filename = f"{name}.jpg"
        if img.mode != "RGB":
            bg = Image.new("RGB", img.size, (255, 255, 255))
            rgba = img.convert("RGBA")
            bg.paste(rgba, mask=rgba.split()[-1])
            img = bg
        img.save(target_dir / filename, "JPEG", quality=85, optimize=True)
    return f"{folder}/{filename}"


def delete_upload(rel_path: str | None) -> None:
    if not rel_path:
        return
    path = (settings.UPLOAD_DIR / rel_path).resolve()
    if settings.UPLOAD_DIR.resolve() in path.parents and path.exists():
        try:
            path.unlink()
        except OSError:
            pass
