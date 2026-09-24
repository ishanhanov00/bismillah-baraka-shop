"""Резервная копия базы данных и загруженных фото.

Запуск:  python scripts/backup.py
Результат: папка backups/ → shop-ГГГГММДД-ЧЧММСС.db и uploads-ГГГГММДД-ЧЧММСС.zip
Безопасно запускать во время работы магазина (используется backup API SQLite).
Хранятся последние 30 копий.
"""
from __future__ import annotations

import sqlite3
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.config import settings  # noqa: E402

KEEP = 30


def main() -> None:
    url = settings.DATABASE_URL
    if not url.startswith("sqlite"):
        print("База не SQLite. Для PostgreSQL используйте: pg_dump -Fc имя_базы > backup.dump")
        return
    db_path = Path(url.split("///", 1)[1])
    if not db_path.is_absolute():
        db_path = (ROOT / db_path).resolve()
    if not db_path.exists():
        print(f"Файл базы не найден: {db_path}")
        return
    out = ROOT / "backups"
    out.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    target = out / f"shop-{stamp}.db"
    src = sqlite3.connect(str(db_path))
    dst = sqlite3.connect(str(target))
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    print(f"✅ База сохранена: {target}")

    zpath = out / f"uploads-{stamp}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in (ROOT / "uploads").rglob("*"):
            if f.is_file() and f.name != ".gitkeep":
                z.write(f, f.relative_to(ROOT))
    print(f"✅ Фото и чеки сохранены: {zpath}")

    for pattern in ("shop-*.db", "uploads-*.zip"):
        files = sorted(out.glob(pattern))
        for old in files[:-KEEP]:
            old.unlink()


if __name__ == "__main__":
    main()
