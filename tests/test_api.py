"""End-to-end check of the whole backend (real server, temporary database, fake bot token).

Run:  python tests/test_api.py
Does not touch your real database and does not contact Telegram.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import hmac
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
TOKEN = "123456789:TEST-TOKEN-FOR-LOCAL-CHECKS-ONLY"
ADMIN, USER_A, USER_B = 111, 222, 333
OK = 0


def init_data(uid: int, username: str = "") -> str:
    fields = {"auth_date": str(int(time.time())), "query_id": "AAE",
              "user": json.dumps({"id": uid, "first_name": f"User{uid}", "username": username or f"user{uid}",
                                  "language_code": "ru"}, separators=(",", ":"))}
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def check(cond: bool, title: str) -> None:
    global OK
    if not cond:
        print("❌ FAIL:", title)
        sys.exit(1)
    OK += 1
    print("✅", title)


def jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (300, 200), (14, 124, 90)).save(buf, "JPEG")
    return buf.getvalue()


def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = dict(os.environ, BOT_TOKEN=TOKEN, ADMIN_IDS=str(ADMIN), RUN_BOT="false", DEV_MODE="false",
               SECRET_KEY="test-secret", DATABASE_URL=f"sqlite+aiosqlite:///{tmp / 'test.db'}",
               PORT=str(port), HOST="127.0.0.1", NOTIFY_CHAT_ID="")
    proc = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    created_uploads: list[Path] = []
    try:
        for _ in range(60):
            try:
                if httpx.get(base + "/api/health").status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.25)
        else:
            raise SystemExit("server did not start")

        H = lambda uid: {"X-Telegram-Init-Data": init_data(uid)}  # noqa: E731
        c = httpx.Client(base_url=base, timeout=20)

        check(c.get("/api/bootstrap").status_code == 401, "без initData → 401")
        bad = init_data(USER_A).replace("hash=", "hash=00")
        check(c.get("/api/bootstrap", headers={"X-Telegram-Init-Data": bad}).status_code == 401, "поддельная подпись → 401")
        b = c.get("/api/bootstrap", headers=H(USER_A)).json()
        check(b["user"]["is_admin"] is False and b["settings"]["business_name"], "bootstrap: клиент зарегистрирован автоматически")
        check(c.get("/api/admin/stats", headers=H(USER_A)).status_code == 403, "не-админ → 403 на админ-API")
        check(c.get("/api/admin/products", headers=H(USER_A)).status_code == 403, "не-админ не видит товары админки")
        check(c.get("/api/admin/stats", headers=H(ADMIN)).status_code == 200, "админ видит статистику")

        r = c.put("/api/admin/settings", headers=H(ADMIN), json={"store_open": True, "open_time": "00:00", "close_time": "00:00",
                                                               "bank_name": "Al Rajhi", "bank_iban": "SA00 0000"})
        check(r.status_code == 200 and r.json()["bank_name"] == "Al Rajhi", "админ сохраняет настройки и реквизиты")

        cats = c.get("/api/admin/categories", headers=H(ADMIN)).json()
        set_cat = next(x for x in cats if x["slug"] == "set")
        r = c.post("/api/admin/products", headers=H(ADMIN), json={
            "section": "menu", "category_id": set_cat["id"], "name_uz": "Palov", "name_ru": "Плов",
            "description_uz": "Mazali", "description_ru": "Вкусный", "price": "25", "stock": 5, "min_qty": 1,
            "max_qty": None, "is_active": True, "sort_order": 0})
        check(r.status_code == 200, "админ создаёт товар")
        pid = r.json()["id"]
        r = c.post(f"/api/admin/products/{pid}/image", headers=H(ADMIN), files={"file": ("p.jpg", jpeg(), "image/jpeg")})
        check(r.status_code == 200 and r.json()["image_url"], "загрузка фото товара")
        created_uploads.append(ROOT / r.json()["image_url"].lstrip("/"))

        cat = c.get("/api/catalog/menu", headers={**H(USER_A), "Accept-Language": "ru"}).json()
        check(any(p["id"] == pid for c_ in [cat] for p in json.loads(json.dumps(c_)).get("products", [])), "товар виден в каталоге")
        pd = c.get(f"/api/products/{pid}?lang=ru", headers=H(USER_A)).json()
        check(pd["stock"] == 5 and pd["price"] == 25, "страница товара: цена и остаток")

        order = {"items": [{"product_id": pid, "quantity": 2}], "customer_name": "Ali", "phone": "+966500000001",
                 "delivery_type": "delivery", "address": "Aziziya, Makkah", "comment": "", "payment_method": "cash"}
        r = c.post("/api/orders", headers=H(USER_A), json=order)
        check(r.status_code == 200, "клиент оформляет заказ (наличные)")
        o1 = r.json()
        check(o1["total"] == 50 and o1["number"] > 1000, "сумма считается на сервере (2×25=50)")
        check(c.get(f"/api/products/{pid}", headers=H(USER_A)).json()["stock"] == 3, "остаток 5 → 3")

        r = c.post("/api/orders", headers=H(USER_A), json={**order, "items": [{"product_id": pid, "quantity": 4}]})
        d = r.json()["detail"]
        check(r.status_code == 409 and d["code"] == "insufficient_stock" and d["available"] == 3, "нельзя заказать больше остатка (осталось 3)")

        r = c.post("/api/orders", headers=H(USER_B), json={**order, "payment_method": "transfer",
                                                           "items": [{"product_id": pid, "quantity": 1}]})
        check(r.status_code == 200 and r.json()["status"] == "awaiting_payment", "заказ с переводом → «Ожидает оплаты»")
        o2 = r.json()
        check(c.get(f"/api/orders/{o2['id']}", headers=H(USER_A)).status_code in (403, 404), "клиент А не видит заказ клиента Б")
        mine = c.get("/api/orders", headers=H(USER_A)).json()
        check(all(x["id"] != o2["id"] for x in mine) and any(x["id"] == o1["id"] for x in mine), "история заказов изолирована")

        r = c.post(f"/api/orders/{o2['id']}/receipt", headers=H(USER_B), files={"file": ("r.jpg", jpeg(), "image/jpeg")})
        check(r.status_code == 200 and r.json()["status"] == "payment_review", "загрузка чека → «Проверка оплаты»")
        adm = c.get(f"/api/admin/orders/{o2['id']}", headers=H(ADMIN)).json()
        check(bool(adm.get("receipt_url")) and adm["user"]["username"] == f"user{USER_B}", "админ видит чек и ник клиента")
        check(c.get(adm["receipt_url"]).status_code == 200, "чек открывается по подписанной ссылке")
        check(c.get(f"/api/files/receipt/1?exp=9999999999&sig=bad").status_code == 403, "без подписи чек недоступен")

        r = c.post(f"/api/admin/orders/{o2['id']}/payment", headers=H(USER_B), json={"action": "confirm"})
        check(r.status_code == 403, "клиент не может подтвердить свою оплату")
        r = c.post(f"/api/admin/orders/{o2['id']}/payment", headers=H(ADMIN), json={"action": "reject", "note": "сумма"})
        check(r.status_code == 200 and r.json()["status"] == "awaiting_payment", "админ отклоняет чек")
        c.post(f"/api/orders/{o2['id']}/receipt", headers=H(USER_B), files={"file": ("r.jpg", jpeg(), "image/jpeg")})
        r = c.post(f"/api/admin/orders/{o2['id']}/payment", headers=H(ADMIN), json={"action": "confirm"})
        check(r.status_code == 200 and r.json()["status"] == "paid", "повторный чек → админ подтверждает → «Оплачен»")

        check(c.get(f"/api/products/{pid}", headers=H(USER_A)).json()["stock"] == 2, "остаток 2")
        r = c.post(f"/api/admin/orders/{o1['id']}/status", headers=H(ADMIN), json={"status": "cancelled"})
        check(r.status_code == 200 and r.json()["status"] == "cancelled", "админ отменяет заказ")
        check(c.get(f"/api/products/{pid}", headers=H(USER_A)).json()["stock"] == 4, "отмена возвращает товар на склад (2 → 4)")
        r = c.post(f"/api/admin/orders/{o1['id']}/status", headers=H(ADMIN), json={"status": "new"})
        check(r.status_code == 400, "отменённый заказ нельзя «воскресить» (остаток не удвоится)")

        c.post(f"/api/admin/products/{pid}/stock", headers=H(ADMIN), json={"set": 1})
        uids = list(range(1000, 1010))
        bodies = [{**order, "items": [{"product_id": pid, "quantity": 1}]} for _ in uids]

        def buy(uid_body):
            uid, body = uid_body
            return httpx.post(base + "/api/orders", headers=H(uid), json=body, timeout=30).status_code

        with concurrent.futures.ThreadPoolExecutor(10) as ex:
            codes = list(ex.map(buy, zip(uids, bodies)))
        check(codes.count(200) == 1 and codes.count(409) == 9, f"10 клиентов одновременно за последней штукой → продана 1 ({codes})")
        check(c.get(f"/api/products/{pid}", headers=H(USER_A)).json()["stock"] == 0, "остаток 0, не отрицательный")
        r = c.post(f"/api/admin/products/{pid}/stock", headers=H(ADMIN), json={"delta": -5})
        check(r.status_code == 200 and r.json()["stock"] == 0, "остаток не уходит в минус")

        r = c.post("/api/cart/validate", headers=H(USER_A), json={"items": [{"product_id": pid, "quantity": 1}]})
        check(r.status_code == 200, "проверка корзины работает")

        s = c.get("/api/admin/stats", headers=H(ADMIN)).json()
        check(s["today"]["orders"] >= 2 and s["items_sold"] >= 2, "статистика считает заказы и продажи")
        cust = c.get("/api/admin/customers", headers=H(ADMIN)).json()
        check(len(cust) >= 3, "вкладка «Клиенты»")
        check(c.get("/api/admin/inventory", headers=H(ADMIN)).status_code == 200, "журнал склада")

        r = c.post("/api/admin/settings/logo", headers=H(ADMIN), files={"file": ("l.png", jpeg(), "image/jpeg")})
        check(r.status_code == 200, "загрузка логотипа")
        c.delete("/api/admin/settings/logo", headers=H(ADMIN))
        r = c.delete(f"/api/admin/products/{pid}", headers=H(ADMIN))
        check(r.status_code == 200 and all(p["id"] != pid for p in c.get("/api/catalog/menu", headers=H(USER_A)).json().get("products", [])),
              "удалённый товар исчезает из магазина")
        for page in ("/", "/admin", "/js/app.js", "/js/admin.js", "/css/app.css", "/static/logo.svg"):
            check(c.get(page).status_code == 200, f"страница {page} открывается")
        check(c.get("/uploads/receipts/").status_code in (403, 404, 405), "папка чеков закрыта для посторонних")
        print(f"\n🎉 Все проверки пройдены: {OK}")
    finally:
        proc.terminate()
        try:
            out = proc.communicate(timeout=10)[0].decode(errors="replace")
        except Exception:
            out = ""
        if OK == 0 or "Traceback" in out:
            print(out[-4000:])
        shutil.rmtree(tmp, ignore_errors=True)
        # remove files that the test uploaded into uploads/
        for sub in ("products", "receipts", "logo"):
            for f in (ROOT / "uploads" / sub).glob("*"):
                if f.name != ".gitkeep" and f.stat().st_mtime > START:
                    f.unlink()


START = time.time()
if __name__ == "__main__":
    main()
