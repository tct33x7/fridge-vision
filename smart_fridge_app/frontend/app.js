"use strict";

const state = {
  currentView: "home",
  cameraReady: false,
  profile: null,
  insightDays: 7,
  intakeSession: null,
  intakeBusy: false,
  searchTimer: null,
  cameraTimer: null,
  dialogOpener: null,
};

const SESSION_STORAGE_KEY = "smartFridge.intakeSession";
const units = {
  piece: "个", pack: "包", box: "盒", bottle: "瓶", g: "克", kg: "千克", ml: "毫升", l: "升",
};
const expiryLabels = {
  expired: "已过期", expiring: "临期", fresh: "新鲜", unknown: "日期未知",
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function safeNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function formatAmount(value, maximumDigits = 1) {
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: maximumDigits }).format(safeNumber(value));
}

function formatTime(value) {
  if (!value) return "时间未知";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? String(value)
    : parsed.toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });
}

function setVisible(id, visible) {
  document.getElementById(id)?.classList.toggle("is-hidden", !visible);
}

async function api(path, options = {}) {
  const config = {
    ...options,
    headers: { Accept: "application/json", ...(options.headers || {}) },
  };
  if (config.body && typeof config.body !== "string") {
    config.body = JSON.stringify(config.body);
    config.headers["Content-Type"] = "application/json";
  }
  const response = await fetch(path, config);
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : null;
  if (!response.ok) {
    const detail = payload?.error || payload?.detail;
    const message = Array.isArray(detail)
      ? detail.map((item) => item.msg).filter(Boolean).join("；")
      : detail;
    throw new Error(message || `请求失败（${response.status}）`);
  }
  return payload;
}

function toast(message, isError = false) {
  const element = document.getElementById("toast");
  element.textContent = message;
  element.classList.toggle("is-error", isError);
  element.classList.add("is-visible");
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => element.classList.remove("is-visible"), 3000);
}

function showView(name) {
  state.currentView = name;
  document.querySelectorAll(".view").forEach((element) => {
    element.classList.toggle("is-active", element.id === `view-${name}`);
  });
  document.querySelectorAll(".nav-button").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.view === name);
  });
  if (name === "home") void loadDashboard();
  if (name === "inventory") void loadInventory();
  if (name === "capture") void loadCaptureHistory({ sync: true });
  if (name === "settings") void loadProfile();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function resetHomeSections() {
  [
    "homeEmpty", "actionSection", "inventoryOverview", "expirySection",
    "recipeSection", "insightsSection", "nutritionPanel", "flavorPanel", "recentSection",
  ].forEach((id) => setVisible(id, false));
  [
    "actionList", "summaryCards", "priorityList", "recipeList", "nutritionTotals",
    "nutritionChart", "flavorChart", "recentCaptures",
  ].forEach((id) => {
    const element = document.getElementById(id);
    if (element) element.replaceChildren();
  });
}

async function loadHealth() {
  const status = document.getElementById("systemStatus");
  try {
    const data = await api("/api/v1/health");
    const databaseReady = Boolean(data.database?.ready);
    const cameraReady = Boolean(data.camera?.ready);
    if (databaseReady && cameraReady) {
      status.className = "status-pill is-hidden";
      status.textContent = "";
      return;
    }
    status.textContent = databaseReady ? "摄像头暂不可用" : "数据服务异常";
    status.className = "status-pill is-offline";
  } catch (_error) {
    status.textContent = "主程序连接失败";
    status.className = "status-pill is-offline";
  }
}

function renderActions(actions) {
  const list = document.getElementById("actionList");
  const usable = Array.isArray(actions) ? actions : [];
  setVisible("actionSection", usable.length > 0);
  list.innerHTML = usable.map((item) => {
    const urgent = item.kind === "expired" ? "is-urgent" : "";
    if (item.kind === "open_session" && item.session_id) {
      return `<button class="action-card ${urgent}" data-action="open-session" data-session-id="${escapeHtml(item.session_id)}" type="button"><strong>${escapeHtml(item.title)}</strong><span aria-hidden="true">→</span></button>`;
    }
    return `<button class="action-card ${urgent}" data-view="${escapeHtml(item.target || "inventory")}" type="button"><strong>${escapeHtml(item.title)}</strong><span aria-hidden="true">→</span></button>`;
  }).join("");
}

function renderOverview(data) {
  if (!data.availability?.inventory) return setVisible("inventoryOverview", false);
  const cards = [
    ["现有批次", data.counts.active_lots, ""],
    ["不同食材", data.counts.distinct_products, ""],
  ];
  if (data.counts.expiring > 0) cards.push(["3 天内到期", data.counts.expiring, "is-warning"]);
  if (data.counts.expired > 0) cards.push(["已过期", data.counts.expired, "is-danger"]);
  if (data.counts.unknown_expiry > 0) cards.push(["日期待补", data.counts.unknown_expiry, ""]);
  document.getElementById("summaryCards").innerHTML = cards.map(([label, value, className]) => `
    <article class="summary-card ${className}">
      <span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><span>项</span>
    </article>`).join("");
  setVisible("inventoryOverview", true);
}

function renderPriority(items) {
  const usable = Array.isArray(items) ? items : [];
  setVisible("expirySection", usable.length > 0);
  document.getElementById("priorityList").innerHTML = usable.map((item) => {
    const days = Number(item.days_remaining);
    const dayText = days < 0 ? `已过期 ${Math.abs(days)} 天` : days === 0 ? "今天到期" : `${days} 天后到期`;
    const image = item.image_url
      ? `<img src="${escapeHtml(item.image_url)}" alt="" loading="lazy">`
      : '<div class="priority-thumb" aria-hidden="true">◇</div>';
    return `<article class="priority-item">${image}<div><strong>${escapeHtml(item.name)}</strong><p>${escapeHtml(dayText)} · ${escapeHtml(item.location_name)}</p></div></article>`;
  }).join("");
}

function renderRecipes(items) {
  const usable = Array.isArray(items) ? items : [];
  setVisible("recipeSection", usable.length > 0);
  document.getElementById("recipeList").innerHTML = usable.map((item) => `
    <article class="recipe-card">
      <h3>${escapeHtml(item.title)}</h3>
      <p class="recipe-meta">约 ${escapeHtml(item.minutes)} 分钟 · ${escapeHtml(item.reason)}</p>
      <div class="ingredient-pills">${(item.ingredients || []).map((name) => `<span>${escapeHtml(name)}</span>`).join("")}</div>
    </article>`).join("");
}

function mediaCard(item, compact = false) {
  const confirmed = Boolean(item.linked_lot_id);
  const title = confirmed ? item.linked_name : "待确认照片";
  const action = confirmed || compact
    ? ""
    : `<button type="button" data-action="resume-media" data-capture-id="${escapeHtml(item.id)}">继续处理</button>`;
  return `<article class="history-card">
    <img src="${escapeHtml(item.image_url)}" alt="拍摄记录" loading="lazy">
    <div class="history-card-body">
      <span class="record-status ${confirmed ? "is-confirmed" : ""}">${confirmed ? "已加入库存" : "待确认"}</span>
      <h3>${escapeHtml(title)}</h3>
      <p>${escapeHtml(formatTime(item.captured_at || item.created_at))}</p>
      ${action}
    </div>
  </article>`;
}

function renderRecent(items) {
  const usable = Array.isArray(items) ? items : [];
  setVisible("recentSection", usable.length > 0);
  document.getElementById("recentCaptures").innerHTML = usable.slice(0, 4).map((item) => mediaCard(item, true)).join("");
}

async function loadDashboard() {
  resetHomeSections();
  document.getElementById("homeSubtitle").textContent = "只展示你真正记录过的内容。";
  try {
    const data = await api("/api/v1/dashboard");
    renderActions(data.actions);
    renderOverview(data);
    renderPriority(data.priority_items);
    renderRecipes(data.recipe_suggestions);
    renderRecent(data.recent_captures);
    const hasInsights = await loadInsights(state.insightDays);
    const hasContent = Boolean(
      data.availability?.inventory || data.availability?.recent_captures
      || (data.actions || []).length || hasInsights,
    );
    setVisible("homeEmpty", !hasContent);
  } catch (error) {
    setVisible("homeEmpty", true);
    document.getElementById("homeSubtitle").textContent = `暂时无法读取内容：${error.message}`;
  }
}

function renderNutrition(data) {
  const panel = document.getElementById("nutritionPanel");
  if (!data.availability?.nutrition) {
    panel.classList.add("is-hidden");
    return false;
  }
  const nutrition = data.nutrition || {};
  const totals = nutrition.totals || {};
  document.getElementById("nutritionCoverage").textContent =
    `${nutrition.sample_size || 0} 条有营养数据 · 覆盖 ${formatAmount(nutrition.coverage_percent || 0)}%`;
  const metrics = [
    ["能量", totals.calories_kcal, "kcal"],
    ["蛋白质", totals.protein_g, "g"],
    ["碳水", totals.carbs_g, "g"],
    ["脂肪", totals.fat_g, "g"],
  ];
  document.getElementById("nutritionTotals").innerHTML = metrics.map(([label, value, unit]) => `
    <div class="nutrition-total"><strong>${formatAmount(value)}</strong><span>${escapeHtml(label)} · ${escapeHtml(unit)}</span></div>`).join("");

  const daily = Array.isArray(nutrition.daily) ? nutrition.daily : [];
  const maxCalories = Math.max(0, ...daily.map((item) => safeNumber(item.calories_kcal)));
  const chart = document.getElementById("nutritionChart");
  if (maxCalories > 0 && daily.length > 1) {
    chart.classList.remove("is-hidden");
    chart.setAttribute("aria-label", `${data.days} 天内每日已记录能量趋势，最高 ${formatAmount(maxCalories)} 千卡`);
    chart.innerHTML = daily.map((item) => {
      const calories = safeNumber(item.calories_kcal);
      const height = Math.max(4, Math.round((calories / maxCalories) * 124));
      const label = new Date(`${item.date}T12:00:00`).toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" });
      return `<div class="nutrition-day" title="${escapeHtml(label)}：${formatAmount(calories)} kcal"><div class="nutrition-bar-track"><div class="nutrition-bar" style="height:${height}px"></div></div><small>${escapeHtml(label)}</small></div>`;
    }).join("");
  } else {
    chart.classList.add("is-hidden");
    chart.replaceChildren();
  }
  panel.classList.remove("is-hidden");
  return true;
}

function renderFlavors(data) {
  const panel = document.getElementById("flavorPanel");
  const flavors = Array.isArray(data.flavors) ? data.flavors : [];
  if (!data.availability?.flavors || !flavors.length) {
    panel.classList.add("is-hidden");
    return false;
  }
  const total = flavors.reduce((sum, item) => sum + safeNumber(item.count), 0);
  const maximum = Math.max(...flavors.map((item) => safeNumber(item.count)), 1);
  document.getElementById("flavorTitle").textContent = data.availability.flavor_trend ? "口味趋势" : "口味记录";
  document.getElementById("flavorSample").textContent = data.availability.flavor_trend
    ? `${total} 次明确记录`
    : `${total} 次记录，积累到 3 次后显示趋势`;
  document.getElementById("flavorChart").innerHTML = flavors.map((item) => `
    <div class="flavor-row">
      <span>${escapeHtml(item.label)}</span>
      <div class="flavor-track" aria-hidden="true"><div class="flavor-fill" style="width:${Math.round((safeNumber(item.count) / maximum) * 100)}%"></div></div>
      <strong>${escapeHtml(item.count)} 次</strong>
    </div>`).join("");
  panel.classList.remove("is-hidden");
  return true;
}

async function loadInsights(days) {
  try {
    const data = await api(`/api/v1/insights?days=${days}`);
    const nutritionVisible = renderNutrition(data);
    const flavorVisible = renderFlavors(data);
    setVisible("insightsSection", nutritionVisible || flavorVisible);
    return nutritionVisible || flavorVisible;
  } catch (error) {
    setVisible("insightsSection", false);
    toast(error.message, true);
    return false;
  }
}

async function loadLocations() {
  try {
    const data = await api("/api/v1/locations");
    const options = (data.items || []).map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join("");
    document.getElementById("inventoryLocation").innerHTML = options;
    const filter = document.getElementById("inventoryLocationFilter");
    filter.querySelectorAll("option:not(:first-child)").forEach((item) => item.remove());
    filter.insertAdjacentHTML("beforeend", options);
  } catch (error) {
    toast(error.message, true);
  }
}

async function loadInventory() {
  const list = document.getElementById("inventoryList");
  const params = new URLSearchParams({ state: document.getElementById("inventoryStateFilter").value });
  const location = document.getElementById("inventoryLocationFilter").value;
  const search = document.getElementById("inventorySearch").value.trim();
  if (location) params.set("location_id", location);
  if (search) params.set("search", search);
  try {
    const data = await api(`/api/v1/inventory?${params}`);
    renderInventory(data.items || []);
  } catch (error) {
    list.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
  }
}

function renderInventory(items) {
  const list = document.getElementById("inventoryList");
  if (!items.length) {
    list.innerHTML = '<div class="empty-state">没有符合当前条件的食材。</div>';
    return;
  }
  list.innerHTML = items.map((item) => {
    const image = item.image_url
      ? `<img class="inventory-thumb" src="${escapeHtml(item.image_url)}" alt="${escapeHtml(item.name)} 的照片" loading="lazy">`
      : '<div class="inventory-thumb is-empty" aria-hidden="true">◇</div>';
    const dateText = item.expires_on ? `到期 ${item.expires_on}` : "未记录到期日";
    const controls = item.status === "active" ? `
      <div class="inventory-actions">
        <button class="eat" data-action="consume" data-id="${escapeHtml(item.id)}" data-version="${item.version}" data-quantity="${item.quantity}" type="button">吃了</button>
        <button class="danger" data-action="discard" data-id="${escapeHtml(item.id)}" data-version="${item.version}" type="button">丢弃</button>
      </div>` : "";
    return `<article class="inventory-card">
      ${image}
      <div><h3>${escapeHtml(item.name)} <span class="expiry-badge ${escapeHtml(item.expiry_status)}">${escapeHtml(expiryLabels[item.expiry_status] || item.expiry_status)}</span></h3>
      <p class="inventory-meta">${formatAmount(item.quantity, 2)} ${escapeHtml(units[item.unit] || item.unit)} · ${escapeHtml(item.location_name)} · ${escapeHtml(dateText)}</p></div>
      ${controls}
    </article>`;
  }).join("");
}

async function handleInventoryAction(button) {
  const action = button.dataset.action;
  const id = button.dataset.id;
  const version = Number(button.dataset.version);
  if (action === "consume") {
    const maximum = Number(button.dataset.quantity);
    const raw = window.prompt(`这次吃了多少？当前还有 ${maximum}`, String(Math.min(1, maximum)));
    if (raw === null) return;
    const amount = Number(raw);
    if (!(amount > 0) || amount > maximum) return toast("请输入不超过当前库存的正数", true);
    try {
      await api(`/api/v1/inventory/${id}/consume`, {
        method: "POST",
        body: { amount, expected_version: version, reason: "用户明确记录为已食用", record_meal: true, meal_type: "other" },
      });
      toast("已更新库存，并记入真实摄入记录");
    } catch (error) {
      return toast(error.message, true);
    }
  }
  if (action === "discard") {
    if (!window.confirm("确认标记为丢弃？记录会保留在库存流水中。")) return;
    try {
      await api(`/api/v1/inventory/${id}/discard`, {
        method: "POST", body: { expected_version: version, reason: "用户明确记录为丢弃" },
      });
      toast("已记录丢弃");
    } catch (error) {
      return toast(error.message, true);
    }
  }
  await Promise.all([loadInventory(), loadDashboard()]);
}

async function loadCaptureHistory({ sync = false } = {}) {
  const grid = document.getElementById("captureHistory");
  try {
    if (sync && state.cameraReady) {
      try { await api("/api/v1/media/sync?limit=24", { method: "POST" }); } catch (_error) { /* Existing local history still works. */ }
    }
    const data = await api("/api/v1/media?limit=40");
    const items = data.items || [];
    grid.innerHTML = items.map((item) => mediaCard(item)).join("");
    setVisible("captureHistoryEmpty", items.length === 0);
  } catch (error) {
    grid.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
    setVisible("captureHistoryEmpty", false);
  }
}

function updatePreviewVisibility() {
  const dialog = document.getElementById("intakeDialog");
  const preview = document.getElementById("cameraPreview");
  const placeholder = document.getElementById("cameraPlaceholder");
  const shouldStream = dialog.open && state.cameraReady && !dialog.classList.contains("is-closing");
  if (shouldStream) {
    if (!preview.getAttribute("src")) preview.src = `/api/v1/camera/stream.mjpg?t=${Date.now()}`;
    preview.classList.add("is-active");
    placeholder.classList.add("is-hidden");
  } else {
    preview.removeAttribute("src");
    preview.classList.remove("is-active");
    placeholder.classList.remove("is-hidden");
  }
}

async function loadCameraStatus() {
  const display = document.getElementById("cameraStatus");
  const shutter = document.getElementById("captureButton");
  try {
    const data = await api("/api/v1/camera/status");
    state.cameraReady = Boolean(data.connected && data.camera?.ready);
    display.textContent = state.cameraReady
      ? `相机在线 · ${data.camera.width || ""}×${data.camera.height || ""}`
      : `相机未就绪 · ${data.camera?.error || "请检查摄像头服务"}`;
    display.className = `inline-status ${state.cameraReady ? "is-online" : "is-offline"}`;
  } catch (_error) {
    state.cameraReady = false;
    display.textContent = "摄像头服务离线";
    display.className = "inline-status is-offline";
  }
  shutter.disabled = !state.cameraReady || state.intakeBusy;
  updatePreviewVisibility();
}

function setIntakeBusy(busy) {
  state.intakeBusy = busy;
  const shutter = document.getElementById("captureButton");
  const submit = document.querySelector("#inventoryForm button[type='submit']");
  shutter.disabled = busy || !state.cameraReady;
  if (submit) submit.disabled = busy;
  document.getElementById("captureHint").textContent = busy ? "正在安全保存…" : "拍摄后会立即保存到主软件";
}

function resetIntakeForm() {
  const form = document.getElementById("inventoryForm");
  form.reset();
  form.elements.quantity.value = "1";
}

function renderIntakeSession(session) {
  state.intakeSession = session;
  const captures = Array.isArray(session.captures) ? session.captures : [];
  const selectedId = session.selected_media_id;
  document.getElementById("sessionCaptureCount").textContent = String(captures.length);
  const rail = document.getElementById("sessionCaptures");
  rail.innerHTML = captures.length ? captures.map((item, index) => `
    <button class="session-capture ${item.id === selectedId ? "is-selected" : ""}" data-action="select-session-capture" data-capture-id="${escapeHtml(item.id)}" type="button" aria-label="选择本次拍摄第 ${index + 1} 张">
      <img src="${escapeHtml(item.image_url)}" alt="" loading="lazy"><span>${escapeHtml(formatTime(item.captured_at || item.created_at))}</span>
    </button>`).join("") : '<div class="session-empty">照片只会出现在这次会话中</div>';
  setVisible("reviewPanel", Boolean(selectedId));
  document.getElementById("selectedCaptureLabel").textContent = selectedId ? `照片 ${selectedId.slice(0, 8)}…` : "";
}

async function resolveSession(requestedId) {
  const savedId = requestedId || window.localStorage.getItem(SESSION_STORAGE_KEY);
  if (savedId) {
    try {
      const existing = await api(`/api/v1/intake-sessions/${encodeURIComponent(savedId)}`);
      if (["open", "review"].includes(existing.status)) return existing;
    } catch (_error) { /* Create a clean session below. */ }
    window.localStorage.removeItem(SESSION_STORAGE_KEY);
  }
  return api("/api/v1/intake-sessions", { method: "POST" });
}

async function openIntakeDialog({ sessionId = null, captureId = null, opener = null } = {}) {
  const dialog = document.getElementById("intakeDialog");
  state.dialogOpener = opener || document.activeElement;
  try {
    const session = await resolveSession(sessionId);
    let current = session;
    if (captureId && !(session.captures || []).some((item) => item.id === captureId)) {
      current = await api(`/api/v1/intake-sessions/${encodeURIComponent(session.id)}/attach/${encodeURIComponent(captureId)}`, { method: "POST" });
    }
    window.localStorage.setItem(SESSION_STORAGE_KEY, current.id);
    renderIntakeSession(current);
    if (!dialog.open) dialog.showModal();
    dialog.classList.remove("is-closing");
    await loadCameraStatus();
    window.clearInterval(state.cameraTimer);
    state.cameraTimer = window.setInterval(loadCameraStatus, 5000);
    (current.selected_media_id ? document.querySelector("#inventoryForm [name='name']") : document.getElementById("captureButton"))?.focus();
  } catch (error) {
    toast(error.message, true);
  }
}

function closeIntakeDialog() {
  const dialog = document.getElementById("intakeDialog");
  if (!dialog.open || dialog.classList.contains("is-closing")) return;
  window.clearInterval(state.cameraTimer);
  updatePreviewVisibility();
  dialog.classList.add("is-closing");
  window.setTimeout(() => {
    dialog.close();
    dialog.classList.remove("is-closing");
    updatePreviewVisibility();
    state.dialogOpener?.focus?.();
  }, window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 150);
}

async function takePhoto() {
  if (!state.intakeSession || state.intakeBusy) return;
  setIntakeBusy(true);
  try {
    const session = await api(`/api/v1/intake-sessions/${encodeURIComponent(state.intakeSession.id)}/capture`, { method: "POST" });
    renderIntakeSession(session);
    toast("照片已保存；请确认食材信息");
    document.querySelector("#inventoryForm [name='name']")?.focus();
  } catch (error) {
    toast(error.message, true);
  } finally {
    setIntakeBusy(false);
  }
}

async function selectSessionCapture(captureId) {
  if (!state.intakeSession || state.intakeBusy) return;
  try {
    const session = await api(`/api/v1/intake-sessions/${encodeURIComponent(state.intakeSession.id)}/select/${encodeURIComponent(captureId)}`, { method: "POST" });
    renderIntakeSession(session);
    document.querySelector("#inventoryForm [name='name']")?.focus();
  } catch (error) {
    toast(error.message, true);
  }
}

function optionalNumber(form, name) {
  const value = form.elements[name].value.trim();
  return value === "" ? null : Number(value);
}

async function submitIntake(form) {
  if (!state.intakeSession || !state.intakeSession.selected_media_id || state.intakeBusy) return;
  const data = new FormData(form);
  const nutrientNames = ["calories_kcal", "protein_g", "carbs_g", "fat_g"];
  const hasNutrient = nutrientNames.some((name) => data.get(name) !== "");
  const basisValue = data.get("nutrition_basis_amount");
  if (hasNutrient && !basisValue) return toast("填写营养数据时，也请填写营养基准数量", true);
  const nutrition = hasNutrient ? {
    basis_amount: Number(basisValue),
    basis_unit: data.get("nutrition_basis_unit"),
    calories_kcal: optionalNumber(form, "calories_kcal"),
    protein_g: optionalNumber(form, "protein_g"),
    carbs_g: optionalNumber(form, "carbs_g"),
    fat_g: optionalNumber(form, "fat_g"),
  } : null;
  const payload = {
    name: data.get("name"),
    category: data.get("category"),
    barcode: null,
    quantity: Number(data.get("quantity")),
    unit: data.get("unit"),
    location_id: data.get("location_id"),
    purchased_on: null,
    expires_on: data.get("expires_on") || null,
    note: data.get("note") || "",
    primary_flavor: data.get("primary_flavor") || null,
    nutrition,
  };
  setIntakeBusy(true);
  try {
    await api(`/api/v1/intake-sessions/${encodeURIComponent(state.intakeSession.id)}/confirm`, { method: "POST", body: payload });
    window.localStorage.removeItem(SESSION_STORAGE_KEY);
    state.intakeSession = null;
    resetIntakeForm();
    closeIntakeDialog();
    toast("已确认加入库存");
    await Promise.all([loadDashboard(), loadInventory(), loadCaptureHistory()]);
  } catch (error) {
    toast(error.message, true);
  } finally {
    setIntakeBusy(false);
  }
}

async function cancelIntakeSession() {
  if (!state.intakeSession || state.intakeBusy) return;
  if (!window.confirm("放弃这次录入？已经保存的照片仍会保留在识别记录中。")) return;
  setIntakeBusy(true);
  try {
    await api(`/api/v1/intake-sessions/${encodeURIComponent(state.intakeSession.id)}/cancel`, { method: "POST" });
    window.localStorage.removeItem(SESSION_STORAGE_KEY);
    state.intakeSession = null;
    resetIntakeForm();
    closeIntakeDialog();
    toast("本次录入已结束，照片仍保留");
    await Promise.all([loadDashboard(), loadCaptureHistory()]);
  } catch (error) {
    toast(error.message, true);
  } finally {
    setIntakeBusy(false);
  }
}

function parseList(value) {
  return value.split(/[，,\n]/).map((item) => item.trim()).filter(Boolean);
}

async function loadProfile() {
  try {
    const profile = await api("/api/v1/profile");
    state.profile = profile;
    const form = document.getElementById("profileForm");
    form.elements.display_name.value = profile.display_name || "";
    form.elements.diet_goal.value = profile.diet_goal || "balanced";
    form.elements.preferences.value = (profile.preferences || []).join("，");
    form.elements.allergies.value = (profile.allergies || []).join("，");
    form.elements.medications.value = (profile.medications || []).join("，");
    form.elements.onboarding_completed.checked = Boolean(profile.onboarding_completed);
    setVisible("onboardingNotice", !profile.onboarding_completed);
  } catch (error) {
    toast(error.message, true);
  }
}

async function submitProfile(form) {
  const data = new FormData(form);
  const payload = {
    display_name: data.get("display_name") || "",
    diet_goal: data.get("diet_goal"),
    preferences: parseList(data.get("preferences") || ""),
    allergies: parseList(data.get("allergies") || ""),
    medications: parseList(data.get("medications") || ""),
    onboarding_completed: data.get("onboarding_completed") === "on",
  };
  try {
    state.profile = await api("/api/v1/profile", { method: "PUT", body: payload });
    setVisible("onboardingNotice", !state.profile.onboarding_completed);
    toast("设置已保存");
  } catch (error) {
    toast(error.message, true);
  }
}

function bindEvents() {
  document.addEventListener("click", (event) => {
    const intakeButton = event.target.closest("[data-open-intake]");
    if (intakeButton) return void openIntakeDialog({ opener: intakeButton });

    const viewButton = event.target.closest("[data-view]");
    if (viewButton) return showView(viewButton.dataset.view);

    const insightButton = event.target.closest("[data-insight-days]");
    if (insightButton) {
      state.insightDays = Number(insightButton.dataset.insightDays);
      document.querySelectorAll("[data-insight-days]").forEach((button) => button.classList.toggle("is-active", button === insightButton));
      return void loadInsights(state.insightDays);
    }

    const actionButton = event.target.closest("[data-action]");
    if (!actionButton) return;
    if (actionButton.dataset.action === "open-session") {
      return void openIntakeDialog({ sessionId: actionButton.dataset.sessionId, opener: actionButton });
    }
    if (actionButton.dataset.action === "resume-media") {
      return void openIntakeDialog({ captureId: actionButton.dataset.captureId, opener: actionButton });
    }
    if (actionButton.dataset.action === "select-session-capture") {
      return void selectSessionCapture(actionButton.dataset.captureId);
    }
    if (["consume", "discard"].includes(actionButton.dataset.action)) void handleInventoryAction(actionButton);
  });

  document.getElementById("captureButton").addEventListener("click", takePhoto);
  document.getElementById("closeIntake").addEventListener("click", closeIntakeDialog);
  document.getElementById("cancelSession").addEventListener("click", cancelIntakeSession);
  document.getElementById("retakeButton").addEventListener("click", () => document.getElementById("captureButton").focus());
  document.getElementById("inventoryForm").addEventListener("submit", (event) => {
    event.preventDefault();
    void submitIntake(event.currentTarget);
  });
  document.getElementById("profileForm").addEventListener("submit", (event) => {
    event.preventDefault();
    void submitProfile(event.currentTarget);
  });
  document.getElementById("inventoryLocationFilter").addEventListener("change", loadInventory);
  document.getElementById("inventoryStateFilter").addEventListener("change", loadInventory);
  document.getElementById("inventorySearch").addEventListener("input", () => {
    window.clearTimeout(state.searchTimer);
    state.searchTimer = window.setTimeout(loadInventory, 250);
  });
  const dialog = document.getElementById("intakeDialog");
  dialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    closeIntakeDialog();
  });
  document.getElementById("cameraPreview").addEventListener("error", () => {
    state.cameraReady = false;
    updatePreviewVisibility();
    document.getElementById("cameraStatus").textContent = "实时画面中断，正在重连";
    document.getElementById("cameraStatus").className = "inline-status is-offline";
  });
}

async function init() {
  document.getElementById("todayLabel").textContent = new Intl.DateTimeFormat("zh-CN", {
    month: "long", day: "numeric", weekday: "long",
  }).format(new Date());
  bindEvents();
  await Promise.all([loadHealth(), loadLocations(), loadDashboard(), loadProfile()]);
  window.setInterval(loadHealth, 30000);
}

document.addEventListener("DOMContentLoaded", init);
