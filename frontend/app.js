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
  anchorData: {},
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
  quizBonus: 0,
  knowledgeData: [],
  currentKnowledge: null,
  isReport: false,
  isSound: false,
};

const dom = {
  sceneCount: document.getElementById("scene-count"),
  inventoryCount: document.getElementById("inventory-count"),
  sceneTitle: document.getElementById("scene-title"),
  sceneName: document.getElementById("scene-name"),
  panoramaName: document.getElementById("panorama-name"),
  sceneGroup: document.getElementById("scene-group"),
  sceneSeasons: document.getElementById("scene-seasons"),
  coordX: document.getElementById("coord-x"),
  coordY: document.getElementById("coord-y"),
  guessX: document.getElementById("guess-x"),
  guessY: document.getElementById("guess-y"),
  guessDistance: document.getElementById("guess-distance"),
  guessScore: document.getElementById("guess-score"),

  debugLevel: document.getElementById("debug-level"),
  debugTileList: document.getElementById("debug-tile-list"),
  viewerPlaceholder: document.querySelector(".viewer-placeholder"),
  viewerFrame: document.getElementById("viewer-frame"),
  viewerCanvas: document.getElementById("pannellum-viewer"),
  randomBtn: document.getElementById("random-btn"),
  viewerUsedCount: document.getElementById("viewer-used-count"),
  viewerUsedList: document.getElementById("viewer-used-list"),
  viewerMissingCount: document.getElementById("viewer-missing-count"),
  viewerMissingList: document.getElementById("viewer-missing-list"),
  mapBox: document.querySelector(".map-box"),
  mapPlaceholder: document.getElementById("map-placeholder"),
  miniMap: document.getElementById("mini-map"),
  mapRecenterBtn: document.getElementById("map-recenter-btn"),
  submitGuessBtn: document.getElementById("submit-guess-btn"),
  // 1.0 新增
  versionBadge: document.getElementById("version-badge"),
  scoreBoard: document.getElementById("score-board"),
  scoreCurrent: document.getElementById("score-current"),
  scoreRound: document.getElementById("score-round"),
  scoreTotal: document.getElementById("score-total"),
  scoreAvg: document.getElementById("score-avg"),
  nextRoundBtn: document.getElementById("next-round-btn"),
  quizZone: document.getElementById("quiz-zone"),
  seasonQuiz: document.getElementById("season-quiz"),
  seasonQuestion: document.getElementById("season-question"),
  seasonOptions: document.getElementById("season-options"),
  knowledgeQuiz: document.getElementById("knowledge-quiz"),
  knowledgeQuestion: document.getElementById("knowledge-question"),
  knowledgeOptions: document.getElementById("knowledge-options"),
  knowledgeFact: document.getElementById("knowledge-fact"),
  perfectToast: document.getElementById("perfect-toast"),
  confettiContainer: document.getElementById("confetti-container"),
  settingsFab: document.getElementById("settings-fab"),
  settingsPanel: document.getElementById("settings-panel"),
  reportFigureNav: document.getElementById("report-figure-nav"),
};

function normalizeTilePath(urlLike) {
  try {
    return new URL(String(urlLike), window.location.origin).pathname;
  } catch {
    return String(urlLike || "");
  }
}

function trackViewerTile(pathname) {
  const path = normalizeTilePath(pathname);
  if (!path.startsWith("/assets/viewer/panos/")) {
    return;
  }
  if (!window.__viewerUsedTileSet) {
    window.__viewerUsedTileSet = new Set();
  }
  if (!window.__viewerUsedTileOrder) {
    window.__viewerUsedTileOrder = [];
  }
  if (!window.__viewerUsedTileSet.has(path)) {
    window.__viewerUsedTileSet.add(path);
    window.__viewerUsedTileOrder.push(path);
  }
}

function installViewerUsageProbe() {
  if (window.__viewerUsageProbeInstalled) {
    return;
  }
  window.__viewerUsageProbeInstalled = true;
  window.__viewerUsedTileSet = window.__viewerUsedTileSet || new Set();
  window.__viewerUsedTileOrder = window.__viewerUsedTileOrder || [];

  const descriptor = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, "src");
  if (descriptor && descriptor.get && descriptor.set) {
    Object.defineProperty(HTMLImageElement.prototype, "src", {
      configurable: true,
      enumerable: descriptor.enumerable,
      get() {
        return descriptor.get.call(this);
      },
      set(value) {
        trackViewerTile(value);
        descriptor.set.call(this, value);
      },
    });
  }

  const originalSetAttribute = HTMLImageElement.prototype.setAttribute;
  HTMLImageElement.prototype.setAttribute = function patchedSetAttribute(name, value) {
    if (String(name).toLowerCase() === "src") {
      trackViewerTile(value);
    }
    return originalSetAttribute.call(this, name, value);
  };
}

function getUsedTilesForScene(scene) {
  if (!scene || !window.__viewerUsedTileOrder) {
    return [];
  }
  const oldPrefix = `/assets/viewer/panos/${scene.panorama_id}/${scene.pano_stub}/`;
  const krpanoPrefix = `/panoramas/${scene.panorama_id}/krpano/panos/${scene.pano_stub}.tiles/`;
  return window.__viewerUsedTileOrder.filter((path) => {
    if (!path.startsWith(oldPrefix) && !path.startsWith(krpanoPrefix)) {
      return false;
    }
    // Focus usage stats on highest-detail tiles only.
    return /\/l3\//.test(path) && /\.jpg$/.test(path);
  });
}

/** 将 API 里的 /assets/viewer/panos/... 转为 krpano 实际请求的 /panoramas/.../krpano/panos/*.tiles/... */
function viewerAliasToKrpanoTileUrl(legacyPath) {
  const m = legacyPath.match(
    /^\/assets\/viewer\/panos\/(\d+)\/([^/]+)\/(l\d)\/([fblrud])\/(\d+)\/(\d+)\.jpg$/,
  );
  if (!m) {
    return null;
  }
  const [, pid, stub, levelTag, face, rowStr, colStr] = m;
  const row = Number.parseInt(rowStr, 10);
  const col = Number.parseInt(colStr, 10);
  const vr = String(row + 1).padStart(2, "0");
  const vc = String(col + 1).padStart(2, "0");
  return `/panoramas/${pid}/krpano/panos/${stub}.tiles/${face}/${levelTag}/${vr}/${levelTag}_${face}_${vr}_${vc}.jpg`;
}

function getExpectedTilesForScene(scene) {
  // Keep expected/missing debug view only for synthetic debug scene.
  if (!scene || scene.scene_name !== "scene_debug_tiles") {
    return [];
  }
  if (!scene || !scene.viewer_debug_tile_urls) {
    return [];
  }
  const all = [];
  for (const face of ["f", "b", "l", "r", "u", "d"]) {
    for (const legacy of scene.viewer_debug_tile_urls[face] || []) {
      const k = viewerAliasToKrpanoTileUrl(legacy);
      if (k) {
        all.push(k);
      }
    }
  }
  return all;
}

function getMissingTilesForScene(scene) {
  const expected = getExpectedTilesForScene(scene);
  const used = new Set(getUsedTilesForScene(scene));
  return expected.filter((path) => !used.has(path));
}

function renderViewerUsedTiles(scene) {
  if (!dom.viewerUsedList || !dom.viewerUsedCount) {
    return;
  }
  const used = getUsedTilesForScene(scene);
  dom.viewerUsedCount.textContent = String(used.length);
  dom.viewerUsedList.innerHTML = "";
  for (const path of used.slice(0, 160)) {
    const link = document.createElement("a");
    link.href = path;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = path;
    dom.viewerUsedList.appendChild(link);
  }

  if (dom.viewerMissingList && dom.viewerMissingCount) {
    const missing = getMissingTilesForScene(scene);
    const expected = getExpectedTilesForScene(scene);
    if (expected.length === 0) {
      dom.viewerMissingCount.textContent = "-";
      dom.viewerMissingList.innerHTML = "";
    } else {
      dom.viewerMissingCount.textContent = String(missing.length);
      dom.viewerMissingList.innerHTML = "";
      for (const path of missing.slice(0, 220)) {
        const link = document.createElement("a");
        link.href = path;
        link.target = "_blank";
        link.rel = "noreferrer";
        link.textContent = path;
        dom.viewerMissingList.appendChild(link);
      }
    }
  }
}

function formatValue(value) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toFixed(6);
  }
  return String(value);
}

function renderDebugTiles(scene) {
  if (!dom.debugTileList) {
    return;
  }
  dom.debugTileList.innerHTML = "";
  const level = scene.viewer_source_level || "l3";
  if (dom.debugLevel) {
    dom.debugLevel.textContent = `${level} | ${scene.viewer_source_tile_rows || 0}x${scene.viewer_source_tile_cols || 0}`;
  }

  const debugUrls = scene.viewer_debug_tile_urls || {};
  for (const face of ["f", "b", "l", "r", "u", "d"]) {
    const urls = debugUrls[face] || [];
    const faceCard = document.createElement("section");
    faceCard.className = "debug-face-card";

    const heading = document.createElement("div");
    heading.className = "debug-face-head";
    heading.innerHTML = `<span>${face}</span><strong>${urls.length}</strong>`;
    faceCard.appendChild(heading);

    const grid = document.createElement("div");
    grid.className = "debug-url-grid";
    urls.forEach((url) => {
      const link = document.createElement("a");
      link.href = url;
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = url;
      grid.appendChild(link);
    });
    faceCard.appendChild(grid);
    dom.debugTileList.appendChild(faceCard);
  }
}

function clearViewer() {
  if (state.usedTilesPollTimer) {
    window.clearInterval(state.usedTilesPollTimer);
    state.usedTilesPollTimer = null;
  }
  if (window.removepano) {
    try {
      window.removepano(state.krpanoViewerId);
    } catch (error) {
      console.warn("remove krpano failed", error);
    }
  }
  state.viewer = null;
  dom.viewerCanvas.innerHTML = "";
}

const MAP_MAX_ZOOM = 5;
const MAP_MIN_ZOOM = 1;
const MAP_TILE_SIZE = 256;
const MAP_WORLD_SIZE = MAP_TILE_SIZE * 2 ** MAP_MAX_ZOOM;

function normalizeMapTransform(payload) {
  const affine = payload?.affine || payload?.transform || null;
  if (!affine) {
    return null;
  }
  const values = [affine.a, affine.b, affine.c, affine.d, affine.e, affine.f].map((v) => Number(v));
  if (values.some((v) => !Number.isFinite(v))) {
    return null;
  }
  const [a, b, c, d, e, f] = values;
  const det = a * e - b * d;
  if (Math.abs(det) < 1e-9) {
    return null;
  }
  return { a, b, c, d, e, f, det };
}

function applyCoordToMapPixel(coordX, coordY) {
  const x = Number(coordX);
  const y = Number(coordY);
  if (!Number.isFinite(x) || !Number.isFinite(y)) {
    return null;
  }
  const t = state.mapTransform;
  if (!t) {
    return null;
  }
  return {
    px: t.a * x + t.b * y + t.c,
    py: t.d * x + t.e * y + t.f,
  };
}

function applyMapPixelToCoord(pixelX, pixelY) {
  const px = Number(pixelX);
  const py = Number(pixelY);
  if (!Number.isFinite(px) || !Number.isFinite(py)) {
    return null;
  }
  const t = state.mapTransform;
  if (!t) {
    return null;
  }
  const dx = px - t.c;
  const dy = py - t.f;
  return {
    x: (t.e * dx - t.b * dy) / t.det,
    y: (-t.d * dx + t.a * dy) / t.det,
  };
}

function updateGuessDisplay(guess) {
  dom.guessX.textContent = guess ? formatValue(guess.x) : "-";
  dom.guessY.textContent = guess ? formatValue(guess.y) : "-";
}

function resetRoundResultDisplay() {
  if (dom.guessDistance) {
    dom.guessDistance.textContent = "-";
  }
  if (dom.guessScore) {
    dom.guessScore.textContent = "-";
  }
}

function scoreByDistance(distance) {
  if (!Number.isFinite(distance)) {
    return 0;
  }
  const knots = [
    { d: 5, s: 5000 },
    { d: 10, s: 4500 },
    { d: 20, s: 4000 },
    { d: 40, s: 3000 },
    { d: 80, s: 1500 },
    { d: 160, s: 750 },
  ];
  if (distance <= knots[0].d) {
    return 5000;
  }
  for (let i = 0; i < knots.length - 1; i += 1) {
    const a = knots[i];
    const b = knots[i + 1];
    if (distance <= b.d) {
      const t = (distance - a.d) / (b.d - a.d);
      return Math.round(a.s + t * (b.s - a.s));
    }
  }
  // Beyond 160 keep declining with last segment slope until 0.
  const tailSlope = (knots[5].s - knots[4].s) / (knots[5].d - knots[4].d); // -9.375
  const tail = knots[5].s + (distance - knots[5].d) * tailSlope;
  return Math.max(0, Math.round(tail));
}

function animateScoreDisplay(targetScore) {
  if (!dom.guessScore) {
    return;
  }
  if (state.scoreAnimId) {
    window.cancelAnimationFrame(state.scoreAnimId);
    state.scoreAnimId = null;
  }
  const start = Number(state.scoreValue) || 0;
  const end = Math.max(0, Math.min(5000, Number(targetScore) || 0));
  const durationMs = 550;
  const startAt = performance.now();

  function tick(now) {
    const t = Math.min(1, (now - startAt) / durationMs);
    const eased = 1 - (1 - t) ** 3;
    const current = Math.round(start + (end - start) * eased);
    dom.guessScore.textContent = `${current} / 5000`;
    if (t < 1) {
      state.scoreAnimId = window.requestAnimationFrame(tick);
    } else {
      state.scoreAnimId = null;
      state.scoreValue = end;
    }
  }

  state.scoreAnimId = window.requestAnimationFrame(tick);
}

/** 真值坐标优先级: user_x/y -> click_pixel_xy(仿射映射) -> x_axis/y_axis(fallback) */
function getSceneTruthCoord(scene) {
  if (!scene) return null;
  // 1) 锚点 user_x/user_y
  const ux = Number(scene.user_x), uy = Number(scene.user_y);
  if (Number.isFinite(ux) && Number.isFinite(uy)) return { x: ux, y: uy };
  // 2) click_pixel_xy 通过 per-pano affine 转 user coord
  const cpx = scene.click_pixel_xy;
  if (cpx && Array.isArray(cpx) && cpx.length === 2) {
    const perPano = state.perPanoTransforms?.[String(scene.panorama_id)];
    const t = perPano || state.mapTransform;
    if (t) {
      const pixel = { px: Number(cpx[0]), py: Number(cpx[1]) };
      if (Number.isFinite(pixel.px) && Number.isFinite(pixel.py)) {
        const coord = applyMapPixelToCoord(pixel.px, pixel.py);
        if (coord) return coord;
      }
    }
  }
  // 3) catalog x_axis/y_axis fallback
  const cx = Number(scene.coordinate_x), cy = Number(scene.coordinate_y);
  if (Number.isFinite(cx) && Number.isFinite(cy)) return { x: cx, y: cy };
  return null;
}

function updateScoreboardUI() {
  if (!dom.scoreRound) return;
  dom.scoreRound.textContent = String(state.roundNumber);
  dom.scoreTotal.textContent = String(state.totalScore);
  if (state.roundScores.length > 0) {
    dom.scoreAvg.textContent = Math.round(state.totalScore / state.roundScores.length) + " / 5000";
  }
}

function resetRoundState() {
  state.roundSubmitted = false;
  state.quizBonus = 0;
  state.currentKnowledge = null;
  state.scoreValue = 0;
  state.lastGuessCoord = null;
  state.lastGuessLatLng = null;
  if (state.guessLine) { state.guessLine.remove(); state.guessLine = null; }
  if (state.guessMarker) { state.guessMarker.remove(); state.guessMarker = null; }
  dom.submitGuessBtn.disabled = true;
  if (dom.quizZone) dom.quizZone.style.display = "none";
  if (dom.seasonQuiz) dom.seasonQuiz.style.display = "none";
  if (dom.knowledgeQuiz) dom.knowledgeQuiz.style.display = "none";
  // 不清零得分——保留上一轮成绩显示
}

// ---- 满分特效（方案 B） ----
function triggerPerfectEffects() {
  if (dom.scoreBoard) {
    dom.scoreBoard.classList.add("is-perfect");
    setTimeout(function () { dom.scoreBoard.classList.remove("is-perfect"); }, 3200);
  }
  if (dom.perfectToast) {
    dom.perfectToast.style.display = "block";
    dom.perfectToast.style.animation = "none";
    void dom.perfectToast.offsetWidth;
    dom.perfectToast.style.animation = "";
    setTimeout(function () { dom.perfectToast.style.display = "none"; }, 3200);
  }
  spawnConfetti();
  if (state.isSound || !state.isReport) playChime();
}

function spawnConfetti() {
  if (!dom.confettiContainer) return;
  dom.confettiContainer.style.display = "block";
  dom.confettiContainer.innerHTML = "";
  var colors = ["#f59e0b", "#fbbf24", "#fcd34d", "#22c55e", "#3b82f6", "#ef4444", "#a855f7"];
  for (var i = 0; i < 50; i++) {
    var piece = document.createElement("div");
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
  setTimeout(function () { dom.confettiContainer.style.display = "none"; dom.confettiContainer.innerHTML = ""; }, 3500);
}

function playChime() {
  try {
    var ctx = new (window.AudioContext || window.webkitAudioContext)();
    var notes = [523.25, 659.25, 783.99];
    notes.forEach(function (freq, i) {
      var osc = ctx.createOscillator();
      var gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.18, ctx.currentTime + i * 0.12);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + i * 0.12 + 0.5);
      osc.connect(gain).connect(ctx.destination);
      osc.start(ctx.currentTime + i * 0.12);
      osc.stop(ctx.currentTime + i * 0.12 + 0.5);
    });
  } catch (e) { /* silent */ }
}

function submitGuess() {
  if (!state.currentScene || !state.lastGuessCoord || !state.map || state.roundSubmitted) {
    return;
  }
  var truth = getSceneTruthCoord(state.currentScene);
  if (!truth || !state.lastGuessLatLng) return;

  var gx = Number(state.lastGuessCoord.x), gy = Number(state.lastGuessCoord.y);
  var tx = Number(truth.x), ty = Number(truth.y);
  if (![tx, ty, gx, gy].every(function (v) { return Number.isFinite(v); })) return;

  state.roundSubmitted = true;
  dom.submitGuessBtn.disabled = true;

  var distance = Math.hypot(gx - tx, gy - ty);
  var score = scoreByDistance(distance);

  // 绘制连线（用 truthMarker 的最新位置）
  if (state.truthMarker && state.guessMarker) {
    if (state.guessLine) state.guessLine.remove();
    state.guessLine = window.L.polyline([state.guessMarker.getLatLng(), state.truthMarker.getLatLng()], {
      color: "#f59e0b", weight: 3, opacity: 0.9, dashArray: "7 6",
    }).addTo(state.map);
  }

  if (dom.guessDistance) dom.guessDistance.textContent = distance.toFixed(2);
  if (dom.guessScore) animateScoreDisplay(score);

  // 满分检测
  if (score >= 5000) setTimeout(function () { triggerPerfectEffects(); }, 600);

  // 记录成绩
  state.roundScores.push(score);
  state.totalScore += score;
  state.roundNumber++;
  updateScoreboardUI();

  // 标记已玩 + 懒下载自动预取
  if (state.currentScene && state.currentScene.scene_name) {
    playedScenes[state.currentScene.scene_name] = true;
    markPlayedAndPrefetch(state.currentScene.scene_name);
  }

  // 出问答
  startQuizFlow();
}

// ---- 问答流程 ----
function startQuizFlow() {
  // 季节小问（40%概率）
  if (Math.random() < 0.4) { showSeasonQuiz(); } else { showKnowledgeQuiz(); }
}

function showSeasonQuiz() {
  var scene = state.currentScene;
  var correct = scene.season_hint || "summer";
  // 季节映射为中文
  var seasonMap = { spring: "春", summer: "夏", autumn: "秋", winter: "冬" };
  var correctCN = seasonMap[correct] || correct;
  var allSeasons = ["春", "夏", "秋", "冬"];
  allSeasons.sort(function () { return Math.random() - 0.5; });

  if (dom.seasonQuiz) dom.seasonQuiz.style.display = "block";
  if (dom.quizZone) dom.quizZone.style.display = "block";
  if (dom.seasonQuestion) dom.seasonQuestion.textContent = "这个场景拍摄于哪个季节？";
  if (dom.seasonOptions) {
    dom.seasonOptions.innerHTML = "";
    allSeasons.forEach(function (opt) {
      var btn = document.createElement("button");
      btn.textContent = opt;
      btn.addEventListener("click", function () {
        var isCorrect = opt === correctCN;
        dom.seasonOptions.querySelectorAll("button").forEach(function (b) { b.disabled = true; });
        if (!isCorrect) {
          btn.classList.add("is-wrong");
          // 标出正确答案
          dom.seasonOptions.querySelectorAll("button").forEach(function (b) {
            if (b.textContent === correctCN) b.classList.add("is-correct");
          });
        } else {
          btn.classList.add("is-correct");
          state.quizBonus += 500; state.totalScore += 500; updateScoreboardUI();
        }
        showKnowledgeQuiz();
      });
      dom.seasonOptions.appendChild(btn);
    });
  }
}

function showKnowledgeQuiz() {
  var scene = state.currentScene;
  if (!scene) return;
  var correct = scene.scene_title || scene.scene_name;
  var pool = state.scenes.filter(function (s) {
    return s.scene_name !== scene.scene_name && (s.scene_title || s.scene_name);
  });
  pool.sort(function () { return Math.random() - 0.5; });
  var distractors = pool.slice(0, 3).map(function (s) { return s.scene_title || s.scene_name; });
  var options = distractors.concat([correct]);
  options.sort(function () { return Math.random() - 0.5; });

  if (dom.knowledgeQuiz) dom.knowledgeQuiz.style.display = "block";
  if (dom.quizZone) dom.quizZone.style.display = "block";
  if (dom.knowledgeQuestion) dom.knowledgeQuestion.textContent = "这是哪个建筑？";
  if (dom.knowledgeOptions) {
    dom.knowledgeOptions.innerHTML = "";
    options.forEach(function (opt) {
      var btn = document.createElement("button");
      btn.textContent = opt;
      btn.addEventListener("click", function () {
        var isCorrect = opt === correct;
        dom.knowledgeOptions.querySelectorAll("button").forEach(function (b) { b.disabled = true; });
        if (!isCorrect) {
          btn.classList.add("is-wrong");
          // 标出正确答案
          dom.knowledgeOptions.querySelectorAll("button").forEach(function (b) {
            if (b.textContent === correct) b.classList.add("is-correct");
          });
        } else {
          btn.classList.add("is-correct");
          state.quizBonus += 500; state.totalScore += 500; updateScoreboardUI();
        }
        // 保留显示，不隐藏
      });
      dom.knowledgeOptions.appendChild(btn);
    });
  }
}

function getSceneFocusBounds() {
  if (!state.map || !state.mapTransform || !state.scenes.length) {
    return null;
  }
  const points = state.scenes
    .map((scene) => applyCoordToMapPixel(scene.coordinate_x, scene.coordinate_y))
    .filter((point) => point && Number.isFinite(point.px) && Number.isFinite(point.py));
  if (!points.length) {
    return null;
  }
  const xs = points.map((p) => p.px);
  const ys = points.map((p) => p.py);
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
  if (!state.map || !state.mapFocusBounds) {
    return;
  }
  state.map.fitBounds(state.mapFocusBounds, { animate: false, padding: [8, 8] });
}

function createDotIcon(className) {
  return window.L.divIcon({
    className: "",
    html: `<div class="${className}"></div>`,
    iconSize: [12, 12],
    iconAnchor: [6, 6],
  });
}

function installMiniMap() {
  if (!dom.miniMap || !window.L || state.map) {
    return;
  }
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
  if (state.mapFocusBounds) {
    recenterMiniMap();
  }
  state.map.on("click", (event) => {
    if (state.roundSubmitted) return; // 提交后不允许再选点
    const point = state.map.project(event.latlng, MAP_MAX_ZOOM);
    const guess = applyMapPixelToCoord(point.x, point.y);
    state.lastGuessCoord = guess;
    state.lastGuessLatLng = event.latlng;
    updateGuessDisplay(guess);
    resetRoundResultDisplay();
    if (state.guessLine) {
      state.guessLine.remove();
      state.guessLine = null;
    }
    if (state.guessMarker) {
      state.guessMarker.remove();
    }
    state.guessMarker = window.L.marker(event.latlng, {
      icon: createDotIcon("guess-dot"),
      title: "猜测点",
    }).addTo(state.map);
    dom.submitGuessBtn.disabled = false;
  });
  dom.mapBox?.classList.add("is-ready");
  if (dom.mapPlaceholder) {
    dom.mapPlaceholder.hidden = true;
  }
}

function renderMapForScene(scene) {
  if (!state.map) {
    return;
  }
  var truth = getSceneTruthCoord(scene);
  var pixel = truth ? applyCoordToMapPixel(truth.x, truth.y) : null;
  if (!pixel) {
    // fallback to catalog coords
    pixel = applyCoordToMapPixel(scene?.coordinate_x, scene?.coordinate_y);
  }
  if (!pixel) {
    return;
  }
  const latlng = state.map.unproject([pixel.px, pixel.py], MAP_MAX_ZOOM);
  if (state.truthMarker) {
    state.truthMarker.remove();
  }
  state.truthMarker = window.L.marker(latlng, {
    icon: createDotIcon("truth-dot"),
    title: "场景真值点",
  }).addTo(state.map);
  if (state.guessLine) {
    state.guessLine.remove();
    state.guessLine = null;
  }
}

function renderViewer(scene) {
  if (!window.embedpano) {
    dom.viewerCanvas.innerHTML = "<div class='viewer-error'>krpano 未加载，请检查运行时文件。</div>";
    return;
  }

  clearViewer();
  dom.viewerFrame.classList.remove("is-ready");
  dom.viewerFrame.classList.add("is-loading");

  const isDebug = scene.scene_name === "scene_debug_tiles";
  const tourXml = isDebug ? "/assets/debug_krpano_tour.xml" : "/assets/project_tour.xml";
  const startScene = isDebug ? "scene_debug_tiles" : scene.scene_name;

  try {
    window.embedpano({
      target: "pannellum-viewer",
      id: state.krpanoViewerId,
      xml: tourXml,
      html5: "only",
      mobilescale: 1.0,
      passQueryParameters: false,
      vars: {
        startscene: startScene,
      },
      onready(krpano) {
        state.viewer = krpano;
        // BLEND(0) 减少场景切换时的短暂黑屏
        krpano.call(`loadscene(${startScene}, null, MERGE, BLEND(0));`);
        dom.viewerFrame.classList.remove("is-loading");
        dom.viewerFrame.classList.add("is-ready");
        if (dom.viewerPlaceholder) {
          dom.viewerPlaceholder.hidden = true;
        }
      },
      onerror(message) {
        dom.viewerFrame.classList.remove("is-loading");
        dom.viewerFrame.classList.remove("is-ready");
        if (dom.viewerPlaceholder) {
          dom.viewerPlaceholder.hidden = false;
        }
        dom.viewerCanvas.innerHTML = `<div class='viewer-error'>${message}</div>`;
      },
    });
  } catch (error) {
    dom.viewerFrame.classList.remove("is-loading");
    dom.viewerFrame.classList.remove("is-ready");
    if (dom.viewerPlaceholder) {
      dom.viewerPlaceholder.hidden = false;
    }
    dom.viewerCanvas.innerHTML = `<div class='viewer-error'>${error.message}</div>`;
  }
}

function renderScene(scene) {
  state.currentScene = scene;
  resetRoundState();
  dom.sceneTitle.textContent = "故宫一景";
  state.scoreValue = 0;
  if (dom.guessScore) dom.guessScore.textContent = "-";
  renderViewer(scene);
  renderMapForScene(scene);
  // 停止之前的瓦片轮询
  if (state.usedTilesPollTimer) {
    window.clearInterval(state.usedTilesPollTimer);
    state.usedTilesPollTimer = null;
  }
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: {
      Accept: "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });
  if (!response.ok) {
    throw new Error(`请求失败: ${response.status}`);
  }
  return response.json();
}

// 已玩场景集合
var playedScenes = {};

async function loadScene(sceneName) {
  var scene = await requestJson("/api/scenes/" + encodeURIComponent(sceneName));
  renderScene(scene);
}

async function loadNextScene() {
  // 从未玩过的本地场景中选
  var localScenes = state.scenes.filter(function (s) {
    return (s.local_tile_count || 0) > 0 && s.scene_name !== "scene_debug_tiles";
  });
  var unplayed = localScenes.filter(function (s) {
    return !playedScenes[s.scene_name];
  });
  // 全玩过了就重置
  if (unplayed.length === 0) {
    playedScenes = {};
    unplayed = localScenes;
  }
  var pick = unplayed[Math.floor(Math.random() * unplayed.length)];
  renderScene(pick);
}

async function init() {
  // URL 参数
  var params = new URLSearchParams(window.location.search);
  state.isReport = params.get("report") === "1";
  state.isSound = params.get("sound") === "1";
  var figureIdx = parseInt(params.get("figure") || "0", 10);

  if (state.isReport) {
    document.body.classList.add("is-report-mode");
    document.title = "寻迹故宫 · 报告演示";
    if (dom.reportFigureNav) dom.reportFigureNav.style.display = "flex";
    if (dom.settingsFab) dom.settingsFab.style.display = "none";
  }
  if (dom.versionBadge) dom.versionBadge.textContent = "1.0";

  installViewerUsageProbe();
  var config = await requestJson("/api/config");
  var scenesResponse = await requestJson("/api/scenes");

  // 加载仿射变换（含 per-panorama）
  try {
    var transformPayload = await requestJson("/assets/map_transform.json");
    state.mapTransform = normalizeMapTransform(transformPayload);
    // per-pano transforms
    if (transformPayload && transformPayload.per_panorama) {
      state.perPanoTransforms = {};
      Object.keys(transformPayload.per_panorama).forEach(function (key) {
        var t = normalizeMapTransform({ affine: transformPayload.per_panorama[key].affine });
        if (t) state.perPanoTransforms[key] = t;
      });
    }
  } catch (e) {
    state.mapTransform = null;
  }

  state.scenes = scenesResponse.items || [];
  state.bounds = config.bounds;
  // 加载知识题库
  try {
    var knResp = await requestJson("/api/knowledge");
    state.knowledgeData = knResp.items || [];
  } catch (e) { state.knowledgeData = []; }
  state.mapFocusBounds = null;
  installMiniMap();
  if (!state.map && dom.mapPlaceholder) {
    dom.mapPlaceholder.innerHTML = "<p>地图运行时未加载（Leaflet 缺失）。</p><p>请先下载 /assets/vendor/leaflet.js。</p>";
  } else if (!state.mapTransform && dom.mapPlaceholder) {
    dom.mapPlaceholder.innerHTML = "<p>缺少 map_transform.json，地图仅显示底图。</p>";
    dom.mapPlaceholder.hidden = false;
    dom.mapBox?.classList.remove("is-ready");
  }

  dom.sceneCount.textContent = formatValue(scenesResponse.total);
  dom.inventoryCount.textContent = formatValue(config.playable_count || config.inventory_count);

  // 报告模式六景导航
  var REPORT_SCENES = ["太和殿", "中和殿", "保和殿", "箭亭", "神武门", "天一门"];
  if (state.isReport && dom.reportFigureNav) {
    dom.reportFigureNav.querySelectorAll("button").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var title = btn.textContent.trim();
        var found = state.scenes.find(function (s) { return (s.scene_title || s.scene_name) === title; });
        if (found) loadScene(found.scene_name);
      });
    });
  }

  // 初始场景
  var startScene = config.default_scene_name;
  if (state.isReport && figureIdx >= 1 && figureIdx <= 6) {
    var title = REPORT_SCENES[figureIdx - 1];
    var found = state.scenes.find(function (s) { return (s.scene_title || s.scene_name) === title; });
    if (found) startScene = found.scene_name;
  }
  if (startScene) {
    await loadScene(startScene);
    if (state.currentScene) playedScenes[state.currentScene.scene_name] = true;
  } else if (state.scenes.length > 0) {
    await loadNextScene();
    if (state.currentScene) playedScenes[state.currentScene.scene_name] = true;
  }

  // 事件绑定
  dom.mapRecenterBtn?.addEventListener("click", function () { recenterMiniMap(); });
  dom.submitGuessBtn?.addEventListener("click", submitGuess);

  // 下一题按钮（始终可见，替换原随机场景按钮）
  if (dom.nextRoundBtn) {
    dom.nextRoundBtn.addEventListener("click", async function () {
      dom.nextRoundBtn.disabled = true;
      dom.nextRoundBtn.textContent = "加载中...";
      try {
        await loadNextScene();
        if (state.currentScene) playedScenes[state.currentScene.scene_name] = true;
      } finally {
        dom.nextRoundBtn.disabled = false;
        dom.nextRoundBtn.textContent = "下一题";
      }
    });
  }

  // 设置面板
  setupSettingsPanel();
}

// ---- 设置面板 ----
function setupSettingsPanel() {
  if (!dom.settingsFab || !dom.settingsPanel) return;
  if (state.isReport) { dom.settingsFab.style.display = "none"; return; }

  var open = false;
  dom.settingsFab.addEventListener("click", function () {
    open = !open;
    dom.settingsPanel.style.display = open ? "block" : "none";
    if (open) refreshUsage();
  });

  document.getElementById("btn-refresh-usage")?.addEventListener("click", refreshUsage);
  document.getElementById("btn-prefetch")?.addEventListener("click", async function () {
    var btn = document.getElementById("btn-prefetch");
    if (!btn) return;
    btn.disabled = true; btn.textContent = "下载中...";
    try { await requestJson("/api/resources/prefetch"); await refreshUsage(); } catch (e) { console.warn(e); }
    btn.disabled = false; btn.textContent = "预下载 5 景";
  });
  document.getElementById("btn-prune-by-mb")?.addEventListener("click", async function () {
    var mb = parseFloat(document.getElementById("budget-mb")?.value || "500");
    if (!confirm("将清理至约 " + mb + " MB，继续？")) return;
    try {
      var result = await requestJson("/api/resources/prune?max_mb=" + mb);
      alert("已清理 " + result.pruned_count + " 个场景，释放 " + result.freed_mb + " MB");
      location.reload();
    } catch (e) { alert("清理失败: " + e.message); }
  });

  // 下载模式切换
  var modeSelect = document.getElementById("download-mode-select");
  if (modeSelect) {
    modeSelect.addEventListener("change", async function () {
      try {
        await fetch("/api/resources/config", {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({ download_mode: modeSelect.value }),
        });
      } catch (e) { console.warn(e); }
    });
  }
}

async function refreshUsage() {
  try {
    var data = await requestJson("/api/resources/status?usage=1");
    if (data.usage) {
      var u = data.usage;
      var el = function (id, v) { var e = document.getElementById(id); if (e) e.textContent = v; };
      el("stat-pano-mb", u.pano_mb + " MB");
      el("stat-other-mb", u.other_mb + " MB");
      el("stat-total-mb", u.total_mb + " MB");
      el("stat-playable", (data.unplayed_local_count || 0) + " / " + (data.playable_count || 0));
      el("stat-played", String(data.played_count || 0));
    }
    // 同步下载模式
    var cfg = await requestJson("/api/resources/config");
    var sel = document.getElementById("download-mode-select");
    if (sel && cfg.download_mode) sel.value = cfg.download_mode;
  } catch (e) { console.warn(e); }
}

// 标记已玩 + 懒下载自动预取
async function markPlayedAndPrefetch(sceneName) {
  try {
    await fetch("/api/resources/played", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ scene_name: sceneName }),
    });
  } catch (e) { /* silent */ }
  // 懒下载模式：剩余不足时自动触发
  try {
    var cfg = await requestJson("/api/resources/config");
    if (cfg.download_mode === "lazy") {
      var status = await requestJson("/api/resources/status");
      if ((status.unplayed_local_count || 0) < 5) {
        await requestJson("/api/resources/prefetch");
      }
    }
  } catch (e) { /* silent */ }
}

init().catch((error) => {
  console.error(error);
  document.body.insertAdjacentHTML(
    "afterbegin",
    `<div style="padding: 24px; color: #fee2e2; background: #7f1d1d; font-size: 14px;">初始化失败：${error.message}</div>`,
  );
});