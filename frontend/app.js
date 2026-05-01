const state = {
  scenes: [],
  currentScene: null,
  bounds: null,
  viewer: null,
  map: null,
  mapLayer: null,
  truthMarker: null,
  guessMarker: null,
  lastGuessCoord: null,
  mapTransform: null,
  mapPickMode: false,
  anchorSamples: [],
  mapFocusBounds: null,
  usedTilesPollTimer: null,
  krpanoViewerId: "krpano_viewer",
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
  boundsX: document.getElementById("bounds-x"),
  boundsY: document.getElementById("bounds-y"),
  guessX: document.getElementById("guess-x"),
  guessY: document.getElementById("guess-y"),

  debugLevel: document.getElementById("debug-level"),
  debugTileList: document.getElementById("debug-tile-list"),
  sceneList: document.getElementById("scene-list"),
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
  anchorModeBtn: document.getElementById("anchor-mode-btn"),
  anchorOutput: document.getElementById("anchor-output"),
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

function renderSceneList() {
  dom.sceneList.innerHTML = "";
  state.scenes.slice(0, 12).forEach((scene) => {
    const button = document.createElement("button");
    button.className = "scene-chip";
    button.type = "button";
    button.textContent = scene.scene_title || scene.scene_name;
    button.title = scene.scene_name;
    button.addEventListener("click", () => loadScene(scene.scene_name));
    dom.sceneList.appendChild(button);
  });
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

function updateAnchorOutput() {
  if (!dom.anchorOutput) {
    return;
  }
  dom.anchorOutput.value = JSON.stringify(state.anchorSamples, null, 2);
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

function setMapPickMode(enabled) {
  state.mapPickMode = Boolean(enabled);
  if (dom.anchorModeBtn) {
    dom.anchorModeBtn.textContent = `采点模式：${state.mapPickMode ? "开" : "关"}`;
    dom.anchorModeBtn.classList.toggle("is-active", state.mapPickMode);
  }
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
    const point = state.map.project(event.latlng, MAP_MAX_ZOOM);
    const guess = applyMapPixelToCoord(point.x, point.y);
    state.lastGuessCoord = guess;
    updateGuessDisplay(guess);
    if (state.guessMarker) {
      state.guessMarker.remove();
    }
    state.guessMarker = window.L.marker(event.latlng, {
      icon: createDotIcon("guess-dot"),
      title: "猜测点",
    }).addTo(state.map);
    if (state.mapPickMode && state.currentScene) {
      const sample = {
        scene_name: state.currentScene.scene_name,
        map_px: Number(point.x.toFixed(2)),
        map_py: Number(point.y.toFixed(2)),
      };
      const i = state.anchorSamples.findIndex((row) => row.scene_name === sample.scene_name);
      if (i >= 0) {
        state.anchorSamples[i] = sample;
      } else {
        state.anchorSamples.push(sample);
      }
      updateAnchorOutput();
    }
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
  const pixel = applyCoordToMapPixel(scene?.coordinate_x, scene?.coordinate_y);
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
  dom.sceneTitle.textContent = scene.scene_title || scene.scene_name || "未命名场景";
  dom.sceneName.textContent = scene.scene_name || "-";
  dom.panoramaName.textContent = scene.panorama_name || "-";
  dom.sceneGroup.textContent = scene.scene_group_name || "-";
  dom.sceneSeasons.textContent = Array.isArray(scene.seasons) ? scene.seasons.join(", ") : "-";
  dom.coordX.textContent = formatValue(scene.coordinate_x);
  dom.coordY.textContent = formatValue(scene.coordinate_y);
  dom.boundsX.textContent = `X: ${formatValue(state.bounds?.x_min)} → ${formatValue(state.bounds?.x_max)}`;
  dom.boundsY.textContent = `Y: ${formatValue(state.bounds?.y_min)} → ${formatValue(state.bounds?.y_max)}`;
  updateGuessDisplay(state.lastGuessCoord);
  renderDebugTiles(scene);
  renderViewer(scene);
  renderMapForScene(scene);
  renderViewerUsedTiles(scene);
  window.setTimeout(() => renderViewerUsedTiles(scene), 1000);
  window.setTimeout(() => renderViewerUsedTiles(scene), 2500);
  if (state.usedTilesPollTimer) {
    window.clearInterval(state.usedTilesPollTimer);
  }
  state.usedTilesPollTimer = window.setInterval(() => {
    if (!state.currentScene || state.currentScene.scene_name !== scene.scene_name) {
      return;
    }
    renderViewerUsedTiles(scene);
  }, 1000);
  document.querySelectorAll(".scene-chip").forEach((button) => {
    button.classList.toggle("is-active", button.title === scene.scene_name);
  });
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

async function loadScene(sceneName) {
  const scene = await requestJson(`/api/scenes/${encodeURIComponent(sceneName)}`);
  renderScene(scene);
}

async function loadRandomScene() {
  const scene = await requestJson("/api/scenes/random");
  renderScene(scene);
}

async function init() {
  installViewerUsageProbe();
  const config = await requestJson("/api/config");
  const scenesResponse = await requestJson("/api/scenes?limit=20");
  try {
    const transformPayload = await requestJson("/assets/map_transform.json");
    state.mapTransform = normalizeMapTransform(transformPayload);
  } catch {
    state.mapTransform = null;
  }

  state.scenes = scenesResponse.items || [];
  state.bounds = config.bounds;
  state.mapFocusBounds = null;
  installMiniMap();
  if (!state.map && dom.mapPlaceholder) {
    dom.mapPlaceholder.innerHTML = "<p>地图运行时未加载（Leaflet 缺失）。</p><p>请先下载 /assets/vendor/leaflet.js 与 /assets/vendor/leaflet.css。</p>";
  } else if (!state.mapTransform && dom.mapPlaceholder) {
    dom.mapPlaceholder.innerHTML = "<p>缺少 map_transform.json，地图仅显示底图。</p><p>请先运行校准脚本生成仿射映射。</p>";
    dom.mapPlaceholder.hidden = false;
    dom.mapBox?.classList.remove("is-ready");
  }

  dom.sceneCount.textContent = formatValue(scenesResponse.total);
  dom.inventoryCount.textContent = formatValue(config.inventory_count);

  renderSceneList();
  if (config.default_scene_name) {
    await loadScene(config.default_scene_name);
  } else if (state.scenes.length > 0) {
    renderScene(state.scenes[0]);
  }

  dom.randomBtn.addEventListener("click", async () => {
    dom.randomBtn.disabled = true;
    dom.randomBtn.textContent = "加载中...";
    try {
      await loadRandomScene();
    } finally {
      dom.randomBtn.disabled = false;
      dom.randomBtn.textContent = "随机场景";
    }
  });
  dom.mapRecenterBtn?.addEventListener("click", () => {
    recenterMiniMap();
  });
  dom.anchorModeBtn?.addEventListener("click", () => {
    setMapPickMode(!state.mapPickMode);
  });
  setMapPickMode(false);
  updateAnchorOutput();

}

init().catch((error) => {
  console.error(error);
  document.body.insertAdjacentHTML(
    "afterbegin",
    `<div style="padding: 24px; color: #fee2e2; background: #7f1d1d; font-size: 14px;">初始化失败：${error.message}</div>`,
  );
});