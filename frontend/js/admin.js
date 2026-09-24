/* BISMILLAH BARAKA — admin panel (opens inside Telegram, only for ADMIN_IDS; the server checks every request). */
(() => {
  "use strict";
  const tg = window.Telegram && window.Telegram.WebApp;
  const $app = document.getElementById("app");
  const $nav = document.getElementById("nav");
  const SECTIONS = { menu: "🍽 Меню", sadaqa: "🤲 Садака", events: "🏞 Мероприятия" };
  const STATUS = {
    new: "🆕 Новый", awaiting_payment: "💳 Ожидает оплаты", payment_review: "🔎 Проверка оплаты", paid: "✅ Оплачен",
    cooking: "👨‍🍳 Готовится", ready: "📦 Готов", delivering: "🚚 Доставляется", done: "✅ Выполнен", cancelled: "❌ Отменён",
  };
  const PAY_ST = { cash: "💵 Наличными при получении", pending: "⏳ Ждём чек", submitted: "🔎 Чек на проверке", confirmed: "✅ Оплата подтверждена", rejected: "❌ Чек отклонён" };
  const ERR = {
    network: "Нет соединения с интернетом", unauthorized: "Откройте админку через Telegram-бота", forbidden: "⛔ Доступ только для администраторов",
    bad_price: "Неверная цена", name_required: "Укажите название (хотя бы на одном языке)", bad_category: "Неверная категория",
    category_section_mismatch: "Категория из другого раздела", bad_qty_limits: "Максимум меньше минимума", category_not_empty: "В категории есть товары — сначала перенесите или удалите их",
    order_cancelled: "Заказ отменён — изменить нельзя", not_transfer: "Это не заказ с переводом", already_confirmed: "Оплата уже подтверждена",
    nothing_to_reject: "Нечего отклонять", bad_time: "Время в формате ЧЧ:ММ, например 08:00", file_too_large: "Файл слишком большой", bad_image: "Это не изображение",
    validation: "Проверьте заполнение полей",
  };
  const S = { depth: 0, cats: [], section: "menu", orderFilter: "active", q: "" };

  const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const haptic = (k = "light") => { try { if (!tg || !tg.HapticFeedback) return; if (["success", "error", "warning"].includes(k)) tg.HapticFeedback.notificationOccurred(k); else tg.HapticFeedback.impactOccurred(k); } catch (e) {} };
  let tt;
  const toast = (m, err) => {
    let el = document.getElementById("toast");
    if (!el) { el = document.createElement("div"); el.id = "toast"; el.className = "toast"; document.body.appendChild(el); }
    el.textContent = m; el.classList.toggle("err", !!err); el.classList.add("show"); clearTimeout(tt); tt = setTimeout(() => el.classList.remove("show"), 2600);
  };
  const confirmDialog = (m) => new Promise((r) => { if (tg && tg.showConfirm && tg.isVersionAtLeast && tg.isVersionAtLeast("6.2")) tg.showConfirm(m, (ok) => r(!!ok)); else r(window.confirm(m)); });
  const ph = (url, icon) => url ? `<img src="${esc(url)}" alt="" loading="lazy">` : `<div class="ph"><span>${esc(icon || "🍽")}</span></div>`;

  class ApiError extends Error { constructor(s, d) { super((d && d.code) || "error"); this.status = s; this.detail = d || {}; } }
  async function api(path, opts = {}) {
    const headers = { "X-Telegram-Init-Data": (tg && tg.initData) || "" };
    let body = opts.body;
    if (opts.form) body = opts.form; else if (body !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(body); }
    let res;
    try { res = await fetch(path, { method: opts.method || (body ? "POST" : "GET"), headers, body }); } catch (e) { throw new ApiError(0, { code: "network" }); }
    let data = null; try { data = await res.json(); } catch (e) {}
    if (!res.ok) throw new ApiError(res.status, (data && data.detail) || { code: "error" });
    return data;
  }
  const errText = (e) => ERR[(e.detail || {}).code] || "Ошибка. Попробуйте ещё раз.";
  const fail = (e) => { haptic("error"); toast(errText(e), true); };

  // ---------------------------------------------------------------- sheet (modal with inputs)
  function sheet(html) {
    const bg = document.createElement("div"); bg.className = "sheet-bg";
    bg.innerHTML = `<div class="sheet">${html}</div>`;
    bg.addEventListener("click", (e) => { if (e.target === bg) bg.remove(); });
    document.body.appendChild(bg);
    return { el: bg.querySelector(".sheet"), close: () => bg.remove() };
  }
  function askNumber(title, value, hint) {
    return new Promise((resolve) => {
      const s = sheet(`<h3>${esc(title)}</h3>${hint ? `<div class="muted small" style="margin-bottom:10px">${esc(hint)}</div>` : ""}
        <input class="input" id="num" inputmode="decimal" value="${esc(value)}"><div class="row mt"><button class="btn ghost" id="c">Отмена</button><button class="btn" id="ok">Сохранить</button></div>`);
      const inp = s.el.querySelector("#num"); setTimeout(() => { inp.focus(); inp.select(); }, 50);
      s.el.querySelector("#c").onclick = () => { s.close(); resolve(null); };
      s.el.querySelector("#ok").onclick = () => { s.close(); resolve(inp.value.trim()); };
    });
  }
  function askText(title, placeholder) {
    return new Promise((resolve) => {
      const s = sheet(`<h3>${esc(title)}</h3><textarea class="input" id="txt" placeholder="${esc(placeholder || "")}"></textarea>
        <div class="row mt"><button class="btn ghost" id="c">Отмена</button><button class="btn danger" id="ok">Подтвердить</button></div>`);
      s.el.querySelector("#c").onclick = () => { s.close(); resolve(null); };
      s.el.querySelector("#ok").onclick = () => { const v = s.el.querySelector("#txt").value; s.close(); resolve(v); };
    });
  }

  // ---------------------------------------------------------------- router
  const parse = () => { const [name, arg] = (location.hash || "#stats").replace(/^#\/?/, "").split("/"); return { name: name || "stats", arg }; };
  function go(hash, replace) { if (replace) history.replaceState(null, "", hash); else { history.pushState(null, "", hash); S.depth++; } render(); }
  window.addEventListener("popstate", () => { S.depth = Math.max(0, S.depth - 1); render(); });
  document.addEventListener("click", (e) => { const a = e.target.closest("[data-go]"); if (a) { e.preventDefault(); haptic(); go(a.getAttribute("data-go")); } });
  const TOP = ["stats", "orders", "products", "customers", "settings"];
  function back() { if (S.depth > 0) history.back(); else go("#" + ({ order: "orders", product: "products", categories: "products", customer: "customers" }[parse().name] || "stats"), true); }

  function render() {
    const r = parse();
    if (tg && tg.BackButton) { TOP.includes(r.name) ? tg.BackButton.hide() : tg.BackButton.show(); }
    window.scrollTo(0, 0);
    renderNav(r);
    ({ stats: renderStats, orders: renderOrders, order: () => renderOrder(r.arg), products: renderProducts,
       product: () => renderProduct(r.arg), categories: renderCategories, customers: renderCustomers,
       customer: () => renderCustomer(r.arg), settings: renderSettings }[r.name] || renderStats)();
  }
  function renderNav(r) {
    const map = { order: "orders", product: "products", categories: "products", customer: "customers" };
    const act = map[r.name] || r.name;
    const items = [["stats", "📊", "Статистика"], ["orders", "🧾", "Заказы"], ["products", "📦", "Товары"], ["customers", "👥", "Клиенты"], ["settings", "⚙️", "Настройки"]];
    $nav.innerHTML = `<div class="inner">${items.map(([k, i, l]) => `<button class="${act === k ? "on" : ""}" data-n="${k}"><span class="i">${i}</span>${l}</button>`).join("")}</div>`;
    $nav.querySelectorAll("[data-n]").forEach((b) => b.onclick = () => { haptic(); S.depth = 0; history.replaceState(null, "", "#" + b.dataset.n); render(); });
  }
  const top = (title, right = "") => `<div class="topbar"><h1>${title}</h1>${right}</div>`;
  const loading = (title) => { $app.innerHTML = `<div class="screen">${top(title)}<div class="center"><div class="spinner dark"></div></div></div>`; };
  const errorBox = (e) => `<div class="page-pad"><div class="notice err">${esc(errText(e))}</div><button class="btn" onclick="location.reload()">↻ Обновить</button></div>`;

  // ---------------------------------------------------------------- STATS
  async function renderStats() {
    loading("📊 Статистика");
    let s; try { s = await api("/api/admin/stats"); } catch (e) { $app.innerHTML = top("📊 Статистика") + errorBox(e); return; }
    const max = Math.max(1, ...s.days.map((d) => d.revenue));
    $app.innerHTML = `<div class="screen">${top("📊 Статистика", `<button class="chip" onclick="location.reload()">↻</button>`)}<div class="page-pad">
      <div class="stats">
        <div class="stat accent"><div class="k">Сегодня заказов</div><div class="v">${s.today.orders}</div></div>
        <div class="stat accent"><div class="k">Сегодня выручка</div><div class="v">${esc(s.today.revenue_text)}</div></div>
        <div class="stat"><div class="k">За 7 дней</div><div class="v">${s.week.orders}</div><div class="s">${esc(s.week.revenue_text)}</div></div>
        <div class="stat"><div class="k">За месяц</div><div class="v">${s.month.orders}</div><div class="s">${esc(s.month.revenue_text)}</div></div>
        <div class="stat"><div class="k">Продано товаров</div><div class="v">${s.items_sold_month}</div><div class="s">в этом месяце · всего ${s.items_sold}</div></div>
        <div class="stat"><div class="k">Клиенты</div><div class="v">${s.customers_with_orders}</div><div class="s">заказывали · всего ${s.users_total}</div></div>
      </div>
      <div class="card mt"><h3>📈 Выручка за 7 дней</h3><div class="bars">${s.days.map((d) =>
        `<div class="bar"><b>${d.orders}</b><i style="height:${Math.round((d.revenue / max) * 100)}%"></i>${esc(d.date)}</div>`).join("")}</div>
        <div class="muted small mt">Цифра над столбцом — количество заказов. Отменённые заказы не учитываются.</div></div>
      <div class="card"><h3>📌 Заказы по статусам</h3>${Object.entries(s.by_status).map(([k, v]) =>
        `<button class="list-row" data-st="${k}"><span class="grow">${STATUS[k]}</span><b>${v}</b></button>`).join("")}</div>
      <div class="card"><h3>🏆 Самые продаваемые</h3>${s.top_products.length ? s.top_products.map((p, i) =>
        `<div class="list-row"><b>${i + 1}.</b><span class="grow"><div class="t1">${esc(p.name)}</div><div class="t2">${esc(p.revenue_text)}</div></span><b>${p.quantity} шт.</b></div>`).join("") : '<div class="muted">Пока нет продаж</div>'}</div>
      <div class="card"><h3>📦 Остатки товаров</h3>${s.stock.length ? s.stock.map((p) =>
        `<button class="list-row" data-go="#product/${p.id}"><span class="grow"><div class="t1">${esc(p.name)}</div><div class="t2">${SECTIONS[p.section] || ""}${p.is_active ? "" : " · скрыт"}</div></span>
         <span class="pill ${p.stock <= 0 ? "off" : p.low ? "low" : "ok"}">${p.stock} шт.</span></button>`).join("") : '<div class="muted">Товаров пока нет</div>'}</div>
    </div></div>`;
    $app.querySelectorAll("[data-st]").forEach((b) => b.onclick = () => { S.orderFilter = b.dataset.st; go("#orders"); });
  }

  // ---------------------------------------------------------------- ORDERS
  async function renderOrders() {
    const filters = [["active", "🔥 Активные"], ["", "Все"], ...Object.entries(STATUS)];
    const draw = (list) => {
      $app.innerHTML = `<div class="screen">${top("🧾 Заказы", `<button class="chip" id="rf">↻</button>`)}
        <div class="page-pad" style="margin-bottom:10px"><input class="input" id="q" placeholder="🔍 Номер, имя или телефон" value="${esc(S.q)}"></div>
        <div class="tabs">${filters.map(([k, l]) => `<button class="chip ${S.orderFilter === k ? "on" : ""}" data-f="${k}">${l}</button>`).join("")}</div>
        <div class="page-pad">${list === null ? '<div class="center"><div class="spinner dark"></div></div>' : (list.length ? list.map((o) => `
          <button class="card order-card" data-go="#order/${o.id}">
            <div class="top"><div><div class="num">№${o.number} · ${esc(o.customer_name)}</div><div class="date">${esc(o.created_local)} · ${esc(o.phone)}</div></div><span class="st ${o.status}">${STATUS[o.status]}</span></div>
            <div class="items">${esc(o.items.map((i) => `${i.name} × ${i.quantity}`).join(", "))}</div>
            <div class="bottom"><span class="muted small">${o.payment_method === "cash" ? "💵 Наличные" : "🏦 Перевод"}${o.has_receipt ? " · 📎 чек" : ""}</span><b>${esc(o.total_text)}</b></div>
          </button>`).join("") : '<div class="empty"><div class="big">🧾</div><h3>Заказов нет</h3></div>')}</div></div>`;
      $app.querySelectorAll("[data-f]").forEach((b) => b.onclick = () => { S.orderFilter = b.dataset.f; haptic(); load(); });
      $app.querySelector("#rf").onclick = () => load();
      let timer; const q = $app.querySelector("#q");
      q.oninput = () => { clearTimeout(timer); timer = setTimeout(() => { S.q = q.value; load(true); }, 400); };
    };
    const load = async (keepFocus) => {
      if (!keepFocus) draw(null);
      try {
        const list = await api(`/api/admin/orders?status=${encodeURIComponent(S.orderFilter)}&q=${encodeURIComponent(S.q)}`);
        if (parse().name !== "orders") return;
        const pos = keepFocus ? $app.querySelector("#q").selectionStart : null;
        draw(list);
        if (keepFocus) { const q = $app.querySelector("#q"); q.focus(); q.setSelectionRange(pos, pos); }
      } catch (e) { $app.innerHTML = top("🧾 Заказы") + errorBox(e); }
    };
    load();
  }

  async function renderOrder(id) {
    loading("Заказ");
    let o; try { o = await api(`/api/admin/orders/${encodeURIComponent(id)}`); } catch (e) { $app.innerHTML = top("Заказ") + errorBox(e); return; }
    const draw = () => {
      const u = o.user || {};
      const tgLink = u.username ? `https://t.me/${u.username}` : `tg://user?id=${u.telegram_id}`;
      const phoneDigits = (o.phone || "").replace(/\D/g, "");
      const canPay = o.payment_method === "transfer" && o.status !== "cancelled" && o.payment_status !== "confirmed";
      const statuses = ["new", "paid", "cooking", "ready", "delivering", "done"];
      $app.innerHTML = `<div class="screen">${top(`Заказ №${o.number}`)}<div class="page-pad">
        <div class="card">
          <div class="line"><span>Статус</span><span class="st ${o.status}">${STATUS[o.status]}</span></div>
          <div class="line"><span>Дата и время</span><span>${esc(o.created_local)}</span></div>
          <div class="line"><span>Клиент</span><span>${esc(o.customer_name)}</span></div>
          <div class="line"><span>Telegram</span><span><a href="${esc(tgLink)}" data-ext>${u.username ? "@" + esc(u.username) : "ID " + esc(u.telegram_id)}</a></span></div>
          <div class="line"><span>Телефон</span><span><a href="tel:${esc(o.phone)}">${esc(o.phone)}</a> · <a href="https://wa.me/${esc(phoneDigits)}" data-ext>WhatsApp</a></span></div>
          <div class="line"><span>Получение</span><span>${o.delivery_type === "delivery" ? "🚚 Доставка" : "🏃 Самовывоз"}</span></div>
          ${o.address ? `<div class="line"><span>Адрес</span><span>${esc(o.address)}</span></div>` : ""}
          ${o.comment ? `<div class="line"><span>Комментарий</span><span>${esc(o.comment)}</span></div>` : ""}
        </div>
        <div class="card"><h3>🛒 Товары</h3>${o.items.map((i) => `<div class="line"><span>${esc(i.name)} × ${i.quantity}</span><span>${esc(i.subtotal_text)}</span></div>`).join("")}
          <div class="total-row"><span>Итого</span><span>${esc(o.total_text)}</span></div></div>
        <div class="card"><h3>💳 Оплата</h3>
          <div class="line"><span>Способ</span><span>${o.payment_method === "cash" ? "💵 Наличными" : "🏦 Банковский перевод"}</span></div>
          <div class="line"><span>Состояние</span><span>${PAY_ST[o.payment_status] || "—"}</span></div>
          ${o.payment_note ? `<div class="line"><span>Причина отказа</span><span>${esc(o.payment_note)}</span></div>` : ""}
          ${o.receipt_url ? `<a href="${esc(o.receipt_url)}" target="_blank"><img class="receipt-img" src="${esc(o.receipt_url)}" alt="Чек"></a>` : (o.payment_method === "transfer" ? '<div class="notice warn mt">Клиент ещё не отправил чек</div>' : "")}
          ${canPay ? `<div class="row mt"><button class="btn" id="pay-ok">✅ Подтвердить</button><button class="btn danger" id="pay-no">❌ Отклонить</button></div>` : ""}
        </div>
        ${o.status !== "cancelled" ? `<div class="card"><h3>📌 Изменить статус</h3><div class="status-grid">${statuses.map((s) =>
          `<button class="btn ghost ${o.status === s ? "cur" : ""}" data-status="${s}">${STATUS[s]}</button>`).join("")}</div>
          <button class="btn danger mt" data-status="cancelled">❌ Отменить заказ (товар вернётся на склад)</button></div>`
          : `<div class="notice err">Заказ отменён. ${o.stock_returned ? "Товары возвращены на склад." : ""}</div>`}
        <div class="card"><h3>📝 Заметка администратора</h3><textarea class="input" id="note" placeholder="Видна только администраторам">${esc(o.admin_note || "")}</textarea>
          <button class="btn secondary sm mt" id="save-note">Сохранить заметку</button></div>
        ${o.user ? `<button class="btn ghost" data-go="#customer/${o.user.id}">👤 Все заказы клиента</button>` : ""}
      </div></div>`;
      $app.querySelectorAll("a[data-ext]").forEach((a) => a.onclick = (e) => { if (tg) { e.preventDefault(); a.href.startsWith("https://t.me/") ? tg.openTelegramLink(a.href) : tg.openLink(a.href); } });
      const upd = async (fn) => { try { o = await fn(); haptic("success"); toast("✅ Сохранено"); draw(); } catch (e) { fail(e); } };
      $app.querySelectorAll("[data-status]").forEach((b) => b.onclick = async () => {
        const st = b.dataset.status; if (st === o.status) return;
        if (st === "cancelled" && !(await confirmDialog("Отменить заказ? Товары вернутся на склад. Отменённый заказ нельзя восстановить."))) return;
        upd(() => api(`/api/admin/orders/${o.id}/status`, { body: { status: st } }));
      });
      const ok = $app.querySelector("#pay-ok");
      if (ok) ok.onclick = async () => { if (await confirmDialog("Деньги действительно поступили? Подтвердить оплату?")) upd(() => api(`/api/admin/orders/${o.id}/payment`, { body: { action: "confirm" } })); };
      const no = $app.querySelector("#pay-no");
      if (no) no.onclick = async () => { const note = await askText("Отклонить оплату", "Причина (необязательно), например: сумма не совпадает"); if (note !== null) upd(() => api(`/api/admin/orders/${o.id}/payment`, { body: { action: "reject", note } })); };
      $app.querySelector("#save-note").onclick = () => upd(() => api(`/api/admin/orders/${o.id}/note`, { body: { note: $app.querySelector("#note").value } }));
    };
    draw();
  }

  // ---------------------------------------------------------------- PRODUCTS
  async function loadCats() { S.cats = await api("/api/admin/categories"); return S.cats; }
  async function renderProducts() {
    loading("📦 Товары");
    let list;
    try { [list] = await Promise.all([api(`/api/admin/products?section=${S.section}`), loadCats()]); } catch (e) { $app.innerHTML = top("📦 Товары") + errorBox(e); return; }
    const cats = S.cats.filter((c) => c.section === S.section);
    const group = (c) => list.filter((p) => (c ? p.category_id === c.id : !p.category_id || !cats.some((x) => x.id === p.category_id)));
    const row = (p) => `<div class="list-row">
        <button class="cthumb" data-go="#product/${p.id}">${ph(p.image_url, c_icon(p))}</button>
        <div class="grow"><button data-go="#product/${p.id}" style="text-align:left;width:100%"><div class="t1">${esc(p.name_ru || p.name_uz)}</div>
          <div class="t2">${esc(p.price_text)} ${p.is_active ? "" : '<span class="pill off">скрыт</span>'}</div></button>
          <div class="stock-ctl"><button data-d="${p.id}" data-v="-1">−</button><button class="num" data-set="${p.id}" data-cur="${p.stock}">${p.stock} шт.</button><button data-d="${p.id}" data-v="1">+</button>
          <button data-t="${p.id}" title="Скрыть/показать">${p.is_active ? "👁" : "🚫"}</button></div></div></div>`;
    const c_icon = (p) => (S.cats.find((c) => c.id === p.category_id) || {}).icon;
    const blocks = [...cats.map((c) => ({ c, items: group(c) })), { c: null, items: group(null) }].filter((b) => b.items.length);
    $app.innerHTML = `<div class="screen">${top("📦 Товары", `<button class="chip" data-go="#categories">🗂 Категории</button>`)}
      <div class="tabs">${Object.entries(SECTIONS).map(([k, l]) => `<button class="chip ${S.section === k ? "on" : ""}" data-sec="${k}">${l}</button>`).join("")}</div>
      <div class="page-pad">${blocks.length ? blocks.map((b) => `<div class="card"><h3>${b.c ? esc(b.c.icon + " " + (b.c.name_ru || b.c.name_uz)) : "Без категории"}${b.c && !b.c.is_active ? ' <span class="pill off">скрыта</span>' : ""}</h3>${b.items.map(row).join("")}</div>`).join("")
        : '<div class="empty"><div class="big">📦</div><h3>В этом разделе пока нет товаров</h3><div>Нажмите «➕ Добавить товар»</div></div>'}</div>
      <button class="fab" data-go="#product/new">➕ Добавить товар</button></div>`;
    $app.querySelectorAll("[data-sec]").forEach((b) => b.onclick = () => { S.section = b.dataset.sec; haptic(); renderProducts(); });
    $app.querySelectorAll("[data-d]").forEach((b) => b.onclick = async () => {
      try { const p = await api(`/api/admin/products/${b.dataset.d}/stock`, { body: { delta: Number(b.dataset.v) } }); haptic(); const n = b.parentElement.querySelector(".num"); n.textContent = p.stock + " шт."; n.dataset.cur = p.stock; } catch (e) { fail(e); }
    });
    $app.querySelectorAll("[data-set]").forEach((b) => b.onclick = async () => {
      const v = await askNumber("Остаток (количество в наличии)", b.dataset.cur, "Укажите точное количество, например 20");
      if (v === null) return;
      if (!/^\d+$/.test(v)) { toast("Введите целое число", true); return; }
      try { const p = await api(`/api/admin/products/${b.dataset.set}/stock`, { body: { set: Number(v) } }); haptic("success"); b.textContent = p.stock + " шт."; b.dataset.cur = p.stock; } catch (e) { fail(e); }
    });
    $app.querySelectorAll("[data-t]").forEach((b) => b.onclick = async () => { try { await api(`/api/admin/products/${b.dataset.t}/toggle`, { body: {} }); haptic(); renderProducts(); } catch (e) { fail(e); } });
  }

  async function renderProduct(id) {
    const isNew = id === "new";
    loading(isNew ? "Новый товар" : "Товар");
    let p;
    try {
      await loadCats();
      p = isNew ? { section: S.section, category_id: null, name_uz: "", name_ru: "", description_uz: "", description_ru: "", price: "", stock: 0, min_qty: 1, max_qty: null, is_active: true, sort_order: 0, image_url: null }
        : await api(`/api/admin/products/${encodeURIComponent(id)}`);
    } catch (e) { $app.innerHTML = top("Товар") + errorBox(e); return; }
    let newImage = null;
    const draw = () => {
      const cats = S.cats.filter((c) => c.section === p.section);
      const preview = newImage ? URL.createObjectURL(newImage) : p.image_url;
      $app.innerHTML = `<div class="screen">${top(isNew ? "➕ Новый товар" : "✏️ " + esc(p.name_ru || p.name_uz))}<div class="page-pad">
        <div class="card"><h3>📸 Фотография</h3><div class="imgedit"><div class="cthumb">${ph(preview, (cats.find((c) => c.id === p.category_id) || {}).icon)}</div>
          <div class="grow"><label class="btn secondary sm"><input type="file" accept="image/*" id="img" hidden>${preview ? "Заменить фото" : "Загрузить фото"}</label>
          ${p.image_url && !isNew ? '<button class="btn ghost sm mt" id="img-del">Удалить фото</button>' : ""}</div></div>
          <div class="muted small mt">Без фото клиент увидит красивую заглушку.</div></div>
        <div class="card"><h3>📂 Раздел и категория</h3>
          <label class="field"><span>Раздел</span><select class="input" id="section">${Object.entries(SECTIONS).map(([k, l]) => `<option value="${k}" ${p.section === k ? "selected" : ""}>${l}</option>`).join("")}</select></label>
          <label class="field"><span>Категория</span><select class="input" id="category"><option value="">— Без категории —</option>${cats.map((c) => `<option value="${c.id}" ${p.category_id === c.id ? "selected" : ""}>${esc(c.icon + " " + (c.name_ru || c.name_uz))}</option>`).join("")}</select></label></div>
        <div class="card"><h3>📝 Название и описание</h3>
          <label class="field"><span>Название<span class="lang-tag">UZ</span></span><input class="input" id="name_uz" maxlength="160" value="${esc(p.name_uz)}"></label>
          <label class="field"><span>Название<span class="lang-tag">RU</span></span><input class="input" id="name_ru" maxlength="160" value="${esc(p.name_ru)}"></label>
          <label class="field"><span>Описание<span class="lang-tag">UZ</span></span><textarea class="input" id="description_uz" rows="4">${esc(p.description_uz)}</textarea></label>
          <label class="field"><span>Описание<span class="lang-tag">RU</span></span><textarea class="input" id="description_ru" rows="4">${esc(p.description_ru)}</textarea></label>
          <div class="muted small">Если перевод не указан, клиенту покажется текст на основном языке.</div></div>
        <div class="card"><h3>💰 Цена и остаток</h3>
          <div class="two-col"><label class="field"><span>Цена, SAR</span><input class="input" id="price" inputmode="decimal" value="${esc(p.price)}" placeholder="25"></label>
          <label class="field"><span>В наличии, шт.</span><input class="input" id="stock" inputmode="numeric" value="${esc(p.stock)}"></label></div>
          <div class="two-col"><label class="field"><span>Мин. заказ</span><input class="input" id="min_qty" inputmode="numeric" value="${esc(p.min_qty)}"></label>
          <label class="field"><span>Макс. заказ</span><input class="input" id="max_qty" inputmode="numeric" value="${esc(p.max_qty || "")}" placeholder="без лимита"></label></div>
          <label class="field"><span>Порядок сортировки (меньше — выше)</span><input class="input" id="sort_order" inputmode="numeric" value="${esc(p.sort_order)}"></label>
          <label class="switch">Показывать клиентам<input type="checkbox" id="is_active" ${p.is_active ? "checked" : ""}></label></div>
        <button class="btn" id="save">💾 Сохранить</button>
        ${isNew ? "" : '<button class="btn danger mt" id="del">🗑 Удалить товар</button>'}
      </div></div>`;
      const v = (i) => $app.querySelector("#" + i).value;
      const collect = () => ({ section: v("section"), category_id: v("category") ? Number(v("category")) : null, name_uz: v("name_uz").trim(), name_ru: v("name_ru").trim(),
        description_uz: v("description_uz").trim(), description_ru: v("description_ru").trim(), price: v("price").trim(),
        stock: parseInt(v("stock") || "0", 10), min_qty: parseInt(v("min_qty") || "1", 10), max_qty: v("max_qty") ? parseInt(v("max_qty"), 10) : null,
        sort_order: parseInt(v("sort_order") || "0", 10), is_active: $app.querySelector("#is_active").checked });
      $app.querySelector("#section").onchange = () => { Object.assign(p, collect(), { section: v("section"), category_id: null }); draw(); };
      $app.querySelector("#img").onchange = (e) => { Object.assign(p, collect()); newImage = e.target.files[0] || null; draw(); };
      const idel = $app.querySelector("#img-del");
      if (idel) idel.onclick = async () => { if (!(await confirmDialog("Удалить фото?"))) return; try { const r = await api(`/api/admin/products/${p.id}/image`, { method: "DELETE" }); Object.assign(p, collect(), { image_url: r.image_url }); draw(); } catch (e) { fail(e); } };
      $app.querySelector("#save").onclick = async () => {
        const data = collect();
        if (!data.name_uz && !data.name_ru) return toast("Укажите название", true);
        if (!data.price || isNaN(Number(data.price.replace(",", ".")))) return toast("Укажите цену", true);
        if ([data.stock, data.min_qty].some((n) => isNaN(n) || n < 0)) return toast("Проверьте количество", true);
        const btn = $app.querySelector("#save"); btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
        try {
          let saved = await api(isNew ? "/api/admin/products" : `/api/admin/products/${p.id}`, { method: isNew ? "POST" : "PUT", body: data });
          if (newImage) { const fd = new FormData(); fd.append("file", newImage); saved = await api(`/api/admin/products/${saved.id}/image`, { form: fd }); }
          haptic("success"); toast("✅ Товар сохранён"); S.section = saved.section;
          go("#products", true);
        } catch (e) { fail(e); btn.disabled = false; btn.textContent = "💾 Сохранить"; }
      };
      const del = $app.querySelector("#del");
      if (del) del.onclick = async () => {
        if (!(await confirmDialog("Удалить товар? Он исчезнет из магазина. История заказов сохранится."))) return;
        try { await api(`/api/admin/products/${p.id}`, { method: "DELETE" }); haptic("warning"); toast("Товар удалён"); go("#products", true); } catch (e) { fail(e); }
      };
    };
    draw();
  }

  // ---------------------------------------------------------------- CATEGORIES
  async function renderCategories() {
    loading("🗂 Категории");
    try { await loadCats(); } catch (e) { $app.innerHTML = top("🗂 Категории") + errorBox(e); return; }
    $app.innerHTML = `<div class="screen">${top("🗂 Категории")}<div class="page-pad">
      ${Object.entries(SECTIONS).map(([sec, label]) => `<div class="card"><h3>${label}</h3>
        ${S.cats.filter((c) => c.section === sec).map((c) => `<button class="list-row" data-cat="${c.id}"><span style="font-size:24px">${esc(c.icon)}</span>
          <span class="grow"><div class="t1">${esc(c.name_ru || c.name_uz)}</div><div class="t2">${esc(c.name_uz)} · порядок ${c.sort_order}</div></span>${c.is_active ? "" : '<span class="pill off">скрыта</span>'}</button>`).join("") || '<div class="muted">Нет категорий</div>'}
        <button class="btn secondary sm mt" data-new="${sec}">➕ Добавить категорию</button></div>`).join("")}
    </div></div>`;
    $app.querySelectorAll("[data-cat]").forEach((b) => b.onclick = () => catForm(S.cats.find((c) => String(c.id) === b.dataset.cat)));
    $app.querySelectorAll("[data-new]").forEach((b) => b.onclick = () => catForm({ section: b.dataset.new, name_uz: "", name_ru: "", icon: "🍽", sort_order: 0, is_active: true }));
  }
  function catForm(c) {
    const s = sheet(`<h3>${c.id ? "Изменить категорию" : "Новая категория"}</h3>
      <label class="field"><span>Раздел</span><select class="input" id="c-sec">${Object.entries(SECTIONS).map(([k, l]) => `<option value="${k}" ${c.section === k ? "selected" : ""}>${l}</option>`).join("")}</select></label>
      <div class="two-col"><label class="field"><span>Иконка (эмодзи)</span><input class="input" id="c-icon" maxlength="8" value="${esc(c.icon)}"></label>
      <label class="field"><span>Порядок</span><input class="input" id="c-sort" inputmode="numeric" value="${esc(c.sort_order)}"></label></div>
      <label class="field"><span>Название<span class="lang-tag">UZ</span></span><input class="input" id="c-uz" value="${esc(c.name_uz)}"></label>
      <label class="field"><span>Название<span class="lang-tag">RU</span></span><input class="input" id="c-ru" value="${esc(c.name_ru)}"></label>
      <label class="switch">Показывать клиентам<input type="checkbox" id="c-act" ${c.is_active ? "checked" : ""}></label>
      <button class="btn mt" id="c-save">💾 Сохранить</button>${c.id ? '<button class="btn danger mt" id="c-del">🗑 Удалить</button>' : ""}`);
    const g = (i) => s.el.querySelector(i);
    g("#c-save").onclick = async () => {
      const body = { section: g("#c-sec").value, icon: g("#c-icon").value || "🍽", sort_order: parseInt(g("#c-sort").value || "0", 10) || 0,
        name_uz: g("#c-uz").value.trim(), name_ru: g("#c-ru").value.trim(), is_active: g("#c-act").checked };
      try { await api(c.id ? `/api/admin/categories/${c.id}` : "/api/admin/categories", { method: c.id ? "PUT" : "POST", body }); s.close(); haptic("success"); renderCategories(); } catch (e) { fail(e); }
    };
    const d = g("#c-del");
    if (d) d.onclick = async () => { if (!(await confirmDialog("Удалить категорию?"))) return; try { await api(`/api/admin/categories/${c.id}`, { method: "DELETE" }); s.close(); renderCategories(); } catch (e) { fail(e); } };
  }

  // ---------------------------------------------------------------- CUSTOMERS
  async function renderCustomers() {
    const draw = (list, q) => {
      $app.innerHTML = `<div class="screen">${top("👥 Клиенты")}<div class="page-pad">
        <input class="input" id="q" placeholder="🔍 Имя, @username или телефон" value="${esc(q || "")}" style="margin-bottom:12px">
        <div class="muted small" style="margin-bottom:10px">Каждый клиент регистрируется автоматически через Telegram. Клиент видит только свои заказы.</div>
        <div class="card">${list.length ? list.map((c) => `<button class="list-row" data-go="#customer/${c.id}"><div class="avatar" style="width:42px;height:42px;border-radius:14px;font-size:17px">${esc((c.name || "?").slice(0, 1).toUpperCase())}</div>
          <span class="grow"><div class="t1">${esc(c.name)}</div><div class="t2">${c.username ? "@" + esc(c.username) + " · " : ""}${esc(c.phone || "без телефона")}${c.phone_verified ? " ✔︎" : ""}</div>
          <div class="t2">Регистрация: ${esc(c.registered)}${c.last_order ? " · последний заказ: " + esc(c.last_order) : ""}</div></span>
          <span style="text-align:right"><b>${c.orders}</b><div class="t2">${esc(c.spent_text)}</div></span></button>`).join("") : '<div class="muted">Клиентов пока нет</div>'}</div></div></div>`;
      let tm; const inp = $app.querySelector("#q");
      inp.oninput = () => { clearTimeout(tm); tm = setTimeout(async () => { const pos = inp.selectionStart; try { draw(await api(`/api/admin/customers?q=${encodeURIComponent(inp.value)}`), inp.value); const n = $app.querySelector("#q"); n.focus(); n.setSelectionRange(pos, pos); } catch (e) { fail(e); } }, 400); };
    };
    loading("👥 Клиенты");
    try { draw(await api("/api/admin/customers"), ""); } catch (e) { $app.innerHTML = top("👥 Клиенты") + errorBox(e); }
  }
  async function renderCustomer(arg) {
    loading("Клиент");
    try {
      const userId = arg;
      const list = await api(`/api/admin/customers/${encodeURIComponent(userId)}/orders`);
      const total = list.filter((o) => o.status !== "cancelled").reduce((a, o) => a + o.total, 0);
      const u = list[0] && list[0].user;
      $app.innerHTML = `<div class="screen">${top("👤 " + esc(list[0] ? list[0].customer_name : "Клиент"))}<div class="page-pad">
        <div class="card"><div class="line"><span>Telegram</span><span>${u ? (u.username ? "@" + esc(u.username) : "ID " + esc(u.telegram_id)) : "—"}</span></div>
          <div class="line"><span>Заказов</span><span>${list.length}</span></div><div class="line"><span>Сумма (без отменённых)</span><span>${total.toFixed(2)} SAR</span></div></div>
        ${list.map((o) => `<button class="card order-card" data-go="#order/${o.id}"><div class="top"><div><div class="num">№${o.number}</div><div class="date">${esc(o.created_local)}</div></div><span class="st ${o.status}">${STATUS[o.status]}</span></div>
          <div class="items">${esc(o.items.map((i) => `${i.name} × ${i.quantity}`).join(", "))}</div><div class="bottom"><span></span><b>${esc(o.total_text)}</b></div></button>`).join("") || '<div class="muted">Заказов нет</div>'}
      </div></div>`;
    } catch (e) { $app.innerHTML = top("Клиент") + errorBox(e); }
  }

  // ---------------------------------------------------------------- SETTINGS
  async function renderSettings() {
    loading("⚙️ Настройки");
    let s; try { s = await api("/api/admin/settings"); } catch (e) { $app.innerHTML = top("⚙️ Настройки") + errorBox(e); return; }
    const inp = (k, label, extra = "") => `<label class="field"><span>${label}</span><input class="input" data-k="${k}" value="${esc(s[k])}" ${extra}></label>`;
    const area = (k, label, rows = 3) => `<label class="field"><span>${label}</span><textarea class="input" data-k="${k}" rows="${rows}">${esc(s[k])}</textarea></label>`;
    const sw = (k, label) => `<label class="switch">${label}<input type="checkbox" data-b="${k}" ${s[k] ? "checked" : ""}></label>`;
    $app.innerHTML = `<div class="screen">${top("⚙️ Настройки")}<div class="page-pad">
      <div class="card"><h3>🏪 Бизнес</h3>
        <div class="imgedit" style="margin-bottom:14px"><div class="cthumb"><img src="${esc(s.logo_url || "/static/logo.svg")}" alt=""></div>
          <div class="grow"><label class="btn secondary sm"><input type="file" accept="image/*" id="logo" hidden>Загрузить логотип</label>
          ${s.logo_url ? '<button class="btn ghost sm mt" id="logo-del">Вернуть стандартный</button>' : ""}</div></div>
        ${inp("business_name", "Название бизнеса")}
        ${area("description_uz", 'Описание<span class="lang-tag">UZ</span>')}${area("description_ru", 'Описание<span class="lang-tag">RU</span>')}</div>
      <div class="card"><h3>🕒 Рабочее время</h3>
        ${sw("store_open", "Магазин открыт (главный переключатель)")}
        <div class="two-col mt"><label class="field"><span>Открытие</span><input class="input" type="time" data-k="open_time" value="${esc(s.open_time)}"></label>
        <label class="field"><span>Закрытие</span><input class="input" type="time" data-k="close_time" value="${esc(s.close_time)}"></label></div>
        ${inp("work_hours_text", "Текст о времени работы (необязательно)", 'placeholder="Например: ежедневно 08:00–23:00"')}
        ${sw("allow_orders_when_closed", "Принимать заказы вне рабочего времени")}
        <div class="muted small">Если одинаковое время открытия и закрытия — магазин работает круглосуточно. Время Мекки.</div></div>
      <div class="card"><h3>🚚 Получение заказа</h3>${sw("delivery_enabled", "Доставка по Мекке")}${sw("pickup_enabled", "Самовывоз")}</div>
      <div class="card"><h3>📞 Контакты</h3>${inp("phone", "Телефон", 'inputmode="tel"')}${inp("whatsapp", "WhatsApp (номер)", 'inputmode="tel"')}${inp("instagram", "Instagram (@username)")}${area("address", "Адрес", 2)}</div>
      <div class="card"><h3>🏦 Реквизиты банковского перевода</h3>${inp("bank_name", "Название банка")}${inp("bank_recipient", "Имя получателя")}${inp("bank_iban", "IBAN")}${inp("bank_account", "Номер счёта")}${area("bank_extra", "Дополнительный текст", 3)}</div>
      <div class="card"><h3>👋 Текст приветствия в боте</h3><div class="muted small" style="margin-bottom:8px">{name} заменяется названием бизнеса</div>
        ${area("welcome_uz", 'Приветствие<span class="lang-tag">UZ</span>')}${area("welcome_ru", 'Приветствие<span class="lang-tag">RU</span>')}</div>
      <div class="card"><h3>🌐 Прочее</h3>
        <label class="field"><span>Основной язык</span><select class="input" data-k="primary_language"><option value="uz" ${s.primary_language === "uz" ? "selected" : ""}>O‘zbekcha</option><option value="ru" ${s.primary_language === "ru" ? "selected" : ""}>Русский</option></select></label>
        ${inp("currency", "Валюта")}${inp("low_stock_threshold", "Показывать «🔥 Осталось мало», если остаток ≤", 'inputmode="numeric"')}</div>
      <button class="btn" id="save">💾 Сохранить настройки</button>
    </div></div>`;
    $app.querySelector("#save").onclick = async () => {
      const body = {};
      $app.querySelectorAll("[data-k]").forEach((el) => { body[el.dataset.k] = el.value; });
      $app.querySelectorAll("[data-b]").forEach((el) => { body[el.dataset.b] = el.checked; });
      const btn = $app.querySelector("#save"); btn.disabled = true;
      try { await api("/api/admin/settings", { method: "PUT", body }); haptic("success"); toast("✅ Настройки сохранены"); } catch (e) { fail(e); }
      btn.disabled = false;
    };
    $app.querySelector("#logo").onchange = async (e) => {
      const f = e.target.files[0]; if (!f) return; const fd = new FormData(); fd.append("file", f);
      try { await api("/api/admin/settings/logo", { form: fd }); haptic("success"); toast("✅ Логотип обновлён"); renderSettings(); } catch (x) { fail(x); }
    };
    const ld = $app.querySelector("#logo-del");
    if (ld) ld.onclick = async () => { try { await api("/api/admin/settings/logo", { method: "DELETE" }); renderSettings(); } catch (x) { fail(x); } };
  }

  // ---------------------------------------------------------------- start
  async function start() {
    document.documentElement.dataset.theme = (tg && tg.colorScheme) || "light";
    if (tg) {
      tg.ready(); tg.expand();
      try { if (tg.isVersionAtLeast("6.1")) { tg.setHeaderColor("secondary_bg_color"); tg.setBackgroundColor("secondary_bg_color"); } } catch (e) {}
      try { if (tg.isVersionAtLeast("7.7")) tg.disableVerticalSwipes(); } catch (e) {}
      if (tg.BackButton) tg.BackButton.onClick(back);
      tg.onEvent("themeChanged", () => { document.documentElement.dataset.theme = tg.colorScheme; });
    }
    try {
      const me = await api("/api/me");
      if (!me.is_admin) throw new ApiError(403, { code: "forbidden" });
    } catch (e) {
      $nav.classList.add("hidden");
      $app.innerHTML = `<div class="denied"><div style="font-size:64px">⛔</div><h2>${esc(errText(e))}</h2><p class="muted">Админ-панель доступна только Telegram ID из ADMIN_IDS.</p></div>`;
      return;
    }
    render();
  }
  start();
})();
