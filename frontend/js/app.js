/* BISMILLAH BARAKA — Telegram Mini App (client side).
   Prices, stock and totals are always re-checked by the server; this file only displays them. */
(() => {
  "use strict";
  const tg = window.Telegram && window.Telegram.WebApp;
  const inTG = !!(tg && tg.initData);
  const $app = document.getElementById("app");
  const $nav = document.getElementById("nav");
  const SECTION_ICON = { menu: "🍽", sadaqa: "🤲", events: "🏞" };
  const TABS = ["home", "menu", "sadaqa", "cart", "profile"];

  const S = {
    lang: localStorage.getItem("lang") || "uz",
    boot: null,
    catalogs: {},
    cart: {},
    depth: 0,
    uid: (tg && tg.initDataUnsafe && tg.initDataUnsafe.user && tg.initDataUnsafe.user.id) || "dev",
    receiptFile: null,
    form: null,
  };

  // ---------------------------------------------------------------- helpers
  const t = (k, vars) => {
    let s = (I18N[S.lang] && I18N[S.lang][k]) || I18N.ru[k] || k;
    if (vars) for (const [a, b] of Object.entries(vars)) s = s.split("{" + a + "}").join(b);
    return s;
  };
  const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const cur = () => (S.boot && S.boot.settings.currency) || "SAR";
  const fmt = (n) => {
    const v = Math.round(Number(n || 0) * 100) / 100;
    const s = Number.isInteger(v) ? String(v) : v.toFixed(2);
    return s.replace(/\B(?=(\d{3})+(?!\d))/g, " ") + " " + cur();
  };
  const haptic = (kind = "light") => {
    try {
      if (!tg || !tg.HapticFeedback) return;
      if (["success", "error", "warning"].includes(kind)) tg.HapticFeedback.notificationOccurred(kind);
      else if (kind === "select") tg.HapticFeedback.selectionChanged();
      else tg.HapticFeedback.impactOccurred(kind);
    } catch (e) { /* old clients */ }
  };
  let toastTimer;
  const toast = (msg, isErr) => {
    let el = document.getElementById("toast");
    if (!el) { el = document.createElement("div"); el.id = "toast"; el.className = "toast"; document.body.appendChild(el); }
    el.textContent = msg; el.classList.toggle("err", !!isErr); el.classList.add("show");
    clearTimeout(toastTimer); toastTimer = setTimeout(() => el.classList.remove("show"), 2600);
  };
  const confirmDialog = (msg) => new Promise((resolve) => {
    if (tg && tg.showConfirm && tg.isVersionAtLeast && tg.isVersionAtLeast("6.2")) tg.showConfirm(msg, (ok) => resolve(!!ok));
    else resolve(window.confirm(msg));
  });
  const phImg = (url, icon, cls = "") =>
    url ? `<img src="${esc(url)}" alt="" loading="lazy" class="${cls}" onerror="this.outerHTML='<div class=&quot;ph&quot;><span>${esc(icon || "🍽")}</span></div>'">`
        : `<div class="ph"><span>${esc(icon || "🍽")}</span></div>`;

  class ApiError extends Error { constructor(status, detail) { super((detail && detail.code) || "error"); this.status = status; this.detail = detail || {}; } }
  async function api(path, opts = {}) {
    const headers = { "X-Telegram-Init-Data": (tg && tg.initData) || "" };
    let body = opts.body;
    if (opts.form) body = opts.form;
    else if (body !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(body); }
    const sep = path.includes("?") ? "&" : "?";
    let res;
    try { res = await fetch(`${path}${sep}lang=${S.lang}`, { method: opts.method || (body ? "POST" : "GET"), headers, body }); }
    catch (e) { throw new ApiError(0, { code: "network" }); }
    let data = null;
    try { data = await res.json(); } catch (e) { data = null; }
    if (!res.ok) throw new ApiError(res.status, (data && data.detail) || { code: "error" });
    return data;
  }
  function errText(e) {
    const d = (e && e.detail) || {};
    const name = S.lang === "ru" ? (d.name_ru || d.name_uz) : (d.name_uz || d.name_ru);
    switch (d.code) {
      case "network": return t("err_network");
      case "unauthorized": return t("err_unauth");
      case "store_closed": return t("err_closed");
      case "insufficient_stock": return d.available > 0 ? t("err_stock", { name, n: d.available }) : t("err_stock0", { name });
      case "product_unavailable": return t("err_unavailable");
      case "bad_phone": return t("required_phone");
      case "address_required": return t("required_address");
      case "name_required": return t("required_name");
      case "min_qty": return t("err_min", { name, n: d.min_qty });
      case "max_qty": return t("err_max", { name, n: d.max_qty });
      case "file_too_large": case "bad_image": return t("err_file");
      default: return t("err_generic");
    }
  }

  // ---------------------------------------------------------------- cart (stored on the phone, verified by server)
  const cartKey = () => "cart_v1_" + S.uid;
  const loadCart = () => { try { S.cart = JSON.parse(localStorage.getItem(cartKey()) || "{}") || {}; } catch (e) { S.cart = {}; } };
  const saveCart = () => { localStorage.setItem(cartKey(), JSON.stringify(S.cart)); renderNav(); };
  const cartCount = () => Object.values(S.cart).reduce((a, i) => a + (i.qty || 0), 0);
  const cartQty = (id) => (S.cart[id] ? S.cart[id].qty : 0);
  const limitFor = (p) => Math.max(0, Math.min(p.stock, p.max_qty || Infinity));
  function cartAdd(p, qty) {
    const have = cartQty(p.id);
    const limit = limitFor(p);
    let next = have + qty;
    if (have === 0) next = Math.max(next, p.min_qty || 1);
    if (next > limit) {
      haptic("error");
      toast(limit > 0 ? t("low", { n: p.stock }).replace("🔥 ", "") : t("out"), true);
      return false;
    }
    S.cart[p.id] = { id: p.id, qty: next, name: p.name, price: p.price, image_url: p.image_url, icon: p.icon || SECTION_ICON[p.section],
                     section: p.section, stock: p.stock, min_qty: p.min_qty || 1, max_qty: p.max_qty || null };
    saveCart(); haptic("success"); return true;
  }
  function cartSet(id, qty) {
    const it = S.cart[id]; if (!it) return;
    if (qty <= 0) delete S.cart[id]; else it.qty = qty;
    saveCart();
  }

  // ---------------------------------------------------------------- Telegram buttons
  let mainHandler = null;
  function setMain(text, handler, enabled = true) {
    clearMain();
    if (inTG && tg.MainButton) {
      mainHandler = handler;
      tg.MainButton.setParams({ text, is_active: enabled, is_visible: true, color: getAccent(), text_color: "#ffffff" });
      tg.MainButton.onClick(mainHandler);
    } else {
      const bar = document.createElement("div");
      bar.className = "bottom-bar"; bar.id = "fallback-main";
      bar.innerHTML = `<div class="inner"><button class="btn" ${enabled ? "" : "disabled"}>${esc(text)}</button></div>`;
      bar.querySelector("button").onclick = handler;
      document.body.appendChild(bar);
    }
  }
  function mainProgress(on) {
    if (inTG && tg.MainButton) { on ? tg.MainButton.showProgress(false) : tg.MainButton.hideProgress(); if (on) tg.MainButton.disable(); else tg.MainButton.enable(); }
    const b = document.querySelector("#fallback-main button");
    if (b) { b.disabled = on; if (on) b.innerHTML = `<span class="spinner"></span>`; }
  }
  function clearMain() {
    if (inTG && tg.MainButton) { if (mainHandler) tg.MainButton.offClick(mainHandler); mainHandler = null; tg.MainButton.hideProgress(); tg.MainButton.hide(); }
    const fb = document.getElementById("fallback-main"); if (fb) fb.remove();
  }
  const getAccent = () => getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#0e7c5a";
  function updateBack(route) {
    if (!tg || !tg.BackButton) return;
    if (route.name === "home") tg.BackButton.hide(); else tg.BackButton.show();
  }
  function goBack() {
    haptic("light");
    if (S.depth > 0) history.back();
    else navigate("#/", true);
  }

  // ---------------------------------------------------------------- router
  function parse() {
    const h = (location.hash || "#/").replace(/^#\/?/, "");
    const [name, arg] = h.split("/");
    return { name: name || "home", arg };
  }
  function navigate(hash, replace = false) {
    if (replace) history.replaceState(null, "", hash); else { history.pushState(null, "", hash); S.depth++; }
    render();
  }
  window.addEventListener("popstate", () => { S.depth = Math.max(0, S.depth - 1); render(); });
  document.addEventListener("click", (e) => {
    const a = e.target.closest("[data-go]");
    if (a) { e.preventDefault(); haptic("light"); navigate(a.getAttribute("data-go")); }
  });

  function render() {
    clearMain();
    const r = parse();
    updateBack(r);
    window.scrollTo(0, 0);
    const noNav = ["product", "checkout"].includes(r.name);
    $app.classList.toggle("no-nav", noNav);
    $nav.classList.toggle("hidden", noNav);
    renderNav(r);
    const screens = { home: renderHome, menu: () => renderSection("menu"), sadaqa: () => renderSection("sadaqa"),
      events: () => renderSection("events"), product: () => renderProduct(r.arg), cart: renderCart, checkout: renderCheckout,
      success: () => renderOrder(r.arg, true), order: () => renderOrder(r.arg, false), orders: renderOrders, profile: renderProfile };
    (screens[r.name] || renderHome)();
  }

  function renderNav(r) {
    r = r || parse();
    const active = r.name === "product" ? (S.lastSection || "menu") : (r.name === "events" ? "home" :
      (["checkout"].includes(r.name) ? "cart" : (["orders", "order", "success"].includes(r.name) ? "profile" : r.name)));
    const items = [["home", "🏠", t("home"), "#/"], ["menu", "🍽", t("menu"), "#/menu"], ["sadaqa", "🤲", t("sadaqa"), "#/sadaqa"],
      ["cart", "🛒", t("cart"), "#/cart"], ["profile", "👤", t("profile"), "#/profile"]];
    const n = cartCount();
    $nav.innerHTML = `<div class="inner">${items.map(([k, i, l, h]) =>
      `<button class="${active === k ? "on" : ""}" data-nav="${h}"><span class="i">${i}</span>${esc(l)}${k === "cart" && n ? `<span class="cnt">${n > 99 ? "99+" : n}</span>` : ""}</button>`).join("")}</div>`;
    $nav.querySelectorAll("[data-nav]").forEach((b) => b.onclick = () => {
      haptic("select");
      const target = b.getAttribute("data-nav");
      if (target === "#/") { S.depth = 0; history.replaceState(null, "", "#/"); render(); }
      else if (location.hash !== target) navigate(target);
    });
  }

  function topbar(title, withLang = false) {
    return `<div class="topbar"><h1>${esc(title)}</h1>${withLang ? langSwitch() : ""}</div>`;
  }
  const langSwitch = () => `<div class="lang-switch"><button data-lang="uz" class="${S.lang === "uz" ? "on" : ""}">UZ</button><button data-lang="ru" class="${S.lang === "ru" ? "on" : ""}">RU</button></div>`;
  function bindLang(root) {
    root.querySelectorAll("[data-lang]").forEach((b) => b.onclick = () => setLang(b.getAttribute("data-lang")));
  }
  async function setLang(lang) {
    if (lang === S.lang) return;
    haptic("select");
    S.lang = lang; localStorage.setItem("lang", lang); S.catalogs = {};
    document.documentElement.lang = lang;
    api("/api/me", { method: "PATCH", body: { language: lang } }).catch(() => {});
    try { S.boot = await api("/api/bootstrap"); } catch (e) { /* keep old */ }
    render();
  }

  // ---------------------------------------------------------------- HOME
  function renderHome() {
    const b = S.boot, st = b.settings;
    const logo = st.logo_url ? `<img class="logo" src="${esc(st.logo_url)}" alt="">` : `<img class="logo" src="/static/logo.svg" alt="">`;
    const hours = `${esc(st.open_time)} – ${esc(st.close_time)}`;
    const pill = b.is_open ? `<div class="status-pill open"><i></i>${t("open_now")} · ${hours}</div>`
      : `<div class="status-pill closed"><i></i>${t("closed_now")}${st.store_open ? " · " + hours : ""}</div>`;
    const card = (key, cls) => `<button class="section-card ${cls}" data-go="#/${key}"><span class="emoji">${SECTION_ICON[key]}</span>
      <span><div class="title">${t(key + "_big")}</div><div class="sub">${t(key + "_sub")}</div></span><span class="arrow">›</span></button>`;
    const rows = [];
    if (st.phone) rows.push(`<a class="info-row" href="tel:${esc(st.phone.replace(/\s/g, ""))}"><span class="ic">📞</span><span class="val"><small>${t("phone")}</small>${esc(st.phone)}</span></a>`);
    if (st.whatsapp) rows.push(`<a class="info-row" href="https://wa.me/${esc(st.whatsapp.replace(/\D/g, ""))}" data-ext><span class="ic">💬</span><span class="val"><small>${t("whatsapp")}</small>${esc(st.whatsapp)}</span></a>`);
    if (st.instagram) rows.push(`<a class="info-row" href="https://instagram.com/${esc(st.instagram.replace(/^@/, "").replace(/^https?:\/\/(www\.)?instagram\.com\//, ""))}" data-ext><span class="ic">📷</span><span class="val"><small>${t("instagram")}</small>${esc(st.instagram)}</span></a>`);
    if (st.address) rows.push(`<div class="info-row"><span class="ic">📍</span><span class="val"><small>${t("address")}</small>${esc(st.address)}</span></div>`);
    rows.push(`<div class="info-row"><span class="ic">🕒</span><span class="val"><small>${t("hours")}</small>${st.work_hours_text ? esc(st.work_hours_text) : hours}</span></div>`);
    $app.innerHTML = `<div class="screen">
      <div class="topbar"><h1></h1>${langSwitch()}</div>
      <div class="hero">${logo}<h2>${esc(st.business_name)}</h2>${st.description ? `<p>${esc(st.description)}</p>` : ""}${pill}</div>
      <div class="sections">${card("menu", "sc-menu")}${card("sadaqa", "sc-sadaqa")}${card("events", "sc-events")}</div>
      <div class="info-card">${rows.join("")}</div>
    </div>`;
    bindLang($app); bindExternal($app);
  }
  function bindExternal(root) {
    root.querySelectorAll("a[data-ext]").forEach((a) => a.onclick = (e) => {
      if (tg && tg.openLink) { e.preventDefault(); tg.openLink(a.href); }
    });
  }

  // ---------------------------------------------------------------- SECTION (catalog)
  function stockLabel(p) {
    if (p.stock <= 0) return `<span class="stock out">${t("out")}</span>`;
    if (p.low_stock) return `<span class="stock low">${t("low", { n: p.stock })}</span>`;
    return `<span class="stock ok">${t("left", { n: p.stock })}</span>`;
  }
  function productCard(p, cats) {
    const cat = cats.find((c) => c.id === p.category_id);
    const isSet = cat && cat.slug === "set";
    const q = cartQty(p.id);
    return `<div class="pcard ${isSet ? "featured" : ""} ${p.stock <= 0 ? "soldout" : ""}" data-go="#/product/${p.id}" role="button">
      <div class="pimg">${phImg(p.image_url, p.icon)}${isSet ? `<span class="badge set">⭐ ${t("our_set")}</span>` : ""}${q ? `<span class="badge">🛒 ${q}</span>` : ""}</div>
      <div class="pbody"><div class="pname">${esc(p.name)}</div>
        ${p.description ? `<div class="pdesc">${esc(p.description)}</div>` : ""}
        ${stockLabel(p)}
        <div class="prow"><span class="price">${esc(fmt(p.price))}</span>
          <button class="addbtn" data-add="${p.id}" ${p.stock <= 0 ? "disabled" : ""} aria-label="+">${p.stock <= 0 ? "×" : "+"}</button></div>
      </div></div>`;
  }
  async function renderSection(section) {
    S.lastSection = section;
    const title = t(section);
    const draw = (data) => {
      const cats = data.categories;
      const prods = data.products;
      const active = S["cat_" + section] || "all";
      const usedCats = cats.filter((c) => prods.some((p) => p.category_id === c.id));
      const noCat = prods.filter((p) => !p.category_id || !cats.some((c) => c.id === p.category_id));
      let body = "";
      if (!prods.length) {
        body = `<div class="empty"><div class="big">${SECTION_ICON[section]}</div><h3>${t("empty_section")}</h3><div>${t("empty_section_sub")}</div></div>`;
      } else {
        const groups = usedCats.map((c) => ({ c, items: prods.filter((p) => p.category_id === c.id) }));
        if (noCat.length) groups.push({ c: { id: 0, name: t("other"), icon: SECTION_ICON[section] }, items: noCat });
        const shown = active === "all" ? groups : groups.filter((g) => String(g.c.id) === String(active));
        body = shown.map((g) => `<div class="cat-title">${esc(g.c.icon || "")} ${esc(g.c.name)}</div>
          <div class="grid">${g.items.map((p) => productCard(p, cats)).join("")}</div>`).join("");
      }
      const chips = usedCats.length > 1 || noCat.length ? `<div class="chips"><button class="chip ${active === "all" ? "on" : ""}" data-cat="all">${t("all")}</button>${
        usedCats.map((c) => `<button class="chip ${String(active) === String(c.id) ? "on" : ""}" data-cat="${c.id}">${esc(c.icon)} ${esc(c.name)}</button>`).join("")}${
        noCat.length && usedCats.length ? `<button class="chip ${active === "0" ? "on" : ""}" data-cat="0">${t("other")}</button>` : ""}</div>` : "";
      const closed = !S.boot.is_open ? `<div class="page-pad"><div class="notice ${S.boot.can_order ? "warn" : "err"}">${S.boot.can_order ? t("closed_but_orders") : t("closed_no_orders")}</div></div>` : "";
      $app.innerHTML = `<div class="screen">${topbar(SECTION_ICON[section] + " " + title, true)}${chips}${closed}${body}</div>`;
      bindLang($app);
      $app.querySelectorAll("[data-cat]").forEach((b) => b.onclick = () => { haptic("select"); S["cat_" + section] = b.getAttribute("data-cat"); draw(data); });
      $app.querySelectorAll("[data-add]").forEach((b) => b.onclick = (e) => {
        e.stopPropagation();
        const p = prods.find((x) => String(x.id) === b.getAttribute("data-add"));
        if (p && cartAdd(p, 1)) { toast(t("added")); draw(data); }
      });
    };
    if (S.catalogs[section]) draw(S.catalogs[section]);
    else $app.innerHTML = `<div class="screen">${topbar(SECTION_ICON[section] + " " + title, true)}<div class="grid" style="margin-top:8px">${
      Array(6).fill('<div class="sk sk-card"></div>').join("")}</div></div>`;
    try {
      const data = await api(`/api/catalog/${section}`);
      S.catalogs[section] = data;
      for (const p of data.products) if (S.cart[p.id]) Object.assign(S.cart[p.id], { stock: p.stock, price: p.price, name: p.name, image_url: p.image_url });
      if (parse().name === section) draw(data);
    } catch (e) { if (!S.catalogs[section]) $app.innerHTML = errorScreen(e); }
  }
  const errorScreen = (e) => `<div class="empty"><div class="big">⚠️</div><h3>${esc(errText(e))}</h3><button class="btn" onclick="location.reload()">↻</button></div>`;

  // ---------------------------------------------------------------- PRODUCT
  async function renderProduct(id) {
    $app.innerHTML = `<div class="screen"><div class="pd-img sk" style="border-radius:0"></div><div class="pd-body">
      <div class="sk" style="height:28px;width:70%"></div><div class="sk mt" style="height:22px;width:40%"></div><div class="sk mt" style="height:90px"></div></div></div>`;
    let p;
    try { p = await api(`/api/products/${encodeURIComponent(id)}`); } catch (e) { $app.innerHTML = errorScreen(e); return; }
    S.lastSection = p.section;
    let qty = 0;
    const draw = () => {
      const inCart = cartQty(p.id);
      const remaining = Math.max(0, limitFor(p) - inCart);
      const minFirst = inCart ? 1 : (p.min_qty || 1);
      if (!qty) qty = Math.min(minFirst, remaining) || 0;
      qty = Math.min(qty, remaining);
      const stockCls = p.stock <= 0 ? "out" : (p.low_stock ? "low" : "ok");
      const stockTxt = p.stock <= 0 ? t("out") : (p.low_stock ? t("low", { n: p.stock }) : t("left", { n: p.stock }));
      const limits = [p.min_qty > 1 ? t("min_qty", { n: p.min_qty }) : "", p.max_qty ? t("max_qty", { n: p.max_qty }) : ""].filter(Boolean).join(" · ");
      $app.innerHTML = `<div class="screen">
        <div class="pd-img">${phImg(p.image_url, p.icon)}</div>
        <div class="pd-body">
          <h2>${esc(p.name)}</h2>
          <div class="pd-meta"><div class="pd-price">${esc(fmt(p.price))}</div><span class="pd-stock ${stockCls}">${stockTxt}</span></div>
          ${inCart ? `<div class="notice ok">🛒 ${t("in_cart", { n: inCart })}</div>` : ""}
          <div class="h3">${t("description")}</div>
          <p class="pd-desc">${p.description ? esc(p.description) : `<span class="muted">${t("no_description")}</span>`}</p>
          ${limits ? `<div class="pd-limits">ℹ️ ${esc(limits)}</div>` : ""}
        </div>
        <div class="bottom-bar"><div class="inner">
          <div class="stepper"><button id="minus" ${qty <= minFirst ? "disabled" : ""}>−</button><span class="q">${qty}</span><button id="plus" ${qty >= remaining ? "disabled" : ""}>+</button></div>
          <button class="btn" id="add" ${p.stock <= 0 || remaining <= 0 || qty <= 0 ? "disabled" : ""}>${p.stock <= 0 ? t("out") : `${t("add_to_cart")}${qty ? " · " + esc(fmt(p.price * qty)) : ""}`}</button>
        </div></div></div>`;
      $app.querySelector("#minus").onclick = () => { if (qty > minFirst) { qty--; haptic("select"); draw(); } };
      $app.querySelector("#plus").onclick = () => { if (qty < remaining) { qty++; haptic("select"); draw(); } else haptic("error"); };
      $app.querySelector("#add").onclick = () => { if (cartAdd(p, qty)) { toast(t("added")); qty = 0; draw(); } };
    };
    draw();
  }

  // ---------------------------------------------------------------- CART
  async function syncCart() {
    const items = Object.values(S.cart).map((i) => ({ product_id: i.id, quantity: i.qty }));
    if (!items.length) return { changed: false, total: 0 };
    const res = await api("/api/cart/validate", { body: { items } });
    let changed = false;
    for (const it of res.items) {
      const c = S.cart[it.product_id]; if (!c) continue;
      if (!it.available) { delete S.cart[it.product_id]; changed = true; continue; }
      if (it.quantity !== c.qty || it.price !== c.price) changed = true;
      Object.assign(c, { qty: it.quantity, price: it.price, stock: it.stock, name: it.name, image_url: it.image_url, min_qty: it.min_qty, max_qty: it.max_qty, icon: it.icon || c.icon });
    }
    saveCart();
    return { changed, total: res.total };
  }
  const cartTotal = () => Object.values(S.cart).reduce((a, i) => a + i.price * i.qty, 0);

  async function renderCart(skipSync) {
    const draw = (notice) => {
      const items = Object.values(S.cart);
      if (!items.length) {
        $app.innerHTML = `<div class="screen">${topbar("🛒 " + t("cart"))}<div class="empty"><div class="big">🛒</div><h3>${t("cart_empty")}</h3><div>${t("cart_empty_sub")}</div>
          <button class="btn" data-go="#/menu">${t("go_menu")}</button></div></div>`;
        return;
      }
      $app.innerHTML = `<div class="screen">${topbar("🛒 " + t("cart"))}<div class="page-pad">
        ${notice ? `<div class="notice warn">${esc(notice)}</div>` : ""}
        <div class="card">${items.map((i) => `<div class="citem">
            <div class="cthumb">${phImg(i.image_url, i.icon)}</div>
            <div class="cinfo"><div class="n">${esc(i.name)}</div><div class="s">${esc(fmt(i.price))} × ${i.qty}</div>
              ${i.qty >= i.stock ? `<div class="w">${t("low", { n: i.stock })}</div>` : ""}
              <div class="stepper sm mt"><button data-dec="${i.id}">−</button><span class="q">${i.qty}</span><button data-inc="${i.id}" ${i.qty >= Math.min(i.stock, i.max_qty || Infinity) ? "disabled" : ""}>+</button></div></div>
            <div class="cright"><span class="csub">${esc(fmt(i.price * i.qty))}</span><button class="rm" data-rm="${i.id}">🗑 ${t("remove")}</button></div>
          </div>`).join("")}
          <div class="total-row"><span>${t("total")}</span><span>${esc(fmt(cartTotal()))}</span></div>
        </div>
        ${!S.boot.can_order ? `<div class="notice err">${t("closed_no_orders")}</div>` : (!S.boot.is_open ? `<div class="notice warn">${t("closed_but_orders")}</div>` : "")}
        <button class="btn ghost sm" id="clear">${t("clear_cart")}</button>
      </div></div>`;
      $app.querySelectorAll("[data-inc]").forEach((b) => b.onclick = () => {
        const i = S.cart[b.getAttribute("data-inc")];
        if (i.qty < Math.min(i.stock, i.max_qty || Infinity)) { cartSet(i.id, i.qty + 1); haptic("select"); draw(); } else haptic("error");
      });
      $app.querySelectorAll("[data-dec]").forEach((b) => b.onclick = async () => {
        const i = S.cart[b.getAttribute("data-dec")];
        if (i.qty - 1 < (i.min_qty || 1)) { if (await confirmDialog(t("confirm_remove"))) { cartSet(i.id, 0); draw(); } }
        else { cartSet(i.id, i.qty - 1); haptic("select"); draw(); }
      });
      $app.querySelectorAll("[data-rm]").forEach((b) => b.onclick = async () => {
        if (await confirmDialog(t("confirm_remove"))) { cartSet(b.getAttribute("data-rm"), 0); haptic("warning"); draw(); }
      });
      $app.querySelector("#clear").onclick = async () => { if (await confirmDialog(t("confirm_clear"))) { S.cart = {}; saveCart(); draw(); } };
      setMain(`${t("checkout")} · ${fmt(cartTotal())}`, () => { haptic("medium"); navigate("#/checkout"); }, S.boot.can_order);
    };
    draw();
    if (!skipSync && Object.keys(S.cart).length) {
      try { const r = await syncCart(); if (parse().name === "cart") draw(r.changed ? t("cart_changed") : ""); }
      catch (e) { toast(errText(e), true); }
    }
  }

  // ---------------------------------------------------------------- CHECKOUT
  function bankBlock(amountText) {
    const b = S.boot.bank;
    const line = (label, val, copy) => val ? `<div class="line"><span>${label}</span><span>${esc(val)}${copy ? ` <button class="copy" data-copy="${esc(val)}">${t("copy")}</button>` : ""}</span></div>` : "";
    return `<div class="bank"><b>🏦 ${t("bank_details")}</b>
      ${amountText ? `<div class="small mt">${esc(t("transfer_hint", { sum: amountText }))}</div>` : ""}
      ${line(t("bank_name"), b.name)}${line(t("recipient"), b.recipient, true)}${line(t("iban"), b.iban, true)}${line(t("account"), b.account, true)}
      ${b.extra ? `<div class="small mt" style="white-space:pre-wrap">${esc(b.extra)}</div>` : ""}</div>`;
  }
  function bindCopy(root) {
    root.querySelectorAll("[data-copy]").forEach((b) => b.onclick = async () => {
      const v = b.getAttribute("data-copy");
      try { await navigator.clipboard.writeText(v); } catch (e) {
        const ta = document.createElement("textarea"); ta.value = v; document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove();
      }
      haptic("success"); toast(t("copied"));
    });
  }
  function requestPhone(onPhone) {
    if (!(tg && tg.requestContact && tg.isVersionAtLeast && tg.isVersionAtLeast("6.9"))) return false;
    tg.requestContact((ok, res) => {
      if (!ok) return;
      const phone = res && res.responseUnsafe && res.responseUnsafe.contact && res.responseUnsafe.contact.phone_number;
      if (phone) onPhone(phone.startsWith("+") ? phone : "+" + phone);
      setTimeout(async () => { try { const me = await api("/api/me"); if (me.phone) { S.boot.user = me; onPhone(me.phone); } } catch (e) {} }, 1800);
    });
    return true;
  }

  async function renderCheckout() {
    if (!Object.keys(S.cart).length) { navigate("#/cart", true); return; }
    const st = S.boot.settings, u = S.boot.user;
    const f = S.form || (S.form = {
      name: u.full_name || "", phone: u.phone || "", delivery: st.delivery_enabled ? "delivery" : "pickup",
      address: "", comment: "", pay: "cash",
    });
    if (!st.delivery_enabled && f.delivery === "delivery") f.delivery = "pickup";
    if (!st.pickup_enabled && f.delivery === "pickup" && st.delivery_enabled) f.delivery = "delivery";
    const draw = () => {
      const items = Object.values(S.cart);
      const total = cartTotal();
      const canTG = !!(tg && tg.requestContact && tg.isVersionAtLeast && tg.isVersionAtLeast("6.9"));
      $app.innerHTML = `<div class="screen">${topbar(t("checkout_title"))}<div class="page-pad">
        <div class="card"><h3>🧾 ${t("items")}</h3>
          ${items.map((i) => `<div class="line"><span>${esc(i.name)} × ${i.qty}</span><span>${esc(fmt(i.price * i.qty))}</span></div>`).join("")}
          <div class="total-row"><span>${t("total")}</span><span>${esc(fmt(total))}</span></div></div>
        <div class="card"><h3>👤 ${t("customer")}</h3>
          <label class="field"><span>${t("your_name")}</span><input class="input" id="f-name" maxlength="80" autocomplete="name" value="${esc(f.name)}"></label>
          <label class="field"><span>${t("your_phone")}</span><input class="input" id="f-phone" type="tel" inputmode="tel" maxlength="24" autocomplete="tel" placeholder="+966 5X XXX XXXX" value="${esc(f.phone)}"></label>
          ${canTG ? `<button class="btn secondary sm" id="f-share">${t("share_phone")}</button>` : ""}
        </div>
        <div class="card"><h3>🚗 ${t("delivery_type")}</h3>
          <div class="opts two">
            ${st.delivery_enabled ? `<button class="opt ${f.delivery === "delivery" ? "on" : ""}" data-del="delivery"><span class="oi">🚚</span>${t("delivery")}</button>` : ""}
            ${st.pickup_enabled ? `<button class="opt ${f.delivery === "pickup" ? "on" : ""}" data-del="pickup"><span class="oi">🏃</span>${t("pickup")}</button>` : ""}
          </div>
          ${f.delivery === "delivery" ? `<label class="field mt"><span>${t("delivery_address")}</span><textarea class="input" id="f-address" maxlength="500" placeholder="${esc(t("address_ph"))}">${esc(f.address)}</textarea></label>`
            : (st.address ? `<div class="line mt"><span>${t("pickup_from")}</span><span>${esc(st.address)}</span></div>` : "")}
          <label class="field ${f.delivery === "delivery" ? "" : "mt"}"><span>${t("comment")}</span><textarea class="input" id="f-comment" maxlength="1000" placeholder="${esc(t("comment_ph"))}">${esc(f.comment)}</textarea></label>
        </div>
        <div class="card"><h3>💳 ${t("payment")}</h3>
          <div class="opts">
            <button class="opt ${f.pay === "cash" ? "on" : ""}" data-pay="cash"><span class="oi">💵</span>${t("cash")}</button>
            <button class="opt ${f.pay === "transfer" ? "on" : ""}" data-pay="transfer"><span class="oi">🏦</span>${t("transfer")}</button>
          </div>
          ${f.pay === "transfer" ? `${bankBlock(fmt(total))}
            <label class="upload"><input type="file" accept="image/*" id="f-receipt">${S.receiptFile ? `<img src="${URL.createObjectURL(S.receiptFile)}" alt="">${t("receipt_selected")} · ${t("change")}` : t("attach_receipt")}</label>
            <div class="small muted mt">${t("receipt_later")}</div>` : ""}
        </div>
        ${!S.boot.can_order ? `<div class="notice err">${t("closed_no_orders")}</div>` : ""}
        <div id="f-error"></div>
      </div></div>`;
      const keep = () => {
        const g = (id) => { const el = $app.querySelector(id); return el ? el.value : undefined; };
        f.name = g("#f-name") ?? f.name; f.phone = g("#f-phone") ?? f.phone;
        if (g("#f-address") !== undefined) f.address = g("#f-address");
        f.comment = g("#f-comment") ?? f.comment;
      };
      $app.querySelectorAll("input,textarea").forEach((el) => el.addEventListener("input", () => { keep(); el.classList.remove("err"); }));
      $app.querySelectorAll("[data-del]").forEach((b) => b.onclick = () => { keep(); f.delivery = b.getAttribute("data-del"); haptic("select"); draw(); });
      $app.querySelectorAll("[data-pay]").forEach((b) => b.onclick = () => { keep(); f.pay = b.getAttribute("data-pay"); haptic("select"); draw(); });
      const share = $app.querySelector("#f-share");
      if (share) share.onclick = () => { keep(); requestPhone((ph) => { f.phone = ph; const el = $app.querySelector("#f-phone"); if (el) el.value = ph; }); };
      const rf = $app.querySelector("#f-receipt");
      if (rf) rf.onchange = () => { keep(); S.receiptFile = rf.files[0] || null; draw(); };
      bindCopy($app);
      setMain(`${t("place_order")} · ${fmt(total)}`, submit, S.boot.can_order);

      async function submit() {
        keep();
        const errBox = $app.querySelector("#f-error");
        const bad = (id, msg) => { const el = $app.querySelector(id); if (el) { el.classList.add("err"); el.scrollIntoView({ behavior: "smooth", block: "center" }); } haptic("error"); toast(msg, true); };
        if (!f.name.trim()) return bad("#f-name", t("required_name"));
        if (f.phone.replace(/\D/g, "").length < 7) return bad("#f-phone", t("required_phone"));
        if (f.delivery === "delivery" && f.address.trim().length < 3) return bad("#f-address", t("required_address"));
        mainProgress(true);
        try {
          const order = await api("/api/orders", { body: {
            items: Object.values(S.cart).map((i) => ({ product_id: i.id, quantity: i.qty })),
            customer_name: f.name.trim(), phone: f.phone.trim(), delivery_type: f.delivery,
            address: f.delivery === "delivery" ? f.address.trim() : "", comment: f.comment.trim(),
            payment_method: f.pay, language: S.lang } });
          S.cart = {}; saveCart(); S.catalogs = {};
          S.boot.user.full_name = f.name.trim(); S.boot.user.phone = f.phone.trim();
          if (f.pay === "transfer" && S.receiptFile) {
            const fd = new FormData(); fd.append("file", S.receiptFile);
            try { await api(`/api/orders/${order.id}/receipt`, { form: fd }); } catch (e) { toast(errText(e), true); }
          }
          S.receiptFile = null; S.form = null;
          haptic("success");
          clearMain();
          S.depth = 0; history.replaceState(null, "", "#/"); history.pushState(null, "", `#/success/${order.id}`); S.depth = 1;
          render();
        } catch (e) {
          mainProgress(false);
          haptic("error");
          const msg = errText(e);
          errBox.innerHTML = `<div class="notice err">${esc(msg)}</div>`;
          toast(msg, true);
          if (["insufficient_stock", "product_unavailable", "min_qty", "max_qty"].includes(e.detail.code)) {
            try { await syncCart(); } catch (x) {}
            if (!Object.keys(S.cart).length) { navigate("#/cart", true); return; }
            draw(); $app.querySelector("#f-error").innerHTML = `<div class="notice err">${esc(msg)}</div>`;
          }
        }
      }
    };
    draw();
    try { const r = await syncCart(); if (r.changed && parse().name === "checkout") { draw(); toast(t("cart_changed")); } } catch (e) {}
  }

  // ---------------------------------------------------------------- ORDER details / success
  async function renderOrder(id, isSuccess) {
    $app.innerHTML = `<div class="screen">${topbar(t("order"))}<div class="center"><div class="spinner dark"></div></div></div>`;
    let o;
    try { o = await api(`/api/orders/${encodeURIComponent(id)}`); } catch (e) { $app.innerHTML = errorScreen(e); return; }
    const draw = () => {
      const needReceipt = o.payment_method === "transfer" && ["awaiting_payment", "payment_review"].includes(o.status);
      const head = isSuccess ? `<div class="success"><div class="big">✅</div><h2>${t("order_created")}</h2><p>${t("order_number", { n: o.number })}</p><p class="mt">${t("thanks")}</p></div>` : "";
      $app.innerHTML = `<div class="screen">${topbar(t("order_number", { n: o.number }))}<div class="page-pad">${head}
        <div class="card">
          <div class="line"><span>${t("status")}</span><span class="st ${o.status}">${esc(o.status_text)}</span></div>
          <div class="line"><span>${t("date")}</span><span>${esc(o.created_local)}</span></div>
          <div class="line"><span>${t("payment")}</span><span>${esc(o.payment_text)}</span></div>
          <div class="line"><span>${t("delivery_type")}</span><span>${o.delivery_type === "delivery" ? "🚚 " + t("delivery") : "🏃 " + t("pickup")}</span></div>
          ${o.address ? `<div class="line"><span>${t("address")}</span><span>${esc(o.address)}</span></div>` : ""}
          ${o.comment ? `<div class="line"><span>${t("comment")}</span><span>${esc(o.comment)}</span></div>` : ""}
        </div>
        <div class="card"><h3>🧾 ${t("items")}</h3>
          ${o.items.map((i) => `<div class="line"><span>${esc(i.name)} × ${i.quantity}</span><span>${esc(i.subtotal_text)}</span></div>`).join("")}
          <div class="total-row"><span>${t("total")}</span><span>${esc(o.total_text)}</span></div></div>
        ${needReceipt ? `<div class="card">
            ${o.payment_status === "rejected" ? `<div class="notice err">${t("receipt_rejected")}</div>` : ""}
            ${o.status === "payment_review" ? `<div class="notice ok">${t("receipt_sent")}</div>` : ""}
            ${bankBlock(o.total_text)}
            ${o.receipt_url && o.payment_status !== "rejected" ? `<img src="${esc(o.receipt_url)}" alt="" style="max-height:220px;border-radius:12px;margin-top:12px">` : ""}
            <label class="upload"><input type="file" accept="image/*" id="receipt">${t("send_receipt")}</label>
          </div>` : ""}
        <button class="btn secondary" id="repeat">${t("repeat")}</button>
        ${isSuccess ? `<button class="btn ghost mt" data-go="#/orders">${t("my_orders")}</button>` : ""}
      </div></div>`;
      bindCopy($app);
      const inp = $app.querySelector("#receipt");
      if (inp) inp.onchange = async () => {
        const file = inp.files[0]; if (!file) return;
        const label = inp.parentElement; label.innerHTML = `<span class="spinner dark"></span> ${t("sending")}`;
        const fd = new FormData(); fd.append("file", file);
        try { o = await api(`/api/orders/${o.id}/receipt`, { form: fd }); haptic("success"); toast(t("receipt_sent")); }
        catch (e) { haptic("error"); toast(errText(e), true); }
        draw();
      };
      $app.querySelector("#repeat").onclick = () => repeatOrder(o);
    };
    draw();
  }
  async function repeatOrder(o) {
    haptic("medium");
    const items = o.items.filter((i) => i.product_id).map((i) => ({ product_id: i.product_id, quantity: i.quantity + cartQty(i.product_id) }));
    if (!items.length) { toast(t("repeat_none"), true); return; }
    try {
      const res = await api("/api/cart/validate", { body: { items } });
      let added = 0;
      for (const it of res.items) {
        if (!it.available) continue;
        S.cart[it.product_id] = { id: it.product_id, qty: it.quantity, name: it.name, price: it.price, image_url: it.image_url,
          icon: it.icon || SECTION_ICON[it.section], section: it.section, stock: it.stock, min_qty: it.min_qty, max_qty: it.max_qty };
        added++;
      }
      saveCart();
      if (!added) { toast(t("repeat_none"), true); return; }
      toast(t("repeated")); navigate("#/cart");
    } catch (e) { toast(errText(e), true); }
  }

  // ---------------------------------------------------------------- ORDERS list / PROFILE
  const orderCard = (o) => `<button class="card order-card" data-go="#/order/${o.id}">
      <div class="top"><div><div class="num">${t("order_number", { n: o.number })}</div><div class="date">${esc(o.created_local)}</div></div><span class="st ${o.status}">${esc(o.status_text)}</span></div>
      <div class="items">${esc(o.items.map((i) => `${i.name} × ${i.quantity}`).join(", "))}</div>
      <div class="bottom"><span class="muted small">${esc(o.payment_text)}</span><b>${esc(o.total_text)}</b></div></button>`;

  async function renderOrders() {
    $app.innerHTML = `<div class="screen">${topbar("📦 " + t("my_orders"))}<div class="page-pad">${Array(3).fill('<div class="sk" style="height:120px;margin-bottom:12px"></div>').join("")}</div></div>`;
    try {
      const list = await api("/api/orders");
      $app.innerHTML = `<div class="screen">${topbar("📦 " + t("my_orders"))}<div class="page-pad">${list.length ? list.map(orderCard).join("") :
        `<div class="empty"><div class="big">📦</div><h3>${t("no_orders")}</h3><button class="btn" data-go="#/menu">${t("go_menu")}</button></div>`}</div></div>`;
    } catch (e) { $app.innerHTML = errorScreen(e); }
  }

  async function renderProfile() {
    const u = S.boot.user;
    const initials = (u.full_name || u.first_name || "?").trim().slice(0, 1).toUpperCase();
    $app.innerHTML = `<div class="screen">${topbar("👤 " + t("profile"))}<div class="page-pad">
      <div class="card"><div class="profile-head"><div class="avatar">${esc(initials)}</div>
        <div><div style="font-weight:800;font-size:18px">${esc(u.full_name || u.first_name || "")}</div>
        <div class="muted small">${u.username ? "@" + esc(u.username) : "ID " + esc(u.telegram_id)}</div>
        <div class="small">${u.phone ? "📞 " + esc(u.phone) : ""}</div></div></div></div>
      <div class="card"><h3>✏️ ${t("edit")}</h3>
        <label class="field"><span>${t("name")}</span><input class="input" id="p-name" maxlength="80" value="${esc(u.full_name || "")}"></label>
        <label class="field"><span>${t("phone")}</span><input class="input" id="p-phone" type="tel" inputmode="tel" maxlength="24" placeholder="+966 5X XXX XXXX" value="${esc(u.phone || "")}"></label>
        <div class="row">${tg && tg.requestContact && tg.isVersionAtLeast && tg.isVersionAtLeast("6.9") ? `<button class="btn secondary sm" id="p-share">📱</button>` : ""}<button class="btn sm" id="p-save">${t("save")}</button></div>
      </div>
      <div class="card"><h3>🌐 ${t("language")}</h3><div class="opts two">
        <button class="opt ${S.lang === "uz" ? "on" : ""}" data-lang="uz"><span class="oi">🇺🇿</span>O‘zbekcha</button>
        <button class="opt ${S.lang === "ru" ? "on" : ""}" data-lang="ru"><span class="oi">🇷🇺</span>Русский</button></div></div>
      <div class="cat-title" style="margin:18px 0 10px">📦 ${t("my_orders")}</div>
      <div id="p-orders">${Array(2).fill('<div class="sk" style="height:110px;margin-bottom:12px"></div>').join("")}</div>
    </div></div>`;
    bindLang($app);
    const share = $app.querySelector("#p-share");
    if (share) share.onclick = () => requestPhone((ph) => { $app.querySelector("#p-phone").value = ph; });
    $app.querySelector("#p-save").onclick = async () => {
      try {
        S.boot.user = await api("/api/me", { method: "PATCH", body: { full_name: $app.querySelector("#p-name").value, phone: $app.querySelector("#p-phone").value } });
        haptic("success"); toast(t("saved")); renderProfile();
      } catch (e) { haptic("error"); toast(errText(e), true); }
    };
    try {
      const list = await api("/api/orders");
      const box = $app.querySelector("#p-orders"); if (!box) return;
      box.innerHTML = list.length ? list.slice(0, 20).map(orderCard).join("") : `<div class="card muted" style="text-align:center">${t("no_orders")}</div>`;
    } catch (e) { const box = $app.querySelector("#p-orders"); if (box) box.innerHTML = `<div class="notice err">${esc(errText(e))}</div>`; }
  }

  // ---------------------------------------------------------------- start
  function applyTheme() {
    document.documentElement.dataset.theme = (tg && tg.colorScheme) || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    if (tg && tg.isVersionAtLeast && tg.isVersionAtLeast("6.1")) {
      try { tg.setHeaderColor("secondary_bg_color"); tg.setBackgroundColor("secondary_bg_color"); } catch (e) {}
    }
  }
  async function start() {
    if (tg) {
      tg.ready(); tg.expand();
      try { if (tg.isVersionAtLeast("7.7")) tg.disableVerticalSwipes(); } catch (e) {}
      if (tg.BackButton) tg.BackButton.onClick(goBack);
      tg.onEvent("themeChanged", applyTheme);
    }
    applyTheme();
    loadCart();
    $app.innerHTML = `<div class="center" style="min-height:80vh"><div class="spinner dark"></div></div>`;
    try {
      S.boot = await api("/api/bootstrap");
      if (!localStorage.getItem("lang")) { S.lang = S.boot.user.language || S.boot.settings.primary_language || "uz"; }
      document.documentElement.lang = S.lang;
      document.title = S.boot.settings.business_name;
    } catch (e) {
      $app.innerHTML = `<div class="empty"><div class="big">${e.detail && e.detail.code === "unauthorized" ? "📱" : "⚠️"}</div><h3>${esc(e.detail && e.detail.code === "unauthorized" ? t("open_in_tg") : errText(e))}</h3>
        <button class="btn" onclick="location.reload()">↻</button></div>`;
      return;
    }
    render();
  }
  start();
})();
