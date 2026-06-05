const { app, BrowserWindow } = require("electron");
const { spawn } = require("child_process");
const path = require("path");
const http = require("http");
const fs = require("fs");

const ROOT = path.resolve(__dirname, "..");
const SERVER_PORT = 8000;
const SERVER_URL = `http://127.0.0.1:${SERVER_PORT}`;

let backendProcess = null;

function startBackend() {
  return new Promise((resolve, reject) => {
    const isDev = !app.isPackaged;

    let cmd, cwd;

    if (isDev) {
      // 开发模式：用系统 Python 直接跑
      const python = process.platform === "win32" ? "python" : "python3";
      cmd = python;
      cwd = ROOT;
    } else {
      // 生产模式：exe 在 resources/app/backend/server/server.exe
      const exeName = process.platform === "win32" ? "server.exe" : "server";
      const exePath = path.join(process.resourcesPath, "app", "backend", "server", exeName);
      if (!fs.existsSync(exePath)) {
        reject(new Error(`Backend executable not found: ${exePath}`));
        return;
      }
      cmd = exePath;
      cwd = process.resourcesPath;
    }

    const args = isDev ? [path.join(ROOT, "backend", "server.py")] : [];
    backendProcess = spawn(cmd, args, {
      cwd: cwd,
      stdio: ["ignore", "pipe", "pipe"],
    });

    backendProcess.stderr.on("data", (data) => {
      console.error("[backend]", data.toString().trim());
    });

    backendProcess.on("error", (err) => {
      console.error("Failed to start backend:", err.message);
      reject(err);
    });

    backendProcess.on("exit", (code) => {
      console.log(`Backend exited with code ${code}`);
      backendProcess = null;
    });

    // Poll until server is ready
    let attempts = 0;
    const maxAttempts = 30;
    const poll = setInterval(() => {
      attempts++;
      http.get(`${SERVER_URL}/api/health`, (res) => {
        if (res.statusCode === 200) {
          clearInterval(poll);
          resolve();
        }
      }).on("error", () => {
        if (attempts >= maxAttempts) {
          clearInterval(poll);
          reject(new Error("Backend did not start in time"));
        }
      });
    }, 500);
  });
}

function stopBackend() {
  if (backendProcess) {
    backendProcess.kill();
    backendProcess = null;
  }
}

async function createWindow() {
  const isReport = process.argv.includes("--report");

  const win = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 960,
    minHeight: 600,
    title: "寻迹故宫 · 1.0",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  const url = isReport ? `${SERVER_URL}/?report=1` : SERVER_URL;
  win.loadURL(url);

  win.on("closed", () => {
    stopBackend();
  });
}

app.whenReady().then(async () => {
  try {
    await startBackend();
    console.log("Backend ready, opening window...");
    await createWindow();
  } catch (err) {
    console.error("Startup failed:", err.message);
    app.quit();
  }
});

app.on("window-all-closed", () => {
  stopBackend();
  app.quit();
});

app.on("before-quit", () => {
  stopBackend();
});
