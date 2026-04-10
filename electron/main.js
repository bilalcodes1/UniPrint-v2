const { app, BrowserWindow, Tray, Menu, nativeImage, dialog, shell, protocol, net } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs   = require('fs');
const http = require('http');

// ── Paths ─────────────────────────────────────────────────────────────────────
const isDev      = !app.isPackaged;
const rootDir    = isDev
  ? path.join(__dirname, '..')
  : path.join(process.resourcesPath);

const backendDir   = path.join(isDev ? rootDir : rootDir, 'backend');
const dashboardDir = isDev
  ? path.join(rootDir, 'frontend', 'build')
  : path.join(rootDir, 'dashboard');

// Packaged: use PyInstaller binary. Dev: use venv python
const backendExeName = process.platform === 'win32' ? 'backend.exe' : 'backend-mac';
const backendExe  = path.join(process.resourcesPath, backendExeName);
const pythonBin   = process.platform === 'win32'
  ? path.join(backendDir, 'venv', 'Scripts', 'python.exe')
  : path.join(backendDir, 'venv', 'bin', 'python');
const runScript   = path.join(backendDir, 'run.py');
const PORT       = 5001;
const DASHBOARD  = 'app://dashboard/';

// ── Register custom protocol for serving dashboard files ──────────────────────
app.whenReady().catch(() => {});
protocol.registerSchemesAsPrivileged([
  { scheme: 'app', privileges: { standard: true, secure: true, supportFetchAPI: true, corsEnabled: true } }
]);

// ── State ─────────────────────────────────────────────────────────────────────
let mainWindow   = null;
let tray         = null;
let backendProc  = null;
let serverReady  = false;

// ── Single instance lock ──────────────────────────────────────────────────────
if (!app.requestSingleInstanceLock()) {
  app.quit();
}
app.on('second-instance', () => {
  if (mainWindow) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  }
});

// ── Start Flask backend ───────────────────────────────────────────────────────
function startBackend() {
  // Packaged app: run PyInstaller binary. Dev: run venv python
  let cmd, args;
  if (!isDev && fs.existsSync(backendExe)) {
    cmd  = backendExe;
    args = [];
  } else if (fs.existsSync(pythonBin)) {
    cmd  = pythonBin;
    args = [runScript];
  } else {
    dialog.showErrorBox(
      'UniPrint — خطأ',
      `لم يُعثر على Backend:\n${backendExe}\n\nيرجى إعادة تثبيت التطبيق.`
    );
    app.quit();
    return;
  }

  backendProc = spawn(cmd, args, {
    cwd: backendDir,
    env: { ...process.env, PYTHONUNBUFFERED: '1' },
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  backendProc.stdout.on('data', d => console.log('[backend]', d.toString().trim()));
  backendProc.stderr.on('data', d => console.error('[backend-err]', d.toString().trim()));

  backendProc.on('exit', (code) => {
    console.log(`[backend] exited with code ${code}`);
    if (mainWindow && !app.isQuitting && serverReady) {
      // Check if another instance (e.g. launchd) is already serving before showing error
      http.get(`http://localhost:${PORT}/health`, res => {
        if (res.statusCode !== 200) {
          mainWindow.webContents.loadURL('data:text/html,<h2 style="font-family:sans-serif;color:#c00;padding:40px">⚠️ انقطع الاتصال بالسيرفر. أعد تشغيل التطبيق.</h2>');
        }
      }).on('error', () => {
        mainWindow.webContents.loadURL('data:text/html,<h2 style="font-family:sans-serif;color:#c00;padding:40px">⚠️ انقطع الاتصال بالسيرفر. أعد تشغيل التطبيق.</h2>');
      });
    }
  });
}

// ── Wait for server ───────────────────────────────────────────────────────────
function waitForServer(retries = 30, delay = 500) {
  return new Promise((resolve, reject) => {
    const attempt = (n) => {
      http.get(`http://localhost:${PORT}/health`, res => {
        if (res.statusCode === 200) { resolve(); }
        else if (n > 0) { setTimeout(() => attempt(n - 1), delay); }
        else { reject(new Error('timeout')); }
      }).on('error', () => {
        if (n > 0) setTimeout(() => attempt(n - 1), delay);
        else reject(new Error('timeout'));
      });
    };
    attempt(retries);
  });
}

// ── Create main window ────────────────────────────────────────────────────────
function createWindow() {
  mainWindow = new BrowserWindow({
    width:  1280,
    height: 800,
    minWidth:  900,
    minHeight: 600,
    title: 'UniPrint',
    backgroundColor: '#F2F2F7',
    show: false,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      webSecurity: false,
    },
  });

  // Loading screen
  mainWindow.loadURL('data:text/html,' + encodeURIComponent(`
    <html dir="rtl">
    <head><meta charset="utf-8">
    <style>
      body { margin:0; display:flex; flex-direction:column; align-items:center;
             justify-content:center; height:100vh; background:#2D6BE4;
             font-family: system-ui, -apple-system, sans-serif; color:#fff; }
      .logo { font-size:64px; margin-bottom:20px; }
      h1    { font-size:28px; font-weight:700; margin:0 0 8px; }
      p     { font-size:15px; opacity:0.75; margin:0 0 32px; }
      .bar  { width:200px; height:4px; background:rgba(255,255,255,0.25); border-radius:2px; overflow:hidden; }
      .fill { height:100%; background:#fff; border-radius:2px; animation:load 1.5s ease-in-out infinite; }
      @keyframes load { 0%{width:0} 50%{width:70%} 100%{width:100%} }
    </style></head>
    <body>
      <div class="logo">🖨️</div>
      <h1>UniPrint</h1>
      <p>جارٍ التشغيل…</p>
      <div class="bar"><div class="fill"></div></div>
    </body></html>
  `));

  mainWindow.once('ready-to-show', () => mainWindow.show());

  mainWindow.on('close', (e) => {
    if (!app.isQuitting) {
      e.preventDefault();
      mainWindow.hide();
    }
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });
}

// ── Tray ──────────────────────────────────────────────────────────────────────
function createTray() {
  const iconPath = path.join(__dirname, 'assets', 'tray.png');
  const icon = fs.existsSync(iconPath)
    ? nativeImage.createFromPath(iconPath).resize({ width: 16, height: 16 })
    : nativeImage.createEmpty();

  tray = new Tray(icon);
  tray.setToolTip('UniPrint — نظام الطباعة');

  const menu = Menu.buildFromTemplate([
    { label: 'فتح UniPrint',    click: () => { mainWindow.show(); mainWindow.focus(); } },
    { label: 'صفحة الطالب',    click: () => shell.openExternal(`http://localhost:${PORT}/student/lan/`) },
    { type: 'separator' },
    { label: 'سجلات السيرفر',   click: () => shell.openExternal(`http://localhost:${PORT}/health`) },
    { type: 'separator' },
    { label: 'إغلاق UniPrint',  click: () => { app.isQuitting = true; app.quit(); } },
  ]);

  tray.setContextMenu(menu);
  tray.on('double-click', () => { mainWindow.show(); mainWindow.focus(); });
}

// ── App lifecycle ─────────────────────────────────────────────────────────────
app.whenReady().then(async () => {
  // ── Serve dashboard build via app:// protocol ──────────────────────────────
  protocol.handle('app', (request) => {
    let urlPath = request.url.slice('app://dashboard/'.length);
    if (!urlPath || urlPath === '' || urlPath.endsWith('/')) {
      urlPath = 'index.html';
    }
    const filePath = path.join(dashboardDir, urlPath);
    if (fs.existsSync(filePath) && fs.statSync(filePath).isFile()) {
      return net.fetch(`file://${filePath}`);
    }
    return net.fetch(`file://${path.join(dashboardDir, 'index.html')}`);
  });

  createWindow();
  createTray();
  startBackend();

  try {
    await waitForServer();
    serverReady = true;
    mainWindow.loadURL(DASHBOARD);
  } catch {
    dialog.showErrorBox('UniPrint', 'تعذّر تشغيل السيرفر. تحقق من السجلات.');
    app.quit();
  }
});

app.on('window-all-closed', (e) => {
  e.preventDefault(); // keep alive in tray
});

app.on('activate', () => {
  mainWindow?.show();
});

app.on('before-quit', () => {
  app.isQuitting = true;
  if (backendProc) {
    backendProc.kill('SIGTERM');
  }
});
