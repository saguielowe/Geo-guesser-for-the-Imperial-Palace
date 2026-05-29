/* 寻迹故宫 · 1.0 — 游戏核心 */

// ---- 常量 ----
const PERFECT_SCORE = 5000;
const GAME_MODE = true; // true=游戏模式（隐藏 leak），false=调试模式
const REPORT_FIGURE_SCENES = [
  "太和殿", "中和殿", "保和殿",
  "箭亭", "神武门", "天一门",
];
const SEASON_QUIZ_PROB = 0.4; // 每题出现季节小问的概率

// ---- URL 参数 ----
const urlParams = new URLSearchParams(window.location.search);
const IS_REPORT = urlParams.get("report") === "1";
const IS_SOUND = urlParams.get("sound") === "1";
const IS_VERIFY = urlParams.get("verify") === "anchors";
const FIGURE_IDX = parseInt(urlParams.get("figure") || "0", 10);

// ---- 全局状态 ----
const state = {
  scenes: [],
  currentScene: null,
  bounds: null,
  viewer: null,
  map: null,
  mapLayer: null,
  truthMarker: null,
  guessMarker: null,
  guessLine: null,
  lastGuessCoord: null,
  lastGuessLatLng: null,
  mapTransform: null,
  perPanoTransforms: null,
  mapFocusBounds: null,
  scoreValue: 0,
  scoreAnimId: null,
  usedTilesPollTimer: null,
  krpanoViewerId: "krpano_viewer",

  // 游戏状态
  roundNumber: 0,
  totalScore: 0,
  roundScores: [],
  roundSubmitted: false,
  quizAnswered: { season: false, knowledge: false },
  quizBonus: { season: 0, knowledge: 0 },
  knowledgeData: [],
  currentKnowledge: null,
  catalogSource: "",
  playableCount: 0,
};

// ---- DOM 引用 ----
const dom = {
  // 顶栏
  headerPlayable: document.getElementById("header-playable"),
  reportFigureNav: document.getElementById("report-figure-nav"),

  // 全景
  viewerFrame: document.getElementById("viewer-frame"),
  viewerCanvas: document.getElementById("krpano_viewer"),
  viewerPlaceholder: document.querySelector(".viewer-placeholder"),

  // 计分
  scoreBoard: document.getElementById("score-board"),
  scoreCurrent: document.getElementById("score-current"),
  scoreRound: document.getElementById("score-round"),
  scoreTotal: document.getElementById("score-total"),
  scoreAvg: document.getElementById("score-avg"),

  // 控制
  submitGuessBtn: document.getElementById("submit-guess-btn"),
  nextRoundBtn: document.getElementById("next-round-btn"),

  // 地图
  mapBox: document.getElementById("map-box"),
  miniMap: document.getElementById("mini-map"),
  mapPlaceholder: document.getElementById("map-placeholder"),
  mapRecenterBtn: document.getElementById("map-recenter-btn"),

  // 场景信息
  sceneTitle: document.getElementById("scene-title"),
  sceneGroup: document.getElementById("scene-group"),

  // 问答
  quizZone: document.getElementById("quiz-zone"),
  seasonQuiz: document.getElementById("season-quiz"),
  seasonQuestion: document.getElementById("season-question"),
  seasonOptions: document.getElementById("season-options"),
  knowledgeQuiz: document.getElementById("knowledge-quiz"),
  knowledgeQuestion: document.getElementById("knowledge-question"),
  knowledgeOptions: document.getElementById("knowledge-options"),
  knowledgeFact: document.getElementById("knowledge-fact"),

  // 特效
  perfectToast: document.getElementById("perfect-toast"),
  confettiContainer: document.getElementById("confetti-container"),
  perfectMapRing: document.getElementById("perfect-map-ring"),

  // 设置
  settingsFab: document.getElementById("settings-fab"),
  settingsPanel: document.getElementById("settings-panel"),
  statPanoMb: document.getElementById("stat-pano-mb"),
  statOtherMb: document.getElementById("stat-other-mb"),
  statTotalMb: document.getElementById("stat-total-mb"),
  statPlayable: document.getElementById("stat-playable"),
  budgetMb: document.getElementById("budget-mb"),
  btnPrefetch: document.getElementById("btn-prefetch"),
  btnPruneByMb: document.getElementById("btn-prune-by-mb"),
  btnPruneByCount: document.getElementById("btn-prune-by-count"),
  btnRefreshUsage: document.getElementById("btn-refresh-usage"),
};

// ---- 地图常量 ----
const MAP_MAX_ZOOM = 5;
const MAP_MIN_ZOOM = 1;
const MAP_TILE_SIZE = 256;
const MAP_WORLD_SIZE = MAP_TILE_SIZE * 2 ** MAP_MAX_ZOOM;

// ---- 工具函数 ----
function formatValue(value) {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(4);
  return String(value);
}

async function requestJson(url, options = {}) {
  const resp = await fetch(url, {
    headers: { Accept: "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!resp.ok) throw new Error(`请求失败: ${resp.status}`);
  return resp.json();
}

// ---- 坐标系统 ----
function normalizeMapTransform(payload) {
  const affine = payload?.affine || payload?.transform || null;
  if (!affine) return null;
  const vals = [affine.a, affine.b, affine.c, affine.d, affine.e, affine.f].map(Number);
  if (vals.some(v => !Number.isFinite(v))) return null;
  const [a, b, c, d, e, f] = vals;
  const det = a * e - b * d;
  if (Math.abs(det) < 1e-9) return null;
  return { a, b, c, d, e, f, det };
}

function applyCoordToMapPixel(coordX, coordY, transform) {
  const t = transform || state.mapTransform;
  if (!t) return null;
  const x = Number(coordX), y = Number(coordY);
  if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
  return { px: t.a * x + t.b * y + t.c, py: t.d * x + t.e * y + t.f };
}

function applyMapPixelToCoord(pixelX, pixelY, transform) {
  const t = transform || state.mapTransform;
  if (!t) return null;
  const px = Number(pixelX), py = Number(pixelY);
  if (!Number.isFinite(px) || !Number.isFinite(py)) return null;
  const dx = px - t.c, dy = py - t.f;
  return { x: (t.e * dx - t.b * dy) / t.det, y: (-t.d * dx + t.a * dy) / t.det };
}

// 真值优先级: click_pixel_xy 仿射 → user_x/y → catalog 回退
function getSceneTruthCoord(scene) {
  if (!scene) return null;

  // 1) click_pixel_xy: 通过 per-pano affine 映射
  const cpx = scene.click_pixel_xy;
  if (cpx && Array.isArray(cpx) && cpx.length === 2) {
    const perPano = state.perPanoTransforms?.[scene.scene_name];
    if (perPano) {
      const pixel = applyCoordToMapPixel(cpx[0], cpx[1], perPano);
      if (pixel) {
        const coord = applyMapPixelToCoord(pixel.px, pixel.py);
        if (coord) return coord;
      }
    }
    // fallback with global transform
    const pixel = applyCoordToMapPixel(cpx[0], cpx[1], state.mapTransform);
    if (pixel) {
      const coord = applyMapPixelToCoord(pixel.px, pixel.py);
      if (coord) return coord;
    }
  }

  // 2) user_x / user_y 锚点
  const ux = Number(scene.user_x), uy = Number(scene.user_y);
  if (Number.isFinite(ux) && Number.isFinite(uy)) {
    return { x: ux, y: uy };
  }

  // 3) catalog 坐标回退
  const cx = Number(scene.coordinate_x), cy = Number(scene.coordinate_y);
  if (Number.isFinite(cx) && Number.isFinite(cy)) {
    return { x: cx, y: cy };
  }
  return null;
}

// ---- 计分 ----
function scoreByDistance(distance) {
  if (!Number.isFinite(distance)) return 0;
  const knots = [
    { d: 5, s: 5000 },
    { d: 10, s: 4500 },
    { d: 20, s: 4000 },
    { d: 40, s: 3000 },
    { d: 80, s: 1500 },
    { d: 160, s: 750 },
  ];
  if (distance <= knots[0].d) return 5000;
  for (let i = 0; i < knots.length - 1; i++) {
    const a = knots[i], b = knots[i + 1];
    if (distance <= b.d) {
      const t = (distance - a.d) / (b.d - a.d);
      return Math.round(a.s + t * (b.s - a.s));
    }
  }
  const tailSlope = (knots[5].s - knots[4].s) / (knots[5].d - knots[4].d);
  const tail = knots[5].s + (distance - knots[5].d) * tailSlope;
  return Math.max(0, Math.round(tail));
}

function animateScoreDisplay(targetScore) {
  if (state.scoreAnimId) { window.cancelAnimationFrame(state.scoreAnimId); state.scoreAnimId = null; }
  const start = Number(state.scoreValue) || 0;
  const end = Math.max(0, Math.min(5500, Number(targetScore) || 0));
  const durationMs = 550;
  const startAt = performance.now();

  function tick(now) {
    const t = Math.min(1, (now - startAt) / durationMs);
    const eased = 1 - (1 - t) ** 3;
    const current = Math.round(start + (end - start) * eased);
    dom.scoreCurrent.textContent = `${Math.min(current, PERFECT_SCORE)} / ${PERFECT_SCORE}`;
    if (t < 1) {
      state.scoreAnimId = window.requestAnimationFrame(tick);
    } else {
      state.scoreAnimId = null;
      state.scoreValue = Math.min(end, PERFECT_SCORE);
    }
  }
  state.scoreAnimId = window.requestAnimationFrame(tick);
}

function updateScoreboardUI() {
  dom.scoreRound.textContent = String(state.roundNumber);
  dom.scoreTotal.textContent = String(state.totalScore);
  const avg = state.roundScores.length > 0
    ? Math.round(state.totalScore / state.roundScores.length)
    : 0;
  dom.scoreAvg.textContent = `${avg} / ${PERFECT_SCORE}`;
}

// ---- 满分特效（方案 B） ----
function triggerPerfectEffects() {
  // 计分板金边
  dom.scoreBoard?.classList.add("is-perfect");
  setTimeout(() => dom.scoreBoard?.classList.remove("is-perfect"), 3200);

  // 横幅
  if (dom.perfectToast) {
    dom.perfectToast.style.display = "block";
    dom.perfectToast.style.animation = "none";
    void dom.perfectToast.offsetWidth;
    dom.perfectToast.style.animation = "";
    setTimeout(() => { dom.perfectToast.style.display = "none"; }, 3200);
  }

  // 纸屑
  spawnConfetti();

  // 地图涟漪
  if (dom.perfectMapRing && state.map && state.guessMarker) {
    const mapEl = dom.mapBox || dom.miniMap?.parentElement;
    if (mapEl) {
      const pos = state.map.latLngToContainerPoint(state.guessMarker.getLatLng());
      dom.perfectMapRing.style.display = "block";
      dom.perfectMapRing.style.left = pos.x + "px";
      dom.perfectMapRing.style.top = pos.y + "px";
      dom.perfectMapRing.style.animation = "none";
      void dom.perfectMapRing.offsetWidth;
      dom.perfectMapRing.style.animation = "mapRing 1.8s ease-out forwards";
      setTimeout(() => { dom.perfectMapRing.style.display = "none"; }, 2000);
    }
  }

  // Web Audio chime（报告模式默认静音）
  if (IS_SOUND || !IS_REPORT) {
    playChime();
  }
}

function spawnConfetti() {
  if (!dom.confettiContainer) return;
  dom.confettiContainer.style.display = "block";
  dom.confettiContainer.innerHTML = "";
  const colors = ["#f59e0b", "#fbbf24", "#fcd34d", "#22c55e", "#3b82f6", "#ef4444", "#a855f7"];
  for (let i = 0; i < 50; i++) {
    const piece = document.createElement("div");
    piece.className = "confetti-piece";
    piece.style.left = Math.random() * 100 + "%";
    piece.style.top = -(Math.random() * 40 + 10) + "px";
    piece.style.width = (Math.random() * 8 + 6) + "px";
    piece.style.height = (Math.random() * 8 + 6) + "px";
    piece.style.background = colors[Math.floor(Math.random() * colors.length)];
    piece.style.animationDelay = Math.random() * 0.6 + "s";
    piece.style.animationDuration = (Math.random() * 1.5 + 2) + "s";
    dom.confettiContainer.appendChild(piece);
  }
  setTimeout(() => {
    dom.confettiContainer.style.display = "none";
    dom.confettiContainer.innerHTML = "";
  }, 3500);
}

function playChime() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const notes = [523.25, 659.25, 783.99]; // C5, E5, G5
    notes.forEach((freq, i) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.18, ctx.currentTime + i * 0.12);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + i * 0.12 + 0.5);
      osc.connect(gain).connect(ctx.destination);
      osc.start(ctx.currentTime + i * 0.12);
      osc.stop(ctx.currentTime + i * 0.12 + 0.5);
    });
  } catch (e) { /* 静默 */ }
}

// ---- 全景 ----
function clearViewer() {
  if (state.usedTilesPollTimer) { window.clearInterval(state.usedTilesPollTimer); state.usedTilesPollTimer = null; }
  if (window.removepano) {
    try { window.removepano(state.krpanoViewerId); } catch (e) { /* */ }
  }
  state.viewer = null;
  if (dom.viewerCanvas) dom.viewerCanvas.innerHTML = "";
}

function renderViewer(scene) {
  if (!window.embedpano) {
    if (dom.viewerCanvas) dom.viewerCanvas.innerHTML = "<div style='padding:24px;color:#fecaca;text-align:center'>krpano 未加载</div>";
    return;
  }
  clearViewer();
  if (dom.viewerFrame) {
    dom.viewerFrame.classList.remove("is-ready");
    dom.viewerFrame.classList.add("is-loading");
  }

  const isDebug = scene.scene_name === "scene_debug_tiles";
  const tourXml = isDebug ? "/assets/debug_krpano_tour.xml" : "/assets/project_tour.xml";
  const startScene = isDebug ? "scene_debug_tiles" : scene.scene_name;

  try {
    window.embedpano({
      target: state.krpanoViewerId,
      id: state.krpanoViewerId,
      xml: tourXml,
      html5: "only",
      mobilescale: 1.0,
      passQueryParameters: false,
      vars: { startscene: startScene },
      onready(krpano) {
        state.viewer = krpano;
        krpano.call(`loadscene(${startScene}, null, MERGE, BLEND(0));`);
        if (dom.viewerFrame) {
          dom.viewerFrame.classList.remove("is-loading");
          dom.viewerFrame.classList.add("is-ready");
        }
        if (dom.viewerPlaceholder) dom.viewerPlaceholder.hidden = true;
      },
      onerror(msg) {
        if (dom.viewerFrame) {
          dom.viewerFrame.classList.remove("is-loading", "is-ready");
        }
        if (dom.viewerPlaceholder) dom.viewerPlaceholder.hidden = false;
        if (dom.viewerCanvas) dom.viewerCanvas.innerHTML = `<div style="padding:24px;color:#fecaca;text-align:center">${msg}</div>`;
      },
    });
  } catch (e) {
    if (dom.viewerFrame) dom.viewerFrame.classList.remove("is-loading", "is-ready");
    if (dom.viewerPlaceholder) dom.viewerPlaceholder.hidden = false;
    if (dom.viewerCanvas) dom.viewerCanvas.innerHTML = `<div style="padding:24px;color:#fecaca;text-align:center">${e.message}</div>`;
  }
}

// ---- 地图 ----
function createDotIcon(className) {
  return window.L.divIcon({
    className: "",
    html: `<div class="${className}"></div>`,
    iconSize: [12, 12],
    iconAnchor: [6, 6],
  });
}

function getSceneFocusBounds() {
  if (!state.map || !state.mapTransform || !state.scenes.length) return null;
  const points = state.scenes
    .map(s => applyCoordToMapPixel(s.coordinate_x, s.coordinate_y))
    .filter(p => p && Number.isFinite(p.px) && Number.isFinite(p.py));
  if (!points.length) return null;
  const xs = points.map(p => p.px), ys = points.map(p => p.py);
  const pad = 180;
  const minX = Math.max(0, Math.min(...xs) - pad);
  const maxX = Math.min(MAP_WORLD_SIZE, Math.max(...xs) + pad);
  const minY = Math.max(0, Math.min(...ys) - pad);
  const maxY = Math.min(MAP_WORLD_SIZE, Math.max(...ys) + pad);
  const sw = state.map.unproject([minX, maxY], MAP_MAX_ZOOM);
  const ne = state.map.unproject([maxX, minY], MAP_MAX_ZOOM);
  return window.L.latLngBounds(sw, ne);
}

function recenterMiniMap() {
  if (!state.map || !state.mapFocusBounds) return;
  state.map.fitBounds(state.mapFocusBounds, { animate: false, padding: [8, 8] });
}

function installMiniMap() {
  if (!dom.miniMap || !window.L || state.map) return;
  state.map = window.L.map(dom.miniMap, {
    crs: window.L.CRS.Simple,
    center: [0, 0],
    zoom: MAP_MIN_ZOOM,
    minZoom: MAP_MIN_ZOOM,
    maxZoom: MAP_MAX_ZOOM,
    zoomSnap: 0.1,
    zoomDelta: 0.2,
    wheelPxPerZoomLevel: 120,
    attributionControl: false,
    zoomControl: false,
    preferCanvas: true,
  });
  const southWest = state.map.unproject([0, MAP_WORLD_SIZE], MAP_MAX_ZOOM);
  const northEast = state.map.unproject([MAP_WORLD_SIZE, 0], MAP_MAX_ZOOM);
  const mapBounds = window.L.latLngBounds(southWest, northEast);
  state.mapLayer = window.L.tileLayer("/assets/leaflet/tiles/{z}/tile_{x}_{y}.png", {
    minZoom: MAP_MIN_ZOOM,
    maxZoom: MAP_MAX_ZOOM,
    tileSize: MAP_TILE_SIZE,
    noWrap: true,
    bounds: mapBounds,
  });
  state.mapLayer.addTo(state.map);
  state.map.fitBounds(mapBounds, { animate: false, padding: [8, 8] });
  state.map.setMaxBounds(mapBounds.pad(0.25));
  state.map.invalidateSize();
  state.mapFocusBounds = getSceneFocusBounds();
  if (state.mapFocusBounds) recenterMiniMap();

  state.map.on("click", (event) => {
    if (state.roundSubmitted) return; // 已提交则不可改点
    const point = state.map.project(event.latlng, MAP_MAX_ZOOM);
    const guess = applyMapPixelToCoord(point.x, point.y);
    state.lastGuessCoord = guess;
    state.lastGuessLatLng = event.latlng;
    if (state.guessLine) { state.guessLine.remove(); state.guessLine = null; }
    if (state.guessMarker) state.guessMarker.remove();
    state.guessMarker = window.L.marker(event.latlng, {
      icon: createDotIcon("guess-dot"),
      title: "猜测点",
    }).addTo(state.map);
    dom.submitGuessBtn.disabled = false;
  });

  dom.mapBox?.classList.add("is-ready");
  if (dom.mapPlaceholder) dom.mapPlaceholder.hidden = true;
}

function renderMapForScene(scene) {
  if (!state.map) return;
  const truth = getSceneTruthCoord(scene);
  if (!truth) return;
  const pixel = applyCoordToMapPixel(truth.x, truth.y);
  if (!pixel) return;
  const latlng = state.map.unproject([pixel.px, pixel.py], MAP_MAX_ZOOM);
  if (state.truthMarker) state.truthMarker.remove();
  state.truthMarker = window.L.marker(latlng, {
    icon: createDotIcon("truth-dot"),
    title: "场景真值点",
  }).addTo(state.map);
  if (state.guessLine) { state.guessLine.remove(); state.guessLine = null; }
  if (state.guessMarker) { state.guessMarker.remove(); state.guessMarker = null; }
}

// ---- 回合流程 ----
function submitGuess() {
  if (!state.currentScene || !state.lastGuessCoord || !state.map || state.roundSubmitted) return;
  const truth = getSceneTruthCoord(state.currentScene);
  if (!truth) return;

  const gx = Number(state.lastGuessCoord.x), gy = Number(state.lastGuessCoord.y);
  const tx = Number(truth.x), ty = Number(truth.y);
  if (![gx, gy, tx, ty].every(v => Number.isFinite(v))) return;

  state.roundSubmitted = true;
  dom.submitGuessBtn.disabled = true;

  const distance = Math.hypot(gx - tx, gy - ty);
  const baseScore = scoreByDistance(distance);

  // 绘制连线
  if (state.guessMarker && state.truthMarker) {
    state.guessLine = window.L.polyline(
      [state.guessMarker.getLatLng(), state.truthMarker.getLatLng()],
      { color: "#f59e0b", weight: 3, opacity: 0.9, dashArray: "7 6" }
    ).addTo(state.map);
  }

  // 动画计分
  animateScoreDisplay(baseScore);
  state.scoreValue = baseScore;

  // 满分检测
  if (baseScore >= PERFECT_SCORE) {
    setTimeout(() => triggerPerfectEffects(), 600);
  }

  // 进入问答阶段
  setTimeout(() => startQuizPhase(baseScore), 800);
}

function startQuizPhase(baseScore) {
  // 季节小问
  if (Math.random() < SEASON_QUIZ_PROB && state.currentScene?.seasons?.length > 1) {
    showSeasonQuiz(baseScore);
  } else {
    showKnowledgeQuiz(baseScore);
  }
}

function showSeasonQuiz(baseScore) {
  const seasons = state.currentScene.seasons || [];
  const correct = state.currentScene.season_hint || seasons[0];
  dom.seasonQuiz.style.display = "block";
  dom.quizZone.style.display = "flex";
  dom.seasonQuestion.textContent = `这个场景是哪个季节拍摄的？`;
  dom.seasonOptions.innerHTML = "";
  const options = [...new Set(seasons)].sort(() => Math.random() - 0.5);
  options.forEach(opt => {
    const btn = document.createElement("button");
    btn.textContent = opt;
    btn.addEventListener("click", () => {
      const isCorrect = opt === correct;
      btn.classList.add(isCorrect ? "is-correct" : "is-wrong");
      dom.seasonOptions.querySelectorAll("button").forEach(b => b.disabled = true);
      state.quizAnswered.season = true;
      if (isCorrect) state.quizBonus.season = 500;
      setTimeout(() => {
        dom.seasonQuiz.style.display = "none";
        showKnowledgeQuiz(baseScore);
      }, 1000);
    });
    dom.seasonOptions.appendChild(btn);
  });
}

function showKnowledgeQuiz(baseScore) {
  const kn = state.currentKnowledge;
  if (!kn || !kn.question) {
    finishRound(baseScore);
    return;
  }
  dom.knowledgeQuiz.style.display = "block";
  dom.quizZone.style.display = "flex";
  dom.knowledgeQuestion.textContent = kn.question;
  dom.knowledgeOptions.innerHTML = "";
  dom.knowledgeFact.style.display = "none";

  const options = [...(kn.options || [])];
  if (!options.includes(kn.answer)) options.push(kn.answer);
  options.sort(() => Math.random() - 0.5);

  options.forEach(opt => {
    const btn = document.createElement("button");
    btn.textContent = opt;
    btn.addEventListener("click", () => {
      const isCorrect = opt === kn.answer;
      btn.classList.add(isCorrect ? "is-correct" : "is-wrong");
      dom.knowledgeOptions.querySelectorAll("button").forEach(b => b.disabled = true);
      state.quizAnswered.knowledge = true;
      if (isCorrect) state.quizBonus.knowledge = 500;
      if (kn.fact) {
        dom.knowledgeFact.textContent = `💡 ${kn.fact}`;
        dom.knowledgeFact.style.display = "block";
      }
      setTimeout(() => {
        dom.knowledgeQuiz.style.display = "none";
        finishRound(baseScore);
      }, 1800);
    });
    dom.knowledgeOptions.appendChild(btn);
  });
}

function finishRound(baseScore) {
  const bonus = (state.quizBonus.season || 0) + (state.quizBonus.knowledge || 0);
  const totalRound = Math.min(baseScore + bonus, PERFECT_SCORE);
  if (bonus > 0 && state.scoreValue > 0) {
    state.scoreValue = totalRound;
    dom.scoreCurrent.textContent = `${totalRound} / ${PERFECT_SCORE}`;
  }

  state.roundScores.push(totalRound);
  state.totalScore += totalRound;
  state.roundNumber++;
  updateScoreboardUI();

  dom.nextRoundBtn.style.display = "block";
  dom.quizZone.style.display = "none";
}

function resetRound() {
  state.roundSubmitted = false;
  state.quizAnswered = { season: false, knowledge: false };
  state.quizBonus = { season: 0, knowledge: 0 };
  state.currentKnowledge = null;
  state.scoreValue = 0;
  state.lastGuessCoord = null;
  state.lastGuessLatLng = null;

  if (state.guessLine) { state.guessLine.remove(); state.guessLine = null; }
  if (state.guessMarker) { state.guessMarker.remove(); state.guessMarker = null; }

  dom.submitGuessBtn.disabled = true;
  dom.nextRoundBtn.style.display = "none";
  dom.scoreCurrent.textContent = `0 / ${PERFECT_SCORE}`;
  dom.seasonQuiz.style.display = "none";
  dom.knowledgeQuiz.style.display = "none";
  dom.quizZone.style.display = "none";
}

// ---- 场景加载 ----
function renderScene(scene) {
  state.currentScene = scene;
  resetRound();

  dom.sceneTitle.textContent = scene.scene_title || scene.scene_name || "未命名";
  dom.sceneGroup.textContent = scene.scene_group_name || "";

  // 查知识题
  const knItems = state.knowledgeData.filter(
    k => k.scene_name === scene.scene_name
  );
  state.currentKnowledge = knItems.length > 0
    ? knItems[Math.floor(Math.random() * knItems.length)]
    : null;

  renderViewer(scene);
  renderMapForScene(scene);

  // 报告模式六景按钮高亮
  if (IS_REPORT && dom.reportFigureNav) {
    const idx = REPORT_FIGURE_SCENES.indexOf(scene.scene_title || scene.scene_name);
    dom.reportFigureNav.querySelectorAll("button").forEach((b, i) => {
      b.classList.toggle("is-active", i + 1 === idx || b.textContent === (scene.scene_title || scene.scene_name));
    });
  }
}

async function loadScene(sceneName) {
  const scene = await requestJson(`/api/scenes/${encodeURIComponent(sceneName)}`);
  renderScene(scene);
}

async function loadRandomScene() {
  // 仅从本地已缓存中随机
  const localNames = state.scenes
    .filter(s => (s.local_tile_count || 0) > 0 && s.scene_name !== "scene_debug_tiles")
    .map(s => s.scene_name);
  if (localNames.length === 0) {
    // fallback to any
    const scene = await requestJson("/api/scenes/random");
    renderScene(scene);
    return;
  }
  const name = localNames[Math.floor(Math.random() * localNames.length)];
  await loadScene(name);
}

// ---- 设置面板 ----
async function refreshUsageUI() {
  try {
    const data = await requestJson("/api/resources/status?usage=1");
    if (data.usage) {
      dom.statPanoMb.textContent = data.usage.pano_mb + " MB";
      dom.statOtherMb.textContent = data.usage.other_mb + " MB";
      dom.statTotalMb.textContent = data.usage.total_mb + " MB";
    }
    dom.statPlayable.textContent = String(data.playable_count || 0);
    dom.headerPlayable.textContent = `可玩: ${data.playable_count || 0} | 题库: ${data.catalog_source || "--"}`;
  } catch (e) {
    console.warn("usage refresh failed", e);
  }
}

function setupSettingsPanel() {
  if (IS_REPORT) {
    dom.settingsFab.style.display = "none";
    return;
  }

  let panelOpen = false;
  dom.settingsFab.addEventListener("click", () => {
    panelOpen = !panelOpen;
    dom.settingsPanel.style.display = panelOpen ? "block" : "none";
    if (panelOpen) refreshUsageUI();
  });

  dom.btnRefreshUsage?.addEventListener("click", async () => {
    try {
      await requestJson("/api/resources/refresh");
      await refreshUsageUI();
    } catch (e) { console.warn(e); }
  });

  dom.btnPrefetch?.addEventListener("click", async () => {
    try {
      dom.btnPrefetch.disabled = true;
      dom.btnPrefetch.textContent = "下载中…";
      await requestJson("/api/resources/prefetch");
      await refreshUsageUI();
    } catch (e) { console.warn(e); }
    finally {
      dom.btnPrefetch.disabled = false;
      dom.btnPrefetch.textContent = "预下载 5 景";
    }
  });

  dom.btnPruneByMb?.addEventListener("click", async () => {
    const mb = parseFloat(dom.budgetMb?.value || "500");
    if (!confirm(`将清理至约 ${mb} MB，继续？`)) return;
    try {
      const result = await requestJson(`/api/resources/prune?max_mb=${mb}`);
      alert(`已清理 ${result.pruned_count} 个场景，释放 ${result.freed_mb} MB`);
      location.reload();
    } catch (e) { alert("清理失败: " + e.message); }
  });

  dom.btnPruneByCount?.addEventListener("click", async () => {
    if (!confirm("将仅保留 10 个场景，继续？")) return;
    try {
      const result = await requestJson("/api/resources/prune?max_scenes=10");
      alert(`已清理 ${result.pruned_count} 个场景，释放 ${result.freed_mb} MB`);
      location.reload();
    } catch (e) { alert("清理失败: " + e.message); }
  });
}

// ---- 报告模式六景导航 ----
function setupReportNav() {
  if (!IS_REPORT || !dom.reportFigureNav) return;
  dom.reportFigureNav.style.display = "flex";
  dom.reportFigureNav.querySelectorAll("button").forEach(btn => {
    btn.addEventListener("click", () => {
      const title = btn.textContent.trim();
      const scene = state.scenes.find(
        s => (s.scene_title || s.scene_name) === title
      );
      if (scene) loadScene(scene.scene_name);
    });
  });
}

// ---- 初始化 ----
async function init() {
  document.body.classList.add("is-loading");

  // 报告模式
  if (IS_REPORT) {
    document.body.classList.add("is-report-mode");
    document.title = "寻迹故宫 · 报告演示";
  }

  // 加载配置
  const config = await requestJson("/api/config");
  const scenesResp = await requestJson("/api/scenes");
  state.scenes = scenesResp.items || [];
  state.bounds = config.bounds;
  state.playableCount = config.playable_count || 0;
  state.catalogSource = config.catalog_source || "unknown";

  // 加载地图变换
  try {
    const transformPayload = await requestJson("/assets/map_transform.json");
    state.mapTransform = normalizeMapTransform(transformPayload);
    // per-panorama transforms
    if (transformPayload?.per_panorama) {
      state.perPanoTransforms = {};
      for (const [key, val] of Object.entries(transformPayload.per_panorama)) {
        const t = normalizeMapTransform(val);
        if (t) state.perPanoTransforms[key] = t;
      }
    }
  } catch (e) {
    state.mapTransform = null;
  }

  // 加载知识库
  try {
    const knResp = await requestJson("/api/knowledge");
    state.knowledgeData = knResp.items || [];
  } catch (e) {
    state.knowledgeData = [];
  }

  // 安装地图
  installMiniMap();

  // 更新顶栏
  dom.headerPlayable.textContent = `可玩: ${state.playableCount} | 题库: ${state.catalogSource}`;

  // 设置面板
  setupSettingsPanel();

  // 报告模式六景导航
  setupReportNav();

  // 加载初始场景
  let startScene = config.default_scene_name;
  if (IS_REPORT && FIGURE_IDX >= 1 && FIGURE_IDX <= 6) {
    const title = REPORT_FIGURE_SCENES[FIGURE_IDX - 1];
    const found = state.scenes.find(s => (s.scene_title || s.scene_name) === title);
    if (found) startScene = found.scene_name;
  }

  if (startScene) {
    await loadScene(startScene);
  } else if (state.scenes.length > 0) {
    await loadRandomScene();
  }

  // 事件绑定
  dom.submitGuessBtn?.addEventListener("click", submitGuess);
  dom.nextRoundBtn?.addEventListener("click", async () => {
    dom.nextRoundBtn.disabled = true;
    dom.nextRoundBtn.textContent = "加载中…";
    try {
      await loadRandomScene();
    } finally {
      dom.nextRoundBtn.disabled = false;
      dom.nextRoundBtn.textContent = "下一题";
    }
  });
  dom.mapRecenterBtn?.addEventListener("click", recenterMiniMap);

  document.body.classList.remove("is-loading");

  // 非报告模式：低题量 prefetch
  if (!IS_REPORT && state.playableCount < 10) {
    try { await requestJson("/api/resources/prefetch"); } catch (e) { /* */ }
  }
}

init().catch(err => {
  console.error(err);
  document.body.insertAdjacentHTML("afterbegin",
    `<div style="padding:24px;color:#fee2e2;background:#7f1d1d;font-size:14px;position:fixed;top:0;left:0;right:0;z-index:9999">初始化失败：${err.message}</div>`
  );
});
