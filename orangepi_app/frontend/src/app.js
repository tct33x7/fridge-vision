const state = {
  inventory: [],
  scans: [],
  nutrition: null,
  recipes: [],
  recipeSource: "local-rules",
  scanType: "receipt",
  selectedFile: null,
  currentScan: null,
  inventoryFilter: "all",
  inventorySearch: "",
  activeView: "home",
  cameraScanType: "food",
  cameraSequence: null,
  cameraPollBusy: false,
  cameraDevices: [],
  cameraStreamActive: false,
  cameraCurrentDevice: "",
  cameraSource: "server",
  cameraMode: "auto",
  browserStream: null,
  browserFacingMode: "environment",
  ocrEngines: [],
  selectedEngine: "rapidocr",
  cameraSelectedEngine: "rapidocr",
  manualRequested: false,   // 是否已请求 manual 模式（离开摄像头页时需切回 counter）
  counterBusy: false,
};

// 需要引擎选择的识别类型
const ENGINE_TYPES = new Set(["receipt", "expiry", "ocr"]);

const SCAN_CONFIG = {
  food: {
    label: "食物照片",
    title: "拍摄一份食物或食材",
    hint: "尽量只拍一种食物，背景简洁、光线均匀",
    loading: "正在生成食物候选…",
    demoPath: "/api/scans/demo-food",
    demoLabel: "运行食物照片 Demo",
  },
  barcode: {
    label: "商品条形码",
    title: "拍摄包装上的条形码",
    hint: "让条码横向占满画面，避免反光、弯折和运动模糊",
    loading: "正在解码条形码…",
    demoPath: "/api/scans/demo-barcode",
    demoLabel: "运行条形码 Demo",
  },
  receipt: {
    label: "购物小票",
    title: "拍摄或选择购物小票",
    hint: "让文字占满画面，避免反光和手指遮挡",
    loading: "正在读取小票商品…",
    demoPath: "/api/scans/demo-receipt",
    demoLabel: "使用 receipt.jpg 示例",
  },
  expiry: {
    label: "包装日期",
    title: "拍摄包装上的生产 / 到期日期",
    hint: "贴近喷码对焦，保留 MFG、EXP、保质期等上下文",
    loading: "正在寻找包装日期…",
    demoPath: null,
    demoLabel: "",
  },
  ocr: {
    label: "OCR 文字识别",
    title: "拍摄或选择需要识别的文字图片",
    hint: "让文字清晰占满画面，避免反光和模糊",
    loading: "正在识别文字…",
    demoPath: null,
    demoLabel: "",
  },
};

const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function showLoading(text = "正在处理…") {
  $("#loadingText").textContent = text;
  $("#loadingOverlay").classList.remove("hidden");
}

function hideLoading() {
  $("#loadingOverlay").classList.add("hidden");
}

let toastTimer;
function toast(message, type = "success") {
  const box = $("#toast");
  box.textContent = message;
  box.className = `toast ${type === "error" ? "error" : ""}`.trim();
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => box.classList.add("hidden"), 3200);
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json") ? await response.json() : null;
  if (!response.ok) {
    const detail = data?.detail;
    const message = Array.isArray(detail)
      ? detail.map(item => item.msg).join("；")
      : detail || `请求失败 (${response.status})`;
    throw new Error(message);
  }
  return data;
}

function navigate(view) {
  state.activeView = view;
  $$(".view").forEach(section => section.classList.toggle("active", section.id === `view-${view}`));
  $$('[data-view]').forEach(button => button.classList.toggle("active", button.dataset.view === view && button.classList.contains("nav-item")));
  window.scrollTo({ top: 0, behavior: "smooth" });
  if (view === "inventory") renderInventory();
  if (view === "scan") populateBatchSelect();
  if (view === "camera") {
    // 进入摄像头页面：暂停自动计数，把摄像头让给手动拍照
    if (!state.manualRequested) {
      state.manualRequested = true;
      setServerCameraMode("manual");
    }
    populateCameraBatchSelect();
    if (state.cameraMode !== "usb_only" && state.cameraSource === "server") {
      loadCameraDevices();
    }
    pollCameraStatus();
  } else {
    deactivateCameraStream();
    stopBrowserCamera();
    // 离开摄像头页面：恢复自动计数
    if (state.manualRequested) {
      state.manualRequested = false;
      setServerCameraMode("counter");
    }
  }
  // 首页展示计数实时画面；其他页面断开 MJPEG 流
  if (view === "home") activateCounterStream();
  else deactivateCounterStream();
  if (view === "recipes") loadRecipes();
}

async function setServerCameraMode(mode) {
  try {
    const result = await api("/api/camera/mode", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    });
    if (mode === "counter" && result.counter?.status) {
      toast("物品自动计数已恢复");
    }
  } catch (error) {
    toast(`摄像头模式切换失败：${error.message}`, "error");
  }
}

async function loadAll() {
  const results = await Promise.allSettled([
    api("/api/inventory"),
    api("/api/nutrition/summary"),
    api("/api/recipes/today?servings=2"),
    api("/api/scans?limit=30"),
    api("/api/scans/engines"),
  ]);
  if (results[0].status === "fulfilled") state.inventory = results[0].value.items;
  if (results[1].status === "fulfilled") state.nutrition = results[1].value;
  if (results[2].status === "fulfilled") {
    state.recipes = results[2].value.items;
    state.recipeSource = results[2].value.generated_by || "local-rules";
  }
  if (results[3].status === "fulfilled") state.scans = results[3].value.items;
  if (results[4].status === "fulfilled") {
    state.ocrEngines = results[4].value.engines || [];
    populateEngineSelects();
  }
  renderDashboard();
  renderInventory();
  renderNutrition();
  renderRecipeSummary();
  renderRecipes();
  renderScanHistory();
  populateBatchSelect();
  populateCameraBatchSelect();
  activateCounterStream();   // 默认首页展示计数实时画面
  startCameraPolling();
}

function populateEngineSelects() {
  const options = state.ocrEngines.length
    ? state.ocrEngines.map(e =>
        `<option value="${escapeHtml(e.id)}" ${!e.available ? "disabled" : ""}>${escapeHtml(e.name)}${!e.available ? "（未安装）" : ""}</option>`
      ).join("")
    : '<option value="rapidocr">RapidOCR</option>';
  $("#engineSelect").innerHTML = options;
  $("#cameraEngineSelect").innerHTML = options;
  $("#engineSelect").value = state.selectedEngine;
  $("#cameraEngineSelect").value = state.cameraSelectedEngine;
}

async function refreshInventoryData() {
  const [inventory, nutrition, recipes] = await Promise.all([
    api("/api/inventory"),
    api("/api/nutrition/summary"),
    api(`/api/recipes/today?servings=${Number($("#servings").value) || 2}`),
  ]);
  state.inventory = inventory.items;
  state.nutrition = nutrition;
  state.recipes = recipes.items;
  state.recipeSource = recipes.generated_by || "local-rules";
  renderDashboard();
  renderInventory();
  renderNutrition();
  renderRecipeSummary();
  renderRecipes();
  populateBatchSelect();
  populateCameraBatchSelect();
}

function categoryEmoji(category, name = "") {
  if (name.includes("牛奶") || category === "乳品") return "🥛";
  if (name.includes("鸡蛋") || category === "蛋类") return "🥚";
  if (name.includes("鸡")) return "🍗";
  if (name.includes("牛") || category === "肉类") return "🥩";
  if (name.includes("油") || category === "粮油") return "🫙";
  if (category === "烘焙") return "🥖";
  if (category === "蔬果") return "🥬";
  if (category === "零食") return "🍪";
  return "🍽️";
}

function expiryText(item) {
  if (item.expiry_status === "expired") return `已过期 ${Math.abs(item.days_until_expiry)} 天`;
  if (item.expiry_status === "expiring") return item.days_until_expiry === 0 ? "今天到期" : `${item.days_until_expiry} 天后到期`;
  if (item.expiry_status === "fresh") return `${item.days_until_expiry} 天后到期`;
  return "日期待补充";
}

function renderDashboard() {
  const expiry = state.inventory.reduce((acc, item) => {
    acc[item.expiry_status] = (acc[item.expiry_status] || 0) + 1;
    return acc;
  }, {});
  $("#totalCount").textContent = state.inventory.length;
  $("#freshCount").textContent = expiry.fresh || 0;
  $("#unknownCount").textContent = expiry.unknown || 0;
  $("#expiringCount").textContent = (expiry.expiring || 0) + (expiry.expired || 0);
  $("#pendingCount").textContent = state.scans.filter(item => item.status === "pending_confirmation").length;
  const urgent = state.inventory.find(item => ["expired", "expiring"].includes(item.expiry_status));
  $("#expiryHint").textContent = urgent ? `${urgent.name} · ${expiryText(urgent)}` : "暂无临期食材";

  const preview = state.inventory.slice(0, 4);
  $("#homeInventory").innerHTML = preview.length
    ? preview.map(item => `
      <article class="food-tile">
        <div class="food-visual">${categoryEmoji(item.category, item.name)}</div>
        <b title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</b>
        <small>${escapeHtml(expiryText(item))}</small>
      </article>`).join("")
    : '<div class="empty-state">还没有库存，上传 receipt.jpg 试试看</div>';
}

function renderNutrition() {
  const totals = state.nutrition?.totals || {};
  const percent = state.nutrition?.daily_reference_percent || {};
  $("#caloriesValue").textContent = Math.round(totals.calories_kcal || 0).toLocaleString("zh-CN");
  const rows = [
    ["蛋白质", "protein_g", "g"],
    ["碳水", "carbs_g", "g"],
    ["脂肪", "fat_g", "g"],
  ];
  $("#nutritionBars").innerHTML = rows.map(([label, key, unit]) => `
    <div class="nutrition-row">
      <span>${label}</span>
      <div class="bar-track"><div class="bar-fill" style="width:${Math.min(100, percent[key] || 0)}%"></div></div>
      <b>${Math.round(totals[key] || 0)}${unit}</b>
    </div>`).join("");
}

function renderRecipeSummary() {
  const recipe = state.recipes[0];
  if (!recipe) return;
  const isAI = state.recipeSource.startsWith("deepseek:");
  $("#homeRecipe").innerHTML = `
    <div class="recipe-copy">
      <span class="sticker purple">${isAI ? "DEEPSEEK PICK" : "TODAY'S PICK"}</span>
      <p>今日推荐 · ${recipe.minutes ? `${recipe.minutes} 分钟` : "等待库存"}</p>
      <h2>${escapeHtml(recipe.title)}</h2>
      <span>${escapeHtml(recipe.subtitle)}</span>
      <button class="dark-button" data-view="recipes">查看做法 <b>↗</b></button>
    </div>
    <div class="recipe-art" aria-hidden="true"><span class="plate">♨</span><span class="spark one">✦</span><span class="spark two">✱</span></div>`;
}

function filteredInventory() {
  const query = state.inventorySearch.trim().toLowerCase();
  return state.inventory.filter(item => {
    const matchesText = !query || item.name.toLowerCase().includes(query) || String(item.barcode || "").includes(query);
    const matchesFilter = state.inventoryFilter === "all"
      || (state.inventoryFilter === "expiring" && ["expiring", "expired"].includes(item.expiry_status))
      || (state.inventoryFilter === "unknown" && item.expiry_status === "unknown");
    return matchesText && matchesFilter;
  });
}

function renderInventory() {
  $("#filterAllCount").textContent = state.inventory.length;
  const items = filteredInventory();
  $("#inventoryGrid").innerHTML = items.length ? items.map(item => `
    <article class="inventory-item ${escapeHtml(item.expiry_status)}">
      <div class="inventory-item-top">
        <span class="food-icon">${categoryEmoji(item.category, item.name)}</span>
        <span class="expiry-label">${escapeHtml(expiryText(item))}</span>
      </div>
      <h3>${escapeHtml(item.name)}</h3>
      <span class="meta">${escapeHtml(item.category)} · ${escapeHtml(item.storage_location)}${item.barcode ? ` · ${escapeHtml(item.barcode)}` : ""}</span>
      <div class="quantity-line"><strong>${Number(item.quantity).toLocaleString("zh-CN")}</strong> ${escapeHtml(item.unit)}</div>
      <div class="item-actions">
        <button data-consume="${item.id}" data-max="${item.quantity}">用掉 1 ${escapeHtml(item.unit)}</button>
        <button data-expiry="${item.id}">拍日期</button>
        <button class="danger-text" data-discard="${item.id}" data-name="${escapeHtml(item.name)}">删除</button>
      </div>
    </article>`).join("") : '<div class="empty-state">没有符合条件的库存</div>';
}

function renderRecipes() {
  const list = state.recipes || [];
  const isAI = state.recipeSource.startsWith("deepseek:");
  $("#recipeList").innerHTML = list.map(recipe => `
    <article class="panel recipe-detail">
      <div class="recipe-side">
        <span class="sticker lime">${isAI ? "AI GENERATED" : "FRESH FIRST"}</span>
        <h2>${escapeHtml(recipe.title)}</h2>
        <p>${escapeHtml(recipe.subtitle)}</p>
        <div class="recipe-facts"><span>⏱ ${recipe.minutes} 分钟</span><span>♙ ${recipe.servings} 人份</span><span>⚡ ${recipe.calories_kcal} kcal</span></div>
      </div>
      <div class="recipe-body">
        <div class="reason-note">✦ ${escapeHtml(recipe.priority_reason)}</div>
        <h3>从冰箱取出</h3>
        <div class="ingredients">${recipe.ingredients.length ? recipe.ingredients.map(item => `<span>${escapeHtml(item)}</span>`).join("") : "<span>暂无食材</span>"}</div>
        <h3>简单做法</h3>
        <ol class="steps">${recipe.steps.map(step => `<li>${escapeHtml(step)}</li>`).join("")}</ol>
      </div>
    </article>`).join("");
}

function setScanType(type) {
  const config = SCAN_CONFIG[type] || SCAN_CONFIG.receipt;
  state.scanType = type;
  $$('[data-scan-type]').forEach(button => button.classList.toggle("active", button.dataset.scanType === type));
  $("#expiryBatchWrap").classList.toggle("hidden", type !== "expiry");
  $("#engineSelectorWrap").classList.toggle("hidden", !ENGINE_TYPES.has(type));
  $("#demoScanButton").classList.toggle("hidden", !config.demoPath);
  $("#demoScanButton").textContent = config.demoLabel;
  $("#cameraTitle").textContent = config.title;
  $("#cameraHint").textContent = config.hint;
  state.selectedFile = null;
  $("#scanFile").value = "";
  $("#imagePreview").classList.add("hidden");
  $("#analyzeButton").disabled = true;
  state.currentScan = null;
  $("#resultContent").classList.add("hidden");
  $("#resultEmpty").classList.remove("hidden");
}

function populateBatchSelect(selectedId = null) {
  const select = $("#expiryBatch");
  const current = selectedId || select.value;
  select.innerHTML = '<option value="">请选择库存批次</option>' + state.inventory.map(item =>
    `<option value="${item.id}" ${String(current) === String(item.id) ? "selected" : ""}>${escapeHtml(item.name)} · ${item.quantity}${escapeHtml(item.unit)} · ${escapeHtml(expiryText(item))}</option>`
  ).join("");
}

function populateCameraBatchSelect(selectedId = null) {
  const select = $("#cameraExpiryBatch");
  const current = selectedId || select.value;
  select.innerHTML = '<option value="">请选择库存批次</option>' + state.inventory.map(item =>
    `<option value="${item.id}" ${String(current) === String(item.id) ? "selected" : ""}>${escapeHtml(item.name)} · ${item.quantity}${escapeHtml(item.unit)} · ${escapeHtml(expiryText(item))}</option>`
  ).join("");
}

async function setCameraScanType(type, sync = true) {
  state.cameraScanType = SCAN_CONFIG[type] ? type : "food";
  $$('[data-camera-scan-type]').forEach(button => button.classList.toggle("active", button.dataset.cameraScanType === state.cameraScanType));
  $("#cameraExpiryBatchWrap").classList.toggle("hidden", state.cameraScanType !== "expiry");
  $("#cameraEngineWrap").classList.toggle("hidden", !ENGINE_TYPES.has(state.cameraScanType));
  if (!sync || (state.cameraScanType === "expiry" && !$("#cameraExpiryBatch").value)) return;
  try {
    await syncCameraConfig();
  } catch (error) {
    toast(error.message, "error");
  }
}

async function syncCameraConfig() {
  const batchId = state.cameraScanType === "expiry" ? Number($("#cameraExpiryBatch").value) || null : null;
  const engine = ENGINE_TYPES.has(state.cameraScanType) ? $("#cameraEngineSelect").value : state.cameraSelectedEngine;
  state.cameraSelectedEngine = engine;
  return api("/api/camera/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scan_type: state.cameraScanType, batch_id: batchId, engine }),
  });
}

function setCameraSource(source) {
  if (state.cameraSource === source) return;
  // 停止旧的
  if (state.cameraSource === "server") {
    deactivateCameraStream();
  } else {
    stopBrowserCamera();
  }
  state.cameraSource = source;
  // 切换 UI
  $$('[data-camera-source]').forEach(btn => btn.classList.toggle("active", btn.dataset.cameraSource === source));
  $("#serverCameraBlock").classList.toggle("hidden", source !== "server");
  $("#browserCameraBlock").classList.toggle("hidden", source !== "browser");
  // 切换视频显示
  $("#liveCameraStream").classList.toggle("hidden", source !== "server");
  $("#browserCameraVideo").classList.toggle("hidden", source !== "browser");
  // 重置状态
  $("#cameraOffline").classList.remove("hidden");
  $("#cameraTopStatus").textContent = source === "server" ? "正在连接" : "点击开启手机摄像头";
  $("#cameraTopStatus").className = "camera-top-status";
  // 启动新的
  if (source === "server") {
    loadCameraDevices();
  }
  // 更新拍照按钮
  updateCaptureButton();
}

function updateCaptureButton() {
  const btn = $("#cameraCaptureButton");
  if (state.cameraSource === "browser") {
    btn.querySelector("small").textContent = "浏览器拍照";
    btn.disabled = !state.browserStream;
  } else {
    btn.querySelector("small").textContent = "也可按下物理按钮";
  }
}

async function startBrowserCamera() {
  const btn = $("#browserCameraStartBtn");
  btn.disabled = true;
  btn.querySelector("b").textContent = "正在开启…";
  try {
    if (state.browserStream) {
      state.browserStream.getTracks().forEach(t => t.stop());
    }
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: state.browserFacingMode, width: { ideal: 1920 }, height: { ideal: 1080 } },
      audio: false,
    });
    state.browserStream = stream;
    const video = $("#browserCameraVideo");
    video.srcObject = stream;
    await video.play();
    $("#cameraOffline").classList.add("hidden");
    $("#cameraTopStatus").textContent = "手机摄像头在线";
    $("#cameraTopStatus").className = "camera-top-status online";
    btn.querySelector("b").textContent = "已开启";
    btn.disabled = false;
    $("#browserCameraSwitchBtn").classList.remove("hidden");
    $("#cameraCaptureButton").disabled = false;
    updateCaptureButton();
    toast("手机摄像头已开启", "success");
  } catch (error) {
    btn.querySelector("b").textContent = "开启手机摄像头";
    btn.disabled = false;
    if (error.name === "NotAllowedError") {
      toast("请在浏览器中允许摄像头访问权限", "error");
    } else if (error.name === "NotFoundError") {
      toast("未检测到摄像头设备", "error");
    } else {
      toast(`摄像头开启失败：${error.message}`, "error");
    }
  }
}

function stopBrowserCamera() {
  if (state.browserStream) {
    state.browserStream.getTracks().forEach(t => t.stop());
    state.browserStream = null;
  }
  const video = $("#browserCameraVideo");
  if (video) video.srcObject = null;
  const btn = $("#browserCameraStartBtn");
  if (btn) {
    btn.querySelector("b").textContent = "开启手机摄像头";
    btn.disabled = false;
  }
  const switchBtn = $("#browserCameraSwitchBtn");
  if (switchBtn) switchBtn.classList.add("hidden");
}

function switchBrowserCamera() {
  state.browserFacingMode = state.browserFacingMode === "environment" ? "user" : "environment";
  stopBrowserCamera();
  startBrowserCamera();
}

async function captureFromBrowserCamera() {
  const video = $("#browserCameraVideo");
  if (!video || !state.browserStream) return toast("请先开启手机摄像头", "error");
  const canvas = $("#browserCameraCanvas");
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  const ctx = canvas.getContext("2d");
  ctx.drawImage(video, 0, 0);
  const batchId = state.cameraScanType === "expiry" ? Number($("#cameraExpiryBatch").value) || null : null;
  if (state.cameraScanType === "expiry" && !batchId) return toast("请先选择日期对应的库存批次", "error");
  const engine = ENGINE_TYPES.has(state.cameraScanType) ? $("#cameraEngineSelect").value : state.cameraSelectedEngine;
  showLoading(SCAN_CONFIG[state.cameraScanType]?.loading || "正在拍照识别…");
  try {
    const blob = await new Promise(resolve => canvas.toBlob(resolve, "image/jpeg", 0.92));
    const form = new FormData();
    form.append("file", blob, `browser-camera-${Date.now()}.jpg`);
    form.append("scan_type", state.cameraScanType);
    if (batchId) form.append("batch_id", batchId);
    form.append("engine", engine);
    const scan = await api("/api/scans", { method: "POST", body: form });
    await openCapturedScan(scan, "web");
  } catch (error) {
    toast(error.message, "error");
  } finally {
    hideLoading();
  }
}

async function loadCameraDevices() {
  try {
    const data = await api("/api/camera/devices");
    state.cameraDevices = data.devices || [];
    const select = $("#cameraDeviceSelect");
    if (state.cameraDevices.length === 0) {
      select.innerHTML = '<option value="">未检测到摄像头</option>';
      $("#cameraStartBtn").disabled = true;
      return;
    }
    select.innerHTML = state.cameraDevices.map(d =>
      `<option value="${d.id}">${d.name}${d.resolution ? ' (' + d.resolution + ')' : ''}</option>`
    ).join("");
    // 选中当前设备
    if (state.cameraCurrentDevice) {
      select.value = state.cameraCurrentDevice;
    }
    $("#cameraStartBtn").disabled = false;
    // 如果当前没有活跃的流，自动启动第一个摄像头
    if (!state.cameraStreamActive) {
      startCamera();
    }
  } catch (error) {
    $("#cameraDeviceSelect").innerHTML = '<option value="">检测失败</option>';
    toast(`摄像头检测失败：${error.message}`, "error");
  }
}

async function startCamera() {
  const deviceId = $("#cameraDeviceSelect").value;
  if (!deviceId) return toast("请先选择一个摄像头", "error");
  const btn = $("#cameraStartBtn");
  btn.disabled = true;
  btn.querySelector("b").textContent = "正在开启…";
  try {
    await api("/api/camera/switch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_id: deviceId }),
    });
    state.cameraCurrentDevice = deviceId;
    state.cameraStreamActive = true;
    activateCameraStream();
    btn.querySelector("b").textContent = "已开启";
    btn.disabled = false;
    toast("摄像头已开启", "success");
  } catch (error) {
    toast(`摄像头开启失败：${error.message}`, "error");
    btn.querySelector("b").textContent = "开启摄像头";
    btn.disabled = false;
  }
}

function activateCameraStream() {
  const stream = $("#liveCameraStream");
  if (stream.dataset.active === "true") return;
  stream.dataset.active = "true";
  stream.src = `/api/camera/stream?t=${Date.now()}`;
}

function deactivateCameraStream() {
  const stream = $("#liveCameraStream");
  if (!stream) return;
  stream.dataset.active = "false";
  state.cameraStreamActive = false;
  stream.removeAttribute("src");
}

// ---------------- 物品进出自动计数 ----------------

function activateCounterStream() {
  const img = $("#counterStream");
  if (!img || img.dataset.active === "true") return;
  img.dataset.active = "true";
  img.dataset.attempt = String(Date.now());
  img.src = `/api/counter/video?t=${Date.now()}`;
}

function deactivateCounterStream() {
  const img = $("#counterStream");
  if (!img) return;
  img.dataset.active = "false";
  img.removeAttribute("src");
}

function renderCounterState(data) {
  const chip = $("#counterModeChip");
  const offline = $("#counterOffline");
  const offlineTitle = $("#counterOfflineTitle");
  const offlineHint = $("#counterOfflineHint");
  if (!chip || !offline) return;
  const paused = data.paused || !data.running;
  chip.textContent = paused ? "已暂停" : data.error ? "异常" : "计数中";
  chip.className = `tiny-badge ${paused ? "paused" : data.error ? "error" : "live"}`;
  offline.classList.toggle("hidden", !paused);
  if (paused) {
    offlineTitle.textContent = "计数监控暂停";
    offlineHint.textContent = data.error || "已切换到手动拍照；离开摄像头页面后自动恢复";
  }
  $("#counterStatusText").textContent = data.error || data.status || "未启动";
  $("#counterStatsMeta").textContent = data.running
    ? `${data.fps ?? "?"} FPS · 追踪 ${data.n_tracks ?? 0} 个目标 · 置信度 ${Math.round((data.conf || 0) * 100)}%`
    : "";
  const counts = data.counts || {};
  $("#counterCounts").innerHTML = Object.keys(counts).length
    ? Object.entries(counts).map(([name, net]) => `
      <div class="counter-count-row">
        <b>${escapeHtml(name)}</b>
        <span class="counter-delta ${net > 0 ? "in" : net < 0 ? "out" : ""}">${net > 0 ? "+" : ""}${net}</span>
      </div>`).join("")
    : '<div class="empty-state">还没有识别到物品进出</div>';
  const events = data.events || [];
  $("#counterEvents").innerHTML = events.length
    ? events.map(ev => `
      <li><small>${escapeHtml(ev.t)}</small><b>${escapeHtml(ev.cls)}</b>
      <span class="counter-delta ${ev.delta > 0 ? "in" : "out"}">${ev.delta > 0 ? "放入" : "取出"}</span></li>`).join("")
    : '<li class="empty-state">暂无进出记录</li>';
}

async function pollCounterState() {
  if (state.counterBusy || state.activeView !== "home") return;
  state.counterBusy = true;
  try {
    const data = await api("/api/counter/state");
    renderCounterState(data);
    // 模式切换后流断了？服务端已就绪则自动重试拉流（至少间隔 3s）
    const img = $("#counterStream");
    if (data.running && !data.paused && img && img.dataset.active !== "true"
        && Date.now() - Number(img.dataset.attempt || 0) > 3000) {
      activateCounterStream();
    }
  } catch (error) {
    renderCounterState({ paused: true, error: `计数服务不可用：${error.message}` });
  } finally {
    state.counterBusy = false;
  }
}

async function flipCounterLine() {
  try {
    await api("/api/counter/line/flip", { method: "POST" });
    toast("已翻转进出方向");
  } catch (error) {
    toast(error.message, "error");
  }
}

function resetCounter() {
  const dialog = $("#confirmDialog");
  $("#dialogTitle").textContent = "计数清零？";
  $("#dialogText").textContent = "所有物品的净计数与流水会重新开始，历史记录仍保留在数据库中。";
  dialog.showModal();
  dialog.addEventListener("close", async function handler() {
    dialog.removeEventListener("close", handler);
    if (dialog.returnValue !== "confirm") return;
    try {
      await api("/api/counter/reset", { method: "POST" });
      await pollCounterState();
      toast("计数已清零");
    } catch (error) {
      toast(error.message, "error");
    }
  });
}

function renderCameraStatus(status) {
  const camera = status.camera || {};
  const button = status.button || {};
  const capture = status.capture || {};
  // 看门狗可能在页面休眠时把模式切回了 counter；回到摄像头页面后重新申请 manual
  if (status.mode === "counter" && state.activeView === "camera" && state.manualRequested) {
    setServerCameraMode("manual");
  }
  // usb_only 模式：隐藏摄像头选择和来源切换，自动开启 USB 摄像头
  const usbOnly = camera.camera_mode === "usb_only";
  state.cameraMode = camera.camera_mode || "auto";
  if (usbOnly) {
    $$(".camera-source-toggle").forEach(el => el.classList.add("hidden"));
    const serverBlock = $("#serverCameraBlock");
    const browserBlock = $("#browserCameraBlock");
    if (serverBlock) serverBlock.classList.add("hidden");
    if (browserBlock) browserBlock.classList.add("hidden");
    state.cameraSource = "server";
  }
  // 摄像头页面 + manual 模式 + 摄像头在线：确保 MJPEG 流处于激活（含失败重试）
  if (status.mode === "manual" && camera.online && !state.cameraStreamActive
      && state.activeView === "camera" && state.cameraSource === "server") {
    activateCameraStream();
    state.cameraStreamActive = true;
  }
  const top = $("#cameraTopStatus");
  top.className = `camera-top-status ${camera.online ? "online" : "error"}`;
  top.textContent = capture.busy ? "正在拍照识别" : camera.online ? "摄像头在线" : "摄像头离线";
  $("#cameraDeviceText").textContent = camera.device || "--";
  $("#cameraResolutionText").textContent = `${camera.resolution || "--"} · ${camera.fps || "--"} FPS`;
  $("#buttonConnectionText").textContent = button.ready ? `7 号脚 · PL4 · wPi ${button.wpi_pin}` : button.enabled ? "未启用" : "无";
  $("#cameraStatusDot").className = camera.online ? "online" : "error";
  $("#cameraStatusText").textContent = camera.online ? `${camera.device} 正常输出画面` : camera.error || "等待开启摄像头";
  $("#buttonStatusDot").className = button.ready ? "online" : "error";
  $("#buttonStatusText").textContent = button.ready ? "物理 7 号脚已启用输入上拉与按键防抖" : button.error || "GPIO 按钮未启用";
  $("#captureStatusDot").className = capture.busy ? "online" : capture.error ? "error" : "";
  $("#lastCaptureText").textContent = capture.busy
    ? "正在处理摄像头照片"
    : capture.last_capture_at
      ? `${new Date(capture.last_capture_at).toLocaleString("zh-CN")} · ${capture.last_trigger === "gpio" ? "物理按钮" : "网页按钮"}`
      : capture.error || "尚未拍照";
  $("#cameraCaptureButton").disabled = !camera.online || capture.busy;
  $("#cameraOffline").classList.toggle("hidden", Boolean(camera.online));
  // 更新设备下拉列表（如果后端返回了新设备）—— usb_only 模式下跳过
  if (!usbOnly) {
    const devices = camera.available_devices;
    if (devices && devices.length > 0) {
      const select = $("#cameraDeviceSelect");
      const currentVal = select.value;
      const hasNew = devices.length !== state.cameraDevices.length ||
        devices.some(d => !state.cameraDevices.some(s => s.id === d.id));
      if (hasNew) {
        state.cameraDevices = devices;
        select.innerHTML = devices.map(d =>
          `<option value="${d.id}">${d.name}${d.resolution ? ' (' + d.resolution + ')' : ''}</option>`
        ).join("");
        if (currentVal && devices.some(d => d.id === currentVal)) {
          select.value = currentVal;
        } else if (camera.device) {
          select.value = camera.device;
          state.cameraCurrentDevice = camera.device;
        }
      }
    }
    // 更新开启按钮状态
    const startBtn = $("#cameraStartBtn");
    if (startBtn) {
      startBtn.querySelector("b").textContent = camera.online ? "已开启" : "开启摄像头";
    }
  }
}

async function openCapturedScan(scan, trigger = "web") {
  if (!state.scans.some(item => item.id === scan.id)) state.scans.unshift(scan);
  setScanType(scan.scan_type);
  if (scan.batch_id) populateBatchSelect(scan.batch_id);
  renderScanResult(scan);
  renderScanHistory();
  renderDashboard();
  navigate("scan");
  toast(trigger === "gpio" ? "物理按钮拍照识别完成，请确认后加入库存" : "拍照识别完成，请确认后加入库存");
}

async function pollCameraStatus() {
  if (state.cameraPollBusy) return;
  state.cameraPollBusy = true;
  try {
    // view=camera 标记当前处于摄像头页面，供服务端 manual 模式活跃判定
    const status = await api(`/api/camera/status${state.activeView === "camera" ? "?view=camera" : ""}`);
    renderCameraStatus(status);
    const sequence = Number(status.capture?.sequence || 0);
    if (state.cameraSequence === null) {
      state.cameraSequence = sequence;
    } else if (sequence > state.cameraSequence && status.capture?.last_scan_id) {
      state.cameraSequence = sequence;
      const scan = await api(`/api/scans/${status.capture.last_scan_id}`);
      if (state.currentScan?.id !== scan.id) await openCapturedScan(scan, status.capture.last_trigger);
    }
  } catch (error) {
    renderCameraStatus({ camera: { error: error.message }, button: {}, capture: {} });
  } finally {
    state.cameraPollBusy = false;
  }
}

let cameraPollTimer;
function startCameraPolling() {
  if (cameraPollTimer) return;
  pollCameraStatus();
  pollCounterState();
  cameraPollTimer = window.setInterval(() => {
    pollCameraStatus();
    pollCounterState();
  }, 1500);
}

async function captureFromUsbCamera() {
  // 浏览器摄像头走单独的拍照逻辑
  if (state.cameraSource === "browser") {
    return captureFromBrowserCamera();
  }
  const batchId = state.cameraScanType === "expiry" ? Number($("#cameraExpiryBatch").value) || null : null;
  if (state.cameraScanType === "expiry" && !batchId) return toast("请先选择日期对应的库存批次", "error");
  const engine = ENGINE_TYPES.has(state.cameraScanType) ? $("#cameraEngineSelect").value : state.cameraSelectedEngine;
  showLoading(SCAN_CONFIG[state.cameraScanType]?.loading || "正在拍照识别…");
  try {
    const scan = await api("/api/camera/capture", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scan_type: state.cameraScanType, batch_id: batchId, engine }),
    });
    await openCapturedScan(scan, "web");
  } catch (error) {
    toast(error.message, "error");
  } finally {
    hideLoading();
    pollCameraStatus();
  }
}

async function analyzeSelectedFile() {
  if (!state.selectedFile) return;
  if (state.scanType === "expiry" && !$("#expiryBatch").value) {
    toast("请先选择这张日期对应的库存", "error");
    return;
  }
  const form = new FormData();
  form.append("file", state.selectedFile);
  form.append("scan_type", state.scanType);
  if (ENGINE_TYPES.has(state.scanType)) {
    state.selectedEngine = $("#engineSelect").value;
    form.append("engine", state.selectedEngine);
  }
  if (state.scanType === "expiry") form.append("batch_id", $("#expiryBatch").value);
  showLoading(SCAN_CONFIG[state.scanType]?.loading || "正在分析图片…");
  try {
    const scan = await api("/api/scans", { method: "POST", body: form });
    state.currentScan = scan;
    state.scans.unshift(scan);
    renderScanResult(scan);
    renderScanHistory();
    renderDashboard();
    toast("识别完成，请检查候选结果");
  } catch (error) {
    toast(error.message, "error");
  } finally {
    hideLoading();
  }
}

async function useDemoScan() {
  const config = SCAN_CONFIG[state.scanType];
  if (!config?.demoPath) return;
  showLoading(`正在运行${config.label} Demo…`);
  try {
    const scan = await api(config.demoPath, { method: "POST" });
    state.currentScan = scan;
    state.scans.unshift(scan);
    renderScanResult(scan);
    renderScanHistory();
    renderDashboard();
    toast(`Demo 完成：得到 ${scan.result?.items?.length || 0} 个候选，请先确认`);
  } catch (error) {
    toast(error.message, "error");
  } finally {
    hideLoading();
  }
}

function renderScanResult(scan) {
  state.currentScan = scan;
  $("#resultEmpty").classList.add("hidden");
  const root = $("#resultContent");
  root.classList.remove("hidden");
  const result = scan.result || {};
  if (scan.scan_type === "receipt") {
    root.innerHTML = `
      <div class="result-header"><div><h2>识别出 ${result.items?.length || 0} 个商品</h2><p>${escapeHtml(result.merchant || "商户待确认")} · 总计 ¥${Number(result.total || 0).toFixed(2)}</p></div><span class="confidence">置信度 ${Math.round((result.confidence || 0) * 100)}%</span></div>
      ${result.warnings?.length ? `<div class="warning-box">${result.warnings.map(escapeHtml).join("<br>")}</div>` : ""}
      <div class="result-meta"><label><span>购买日期</span><input id="purchaseDate" type="date" value="${escapeHtml(result.purchase_date || "")}"></label><label><span>商品数量</span><input value="${result.items?.length || 0} 项" disabled></label></div>
      <div id="candidateList" class="candidate-list">${(result.items || []).map((item, index) => candidateRow(item, index)).join("")}</div>
      <details class="raw-text"><summary>查看 OCR 原文</summary><pre>${escapeHtml(result.raw_text || "暂无 OCR 原文")}</pre></details>
      <div class="result-actions"><button class="outline-button" id="addCandidate">＋ 添加一行</button><button class="primary-button" id="confirmReceipt">确认并全部入库</button></div>`;
  } else if (scan.scan_type === "expiry") {
    const batchId = scan.batch_id || $("#expiryBatch").value;
    root.innerHTML = `
      <div class="result-header"><div><h2>日期识别候选</h2><p>请对照包装核对，确认后更新库存批次。</p></div><span class="confidence">置信度 ${Math.round((result.confidence || 0) * 100)}%</span></div>
      ${result.warnings?.length ? `<div class="warning-box">${result.warnings.map(escapeHtml).join("<br>")}</div>` : ""}
      <div class="expiry-fields">
        <label><span>生产日期 / MFG</span><input id="productionDate" type="date" value="${escapeHtml(result.production_date || "")}"></label>
        <label><span>到期日期 / EXP</span><input id="expiryDate" type="date" value="${escapeHtml(result.expiry_date || "")}"></label>
        <label><span>最佳食用期</span><input id="bestBeforeDate" type="date" value="${escapeHtml(result.best_before_date || "")}"></label>
        <label><span>保质期（天）</span><input id="shelfLifeDays" type="number" min="0" value="${escapeHtml(result.shelf_life_days ?? "")}"></label>
      </div>
      <input id="resultBatchId" type="hidden" value="${escapeHtml(batchId)}">
      <details class="raw-text" open><summary>OCR 原文与日期线索</summary><pre>${escapeHtml(result.raw_text || "暂无 OCR 原文，请手动填写")}</pre></details>
      <div class="result-actions"><span></span><button class="primary-button" id="confirmExpiry">确认更新日期</button></div>`;
  } else if (scan.scan_type === "ocr") {
    const lines = result.lines || [];
    const paragraphs = result.paragraphs || [];
    root.innerHTML = `
      <div class="result-header"><div><h2>识别出 ${result.line_count || lines.length || 0} 行文字</h2><p>引擎：${escapeHtml(scan.engine || result.engine || "未知")} · 耗时 ${escapeHtml(String(result.elapsed ?? "?"))} 秒</p></div><span class="confidence">置信度 ${Math.round((result.avg_confidence || 0) * 100)}%</span></div>
      ${result.warnings?.length ? `<div class="warning-box">${result.warnings.map(escapeHtml).join("<br>")}</div>` : ""}
      <div class="ocr-formatted-text"><pre>${escapeHtml(result.formatted_text || result.raw_text || "未识别到文字")}</pre></div>
      ${paragraphs.length > 1 ? `<details class="raw-text"><summary>段落结构（${paragraphs.length} 段）</summary><div class="ocr-paragraphs">${paragraphs.map((p, i) => `<div class="ocr-paragraph"><b>段落 ${i + 1}</b> <small>${p.line_count} 行</small><pre>${escapeHtml(p.text)}</pre></div>`).join("")}</div></details>` : ""}
      <details class="raw-text"><summary>逐行结果（${lines.length} 行）</summary><div class="ocr-line-list">${lines.map(ln => `<div class="ocr-line"><span class="ocr-line-text">${escapeHtml(ln.text)}</span><span class="ocr-line-conf">${Math.round((ln.confidence || 0) * 100)}%</span></div>`).join("")}</div></details>
      <div class="result-actions"><button class="outline-button" id="copyOcrText">复制全部文字</button><span></span></div>`;
  } else {
    const label = SCAN_CONFIG[scan.scan_type]?.label || "商品";
    const candidates = result.items?.length ? result.items : [{}];
    root.innerHTML = `
      <div class="result-header"><div><h2>${label}候选</h2><p>机器结果不会直接改库存，请核对名称、数量和到期日。</p></div><span class="confidence">置信度 ${Math.round((result.confidence || 0) * 100)}%</span></div>
      ${result.warnings?.length ? `<div class="warning-box">${result.warnings.map(escapeHtml).join("<br>")}</div>` : ""}
      <div class="result-meta"><label><span>入库日期</span><input id="purchaseDate" type="date" value="${escapeHtml(result.purchase_date || "")}"></label><label><span>识别方式</span><input value="${escapeHtml(scan.engine || "manual")}" disabled></label></div>
      <div id="candidateList" class="candidate-list">${candidates.map((item, index) => candidateRow(item, index, true)).join("")}</div>
      ${result.barcodes?.length ? `<details class="raw-text" open><summary>解码原文</summary><pre>${escapeHtml(result.barcodes.join("\n"))}</pre></details>` : ""}
      <div class="result-actions"><button class="outline-button" id="addDetailedCandidate">＋ 添加候选</button><button class="primary-button" id="confirmProducts">确认并加入库存</button></div>`;
  }
}

function candidateRow(item = {}, index = 0, detailed = false) {
  if (detailed) {
    const categories = ["乳品", "肉类", "蛋类", "蔬果", "烘焙", "粮油", "零食", "其他"];
    const units = ["份", "件", "盒", "瓶", "袋", "个", "克"];
    return `<div class="candidate-row detailed" data-index="${index}">
      <label><span>商品名称</span><input data-field="name" required value="${escapeHtml(item.name || "")}" placeholder="请确认商品名称"></label>
      <label><span>条形码（可选）</span><input data-field="barcode" inputmode="numeric" value="${escapeHtml(item.barcode || "")}" placeholder="7–14 位数字"></label>
      <label><span>数量</span><input data-field="quantity" type="number" min="0.01" step="0.01" value="${escapeHtml(item.quantity || 1)}"></label>
      <label><span>单位</span><select data-field="unit">${units.map(unit => `<option ${unit === (item.unit || "份") ? "selected" : ""}>${unit}</option>`).join("")}</select></label>
      <label><span>到期日期（可选）</span><input data-field="expiry_date" type="date" value="${escapeHtml(item.expiry_date || "")}"></label>
      <label><span>分类</span><select data-field="category">${categories.map(category => `<option ${category === (item.category || "其他") ? "selected" : ""}>${category}</option>`).join("")}</select></label>
      <label><span>单价（可选）</span><input data-field="unit_price" type="number" min="0" step="0.01" value="${escapeHtml(item.unit_price ?? "")}"></label>
      <button class="remove-candidate" data-remove-candidate aria-label="移除候选">×</button>
    </div>`;
  }
  return `<div class="candidate-row" data-index="${index}">
    <label><span>商品名称</span><input data-field="name" required value="${escapeHtml(item.name || "")}" placeholder="商品名称"></label>
    <label><span>数量</span><input data-field="quantity" type="number" min="0.01" step="0.01" value="${escapeHtml(item.quantity || 1)}"></label>
    <label><span>单价</span><input data-field="unit_price" type="number" min="0" step="0.01" value="${escapeHtml(item.unit_price ?? "")}"></label>
    <button class="remove-candidate" data-remove-candidate aria-label="移除候选">×</button>
    <input data-field="barcode" type="hidden" value="${escapeHtml(item.barcode || "")}">
    <input data-field="category" type="hidden" value="${escapeHtml(item.category || "其他")}">
    <input data-field="unit" type="hidden" value="${escapeHtml(item.unit || "件")}">
    <input data-field="expiry_date" type="hidden" value="${escapeHtml(item.expiry_date || "")}">
  </div>`;
}

function collectCandidateItems() {
  return $$("#candidateList .candidate-row").map(row => {
    const value = field => row.querySelector(`[data-field="${field}"]`)?.value || "";
    const price = value("unit_price");
    const quantity = Number(value("quantity") || 1);
    return {
      name: value("name").trim(),
      barcode: value("barcode").trim() || null,
      quantity,
      unit: value("unit") || "件",
      unit_price: price === "" ? null : Number(price),
      total_price: price === "" ? null : Number(price) * quantity,
      category: value("category") || "其他",
      expiry_date: value("expiry_date") || null,
    };
  }).filter(item => item.name);
}

async function confirmReceipt() {
  const items = collectCandidateItems();
  if (!items.length) return toast("至少保留一个商品候选", "error");
  showLoading("正在创建商品与库存批次…");
  try {
    const result = await api(`/api/scans/${state.currentScan.id}/confirm-receipt`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ purchase_date: $("#purchaseDate").value || null, items }),
    });
    state.currentScan.status = "confirmed";
    const existing = state.scans.find(item => item.id === state.currentScan.id);
    if (existing) existing.status = "confirmed";
    await refreshInventoryData();
    renderScanHistory();
    toast(`已创建 ${result.created_count} 个库存批次`);
    navigate("inventory");
  } catch (error) { toast(error.message, "error"); }
  finally { hideLoading(); }
}

async function confirmProducts() {
  const items = collectCandidateItems();
  if (!items.length) return toast("请先填写至少一个商品名称", "error");
  showLoading("正在创建商品与库存批次…");
  try {
    const result = await api(`/api/scans/${state.currentScan.id}/confirm-products`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ purchase_date: $("#purchaseDate").value || null, items }),
    });
    state.currentScan.status = "confirmed";
    const existing = state.scans.find(item => item.id === state.currentScan.id);
    if (existing) existing.status = "confirmed";
    await refreshInventoryData();
    renderScanHistory();
    toast(`已确认并创建 ${result.created_count} 个库存批次`);
    navigate("inventory");
  } catch (error) { toast(error.message, "error"); }
  finally { hideLoading(); }
}

async function confirmExpiry() {
  const batchId = Number($("#resultBatchId").value);
  if (!batchId) return toast("缺少库存批次，请重新选择", "error");
  showLoading("正在更新临期状态…");
  try {
    await api(`/api/scans/${state.currentScan.id}/confirm-expiry`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        batch_id: batchId,
        production_date: $("#productionDate").value || null,
        expiry_date: $("#expiryDate").value || null,
        best_before_date: $("#bestBeforeDate").value || null,
        shelf_life_days: $("#shelfLifeDays").value === "" ? null : Number($("#shelfLifeDays").value),
      }),
    });
    state.currentScan.status = "confirmed";
    const existing = state.scans.find(item => item.id === state.currentScan.id);
    if (existing) existing.status = "confirmed";
    await refreshInventoryData();
    renderScanHistory();
    toast("包装日期已更新");
    navigate("inventory");
  } catch (error) { toast(error.message, "error"); }
  finally { hideLoading(); }
}

function renderScanHistory() {
  const labels = { food: "食物照片", barcode: "商品条码", receipt: "购物小票", expiry: "包装日期", ocr: "OCR文字" };
  $("#scanHistory").innerHTML = state.scans.length ? state.scans.slice(0, 10).map(scan => `
    <article class="history-item" ${scan.status === "pending_confirmation" ? `data-open-scan="${scan.id}"` : ""}>
      <img src="${escapeHtml(scan.image_url)}" alt="${escapeHtml(scan.original_name)}">
      <div><b>${labels[scan.scan_type] || "图片识别"} · ${escapeHtml(scan.original_name)}</b><small>${new Date(scan.uploaded_at).toLocaleString("zh-CN")} · ${escapeHtml(scan.engine)}</small></div>
      <span class="status-chip ${scan.status}">${scan.status === "confirmed" ? "已确认" : "待确认"}</span>
    </article>`).join("") : '<div class="empty-state">还没有识别记录</div>';
}

async function openScan(scanId) {
  showLoading("正在载入识别结果…");
  try {
    const scan = await api(`/api/scans/${scanId}`);
    setScanType(scan.scan_type);
    if (scan.batch_id) populateBatchSelect(scan.batch_id);
    renderScanResult(scan);
    navigate("scan");
  } catch (error) { toast(error.message, "error"); }
  finally { hideLoading(); }
}

async function addManualInventory(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const payload = {
    product: { name: form.get("name"), category: form.get("category"), default_unit: form.get("unit") },
    quantity: Number(form.get("quantity")), unit: form.get("unit"),
    expiry_date: form.get("expiry_date") || null, storage_location: form.get("storage_location"),
  };
  showLoading("正在添加库存…");
  try {
    await api("/api/inventory", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    event.currentTarget.reset();
    event.currentTarget.classList.add("hidden");
    await refreshInventoryData();
    toast("已手动添加到库存");
  } catch (error) { toast(error.message, "error"); }
  finally { hideLoading(); }
}

async function consumeBatch(id, max) {
  const quantity = Math.min(1, Number(max));
  showLoading("正在记录使用流水…");
  try {
    await api(`/api/inventory/${id}/consume`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ quantity }) });
    await refreshInventoryData();
    toast(`已使用 ${quantity} 份库存`);
  } catch (error) { toast(error.message, "error"); }
  finally { hideLoading(); }
}

function askDiscard(id, name) {
  const dialog = $("#confirmDialog");
  $("#dialogTitle").textContent = "删除这批库存？";
  $("#dialogText").textContent = `${name} 的剩余数量会记为“丢弃”，流水仍会保留。`;
  dialog.showModal();
  dialog.addEventListener("close", async function handler() {
    dialog.removeEventListener("close", handler);
    if (dialog.returnValue !== "confirm") return;
    showLoading("正在记录丢弃流水…");
    try {
      await api(`/api/inventory/${id}`, { method: "DELETE" });
      await refreshInventoryData();
      toast("库存已移除，流水已保留");
    } catch (error) { toast(error.message, "error"); }
    finally { hideLoading(); }
  });
}

function startExpiryScan(batchId) {
  navigate("scan");
  setScanType("expiry");
  populateBatchSelect(batchId);
}

async function refreshScans() {
  try {
    const data = await api("/api/scans?limit=30");
    state.scans = data.items;
    renderScanHistory();
    renderDashboard();
  } catch (error) { toast(error.message, "error"); }
}

async function loadRecipes() {
  try {
    const data = await api(`/api/recipes/today?servings=${Number($("#servings").value) || 2}`);
    state.recipes = data.items;
    state.recipeSource = data.generated_by || "local-rules";
    renderRecipes();
    renderRecipeSummary();
  } catch (error) { toast(error.message, "error"); }
}

async function checkHealth() {
  try {
    await api("/api/health");
    $("#healthDot").classList.add("online");
    $("#healthText").textContent = "设备在线";
  } catch {
    $("#healthDot").classList.remove("online");
    $("#healthText").textContent = "设备离线";
  }
}

document.addEventListener("click", event => {
  const viewButton = event.target.closest("[data-view]");
  if (viewButton) navigate(viewButton.dataset.view);

  const filter = event.target.closest("[data-filter]");
  if (filter) {
    state.inventoryFilter = filter.dataset.filter;
    $$("[data-filter]").forEach(button => button.classList.toggle("active", button === filter));
    renderInventory();
  }
  const segment = event.target.closest("[data-scan-type]");
  if (segment) setScanType(segment.dataset.scanType);
  const cameraSegment = event.target.closest("[data-camera-scan-type]");
  if (cameraSegment) setCameraScanType(cameraSegment.dataset.cameraScanType);
  const remove = event.target.closest("[data-remove-candidate]");
  if (remove) remove.closest(".candidate-row").remove();
  const consume = event.target.closest("[data-consume]");
  if (consume) consumeBatch(consume.dataset.consume, consume.dataset.max);
  const expiry = event.target.closest("[data-expiry]");
  if (expiry) startExpiryScan(expiry.dataset.expiry);
  const discard = event.target.closest("[data-discard]");
  if (discard) askDiscard(discard.dataset.discard, discard.dataset.name);
  const openScanButton = event.target.closest("[data-open-scan]");
  if (openScanButton) openScan(openScanButton.dataset.openScan);
  if (event.target.closest("#addCandidate")) {
    const list = $("#candidateList");
    list.insertAdjacentHTML("beforeend", candidateRow({}, list.children.length));
  }
  if (event.target.closest("#addDetailedCandidate")) {
    const list = $("#candidateList");
    list.insertAdjacentHTML("beforeend", candidateRow({}, list.children.length, true));
  }
  if (event.target.closest("#confirmReceipt")) confirmReceipt();
  if (event.target.closest("#confirmProducts")) confirmProducts();
  if (event.target.closest("#confirmExpiry")) confirmExpiry();
  if (event.target.closest("#copyOcrText")) {
    const text = state.currentScan?.result?.formatted_text || state.currentScan?.result?.raw_text || "";
    if (text) {
      navigator.clipboard.writeText(text).then(
        () => toast("已复制到剪贴板"),
        () => toast("复制失败", "error")
      );
    }
  }
});

$("#quickScan").addEventListener("click", () => navigate("scan"));
$("#toggleManual").addEventListener("click", () => $("#manualForm").classList.toggle("hidden"));
$("#closeManual").addEventListener("click", () => $("#manualForm").classList.add("hidden"));
$("#manualForm").addEventListener("submit", addManualInventory);
$("#inventorySearch").addEventListener("input", event => { state.inventorySearch = event.target.value; renderInventory(); });
$("#scanFile").addEventListener("change", event => {
  state.selectedFile = event.target.files[0] || null;
  $("#analyzeButton").disabled = !state.selectedFile;
  if (!state.selectedFile) return $("#imagePreview").classList.add("hidden");
  $("#previewImg").src = URL.createObjectURL(state.selectedFile);
  $("#previewName").textContent = state.selectedFile.name;
  $("#previewSize").textContent = `${(state.selectedFile.size / 1024 / 1024).toFixed(2)} MB`;
  $("#imagePreview").classList.remove("hidden");
});
$("#analyzeButton").addEventListener("click", analyzeSelectedFile);
$("#demoScanButton").addEventListener("click", useDemoScan);
$("#refreshScans").addEventListener("click", refreshScans);
$("#servings").addEventListener("change", loadRecipes);
$("#cameraCaptureButton").addEventListener("click", captureFromUsbCamera);
$("#cameraStartBtn").addEventListener("click", startCamera);
$("#cameraDeviceSelect").addEventListener("change", () => {
  if (state.cameraStreamActive) {
    startCamera();
  }
});
// 摄像头来源切换
$$('[data-camera-source]').forEach(btn => {
  btn.addEventListener("click", () => setCameraSource(btn.dataset.cameraSource));
});
// 浏览器摄像头按钮
$("#browserCameraStartBtn").addEventListener("click", startBrowserCamera);
$("#browserCameraSwitchBtn").addEventListener("click", switchBrowserCamera);
$("#cameraExpiryBatch").addEventListener("change", () => {
  if (state.cameraScanType === "expiry" && $("#cameraExpiryBatch").value) syncCameraConfig().catch(error => toast(error.message, "error"));
});
$("#cameraEngineSelect").addEventListener("change", () => {
  state.cameraSelectedEngine = $("#cameraEngineSelect").value;
  if (ENGINE_TYPES.has(state.cameraScanType)) syncCameraConfig().catch(error => toast(error.message, "error"));
});
$("#engineSelect").addEventListener("change", () => {
  state.selectedEngine = $("#engineSelect").value;
});
$("#liveCameraStream").addEventListener("load", () => $("#cameraOffline").classList.add("hidden"));
$("#liveCameraStream").addEventListener("error", () => {
  $("#cameraOffline").classList.remove("hidden");
  state.cameraStreamActive = false;  // 允许下一次状态轮询自动重试拉流
  $("#liveCameraStream").dataset.active = "false";  // 同步重置 img 标记，否则重试被短路
});
// 物品计数控制
$("#counterFlipBtn").addEventListener("click", flipCounterLine);
$("#counterResetBtn").addEventListener("click", resetCounter);
$("#counterStream").addEventListener("error", () => {
  // 模式切换期间拉流会短暂 509，标记未激活以便轮询时自动重试
  const img = $("#counterStream");
  img.dataset.active = "false";
  $("#counterOffline").classList.remove("hidden");
});

checkHealth();
loadAll().catch(error => toast(`初始化失败：${error.message}`, "error"));
if ("serviceWorker" in navigator) window.addEventListener("load", () => navigator.serviceWorker.register("/service-worker.js").catch(() => {}));
