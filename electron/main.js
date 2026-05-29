const { app, BrowserWindow } = require("electron");
const { spawn } = require("child_process");
const path = require("path");
const http = require("http");

const ROOT = path.resolve(__dirname, "..");
const PYTHON = process.platform === "win32" ? "python" : "python3";
const SERVER_PORT = 8000;
const SERVER_URL = `http://127.0.0.1:${SERVER_PORT}`;

let backendProcess = null;

function startBackend() {
  return new Promise((resolve, reject) => {
    const serverScript = path.join(ROOT, "backend", "server.py");
    backendProcess = spawn(PYTHON, [serverScript], {
      cwd: ROOT,
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
