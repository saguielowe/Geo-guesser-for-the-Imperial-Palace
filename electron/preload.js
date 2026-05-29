// Preload script — bridge between Electron main and renderer.
// Currently a placeholder; extend as needed.
const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("electronAPI", {
  platform: process.platform,
  isElectron: true,
});
