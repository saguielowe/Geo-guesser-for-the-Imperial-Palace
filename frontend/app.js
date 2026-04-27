const state = {
  scenes: [],
  currentScene: null,
  bounds: null,
  viewer: null,
  mapping: {
    currentMode: null,
    modes: [],
  },
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
  tileTemplate: document.getElementById("tile-template"),
  tileProbes: document.getElementById("tile-probes"),
  sceneList: document.getElementById("scene-list"),
  viewerPlaceholder: document.querySelector(".viewer-placeholder"),
  viewerFrame: document.getElementById("viewer-frame"),
  viewerCanvas: document.getElementById("pannellum-viewer"),
  randomBtn: document.getElementById("random-btn"),
  mappingBtn: document.getElementById("mapping-btn"),
};

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

function renderTileProbes(scene) {
  dom.tileProbes.innerHTML = "";
  (scene.sample_tile_urls || []).forEach((url) => {
    const item = document.createElement("a");
    item.className = "tile-probe";
    item.href = url;
    item.target = "_blank";
    item.rel = "noreferrer";
    item.textContent = url;
    dom.tileProbes.appendChild(item);
  });
}

function clearViewer() {
  if (state.viewer && typeof state.viewer.destroy === "function") {
    state.viewer.destroy();
  }
  state.viewer = null;
  dom.viewerCanvas.innerHTML = "";
}

function renderViewer(scene) {
  if (!window.pannellum) {
    dom.viewerCanvas.innerHTML = "<div class='viewer-error'>Pannellum 未加载，请检查 CDN 访问。</div>";
    return;
  }

  clearViewer();
  dom.viewerFrame.classList.remove("is-ready");
  dom.viewerFrame.classList.add("is-loading");

  const viewerConfig = {
    default: {
      firstScene: "current",
      autoLoad: true,
      showControls: true,
      mouseZoom: "fullscreenonly",
      backgroundColor: [0.04, 0.05, 0.09],
      yaw: 0,
      pitch: 0,
      hfov: 95,
    },
    scenes: {
      current: {
        title: scene.scene_title || scene.scene_name || "未命名场景",
        type: scene.viewer?.type || "multires",
        multiRes: scene.viewer,
      },
    },
  };

  try {
    state.viewer = window.pannellum.viewer(dom.viewerCanvas, viewerConfig);
    state.viewer.on("load", () => {
      dom.viewerFrame.classList.remove("is-loading");
      dom.viewerFrame.classList.add("is-ready");
      if (dom.viewerPlaceholder) {
        dom.viewerPlaceholder.hidden = true;
      }
    });
    state.viewer.on("error", (message) => {
      dom.viewerFrame.classList.remove("is-loading");
      dom.viewerFrame.classList.remove("is-ready");
      if (dom.viewerPlaceholder) {
        dom.viewerPlaceholder.hidden = false;
      }
      dom.viewerCanvas.innerHTML = `<div class='viewer-error'>${message}</div>`;
    });
  } catch (error) {
    dom.viewerFrame.classList.remove("is-loading");
    dom.viewerFrame.classList.remove("is-ready");
    if (dom.viewerPlaceholder) {
      dom.viewerPlaceholder.hidden = false;
    }
    dom.viewerCanvas.innerHTML = `<div class='viewer-error'>${error.message}</div>`;
  }

    window.setTimeout(() => {
      const loadButton = dom.viewerCanvas.querySelector(".pnlm-load-button");
      if (loadButton) {
        loadButton.click();
      }
    }, 0);
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
  dom.tileTemplate.textContent = scene.tile_url_template || "-";
  renderTileProbes(scene);
  renderViewer(scene);

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

function renderMappingButton() {
  if (!dom.mappingBtn) {
    return;
  }
  const mode = state.mapping.currentMode || "-";
  dom.mappingBtn.textContent = `拼接调试：${mode}`;
}

async function refreshMappingState() {
  const payload = await requestJson("/api/debug/mapping");
  state.mapping.currentMode = payload.current_mode || null;
  state.mapping.modes = Array.isArray(payload.modes) ? payload.modes : [];
  renderMappingButton();
}

async function toggleMappingMode() {
  const payload = await requestJson("/api/debug/mapping", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ action: "next" }),
  });
  state.mapping.currentMode = payload.current_mode || null;
  state.mapping.modes = Array.isArray(payload.modes) ? payload.modes : [];
  renderMappingButton();

  if (state.currentScene?.scene_name) {
    await loadScene(state.currentScene.scene_name);
  }
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
  const config = await requestJson("/api/config");
  const scenesResponse = await requestJson("/api/scenes?limit=20");

  state.scenes = scenesResponse.items || [];
  state.bounds = config.bounds;

  dom.sceneCount.textContent = formatValue(scenesResponse.total);
  dom.inventoryCount.textContent = formatValue(config.inventory_count);
  state.mapping.currentMode = config.mapping_mode || null;
  state.mapping.modes = Array.isArray(config.mapping_modes) ? config.mapping_modes : [];
  renderMappingButton();

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

  if (dom.mappingBtn) {
    dom.mappingBtn.addEventListener("click", async () => {
      dom.mappingBtn.disabled = true;
      const originalText = dom.mappingBtn.textContent;
      dom.mappingBtn.textContent = "拼接调试：切换中...";
      try {
        await toggleMappingMode();
      } finally {
        dom.mappingBtn.disabled = false;
        if (dom.mappingBtn.textContent === "拼接调试：切换中...") {
          dom.mappingBtn.textContent = originalText;
        }
      }
    });
  }

  await refreshMappingState();
}

init().catch((error) => {
  console.error(error);
  document.body.insertAdjacentHTML(
    "afterbegin",
    `<div style="padding: 24px; color: #fee2e2; background: #7f1d1d; font-size: 14px;">初始化失败：${error.message}</div>`,
  );
});