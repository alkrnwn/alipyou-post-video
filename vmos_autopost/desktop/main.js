const { app, BrowserWindow, dialog, shell } = require('electron');
const { spawn } = require('child_process');
const crypto = require('crypto');
const http = require('http');
const net = require('net');
const path = require('path');
const fs = require('fs');

let autoUpdater = null;
try {
  autoUpdater = require('electron-updater').autoUpdater;
} catch (_) {}

let py = null;
let win = null;
let stderrBuf = '';

if (!app.requestSingleInstanceLock()) { app.quit(); }

function freePort() {
  return new Promise((resolve, reject) => {
    const s = net.createServer();
    s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => resolve(p)); });
    s.on('error', reject);
  });
}

function ping(port, token) {
  return new Promise((resolve) => {
    const req = http.get({ host: '127.0.0.1', port, path: '/config', headers: { 'X-Token': token }, timeout: 1000 },
      (res) => { res.resume(); resolve(res.statusCode === 200); });
    req.on('error', () => resolve(false));
    req.on('timeout', () => { req.destroy(); resolve(false); });
  });
}

async function waitReady(port, token) {
  for (let i = 0; i < 80; i++) {
    if (py && py.exitCode !== null) return false;
    if (await ping(port, token)) return true;
    await new Promise((r) => setTimeout(r, 250));
  }
  return false;
}

function stopBackend() {
  if (py && py.exitCode === null) {
    try { py.kill(); } catch (_) { /* sudah mati */ }
  }
}

async function start() {
  const port = await freePort();
  const token = crypto.randomBytes(24).toString('hex');
  const dbPath = path.join(app.getPath('userData'), 'autopost.db');

  const candidatePaths = [
    path.join(process.resourcesPath, 'backend', 'backend', 'backend.exe'),
    path.join(process.resourcesPath, 'backend', 'backend.exe'),
    path.join(__dirname, 'backend', 'backend', 'backend.exe'),
    path.join(__dirname, 'backend', 'backend.exe'),
  ];

  let backendExe = null;
  for (const p of candidatePaths) {
    if (fs.existsSync(p)) {
      backendExe = p;
      break;
    }
  }

  if (backendExe) {
    const backendCwd = path.dirname(backendExe);
    py = spawn(backendExe, [
      '--host', '127.0.0.1',
      '--port', String(port),
      '--token', token,
      '--db', dbPath,
      ...(process.env.AUTOPOST_DRYRUN === '1' ? ['--dry-run'] : []),
    ], {
      cwd: backendCwd,
      windowsHide: true,
      env: {
        ...process.env,
        AUTOPOST_TOKEN: token,
        AUTOPOST_DB: dbPath,
      },
    });
  } else {
    const python = process.env.AUTOPOST_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
    const root = path.join(__dirname, '..');
    py = spawn(python,
      ['-m', 'uvicorn', 'app.main:app_factory', '--factory', '--host', '127.0.0.1', '--port', String(port)],
      {
        cwd: root,
        windowsHide: true,
        env: { ...process.env, AUTOPOST_TOKEN: token, AUTOPOST_DB: dbPath },
      });
  }
  py.stderr.on('data', (d) => { stderrBuf = (stderrBuf + d.toString()).slice(-4000); });
  py.on('error', (e) => { stderrBuf += '\n' + e.message; });

  if (!(await waitReady(port, token))) {
    dialog.showErrorBox('Backend gagal jalan',
      'Pastikan Python dan dependensi terpasang (pip install -r requirements.txt).\n\n' + stderrBuf);
    stopBackend();
    app.quit();
    return;
  }

  const origin = `http://127.0.0.1:${port}`;
  win = new BrowserWindow({
    width: 1240, height: 820, title: 'Shopee Video · VMOS',
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  win.setMenuBarVisibility(false);
  win.webContents.on('will-navigate', (e, url) => {
    if (!url.startsWith(origin)) {
      e.preventDefault();
      shell.openExternal(url);
    }
  });
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('http:') || url.startsWith('https:')) {
      shell.openExternal(url);
    }
    return { action: 'deny' };
  });
  win.loadURL(`${origin}/?t=${token}`);
  setupAutoUpdater();
  py.on('exit', () => {
    if (win && !win.isDestroyed()) {
      dialog.showErrorBox('Backend berhenti', stderrBuf || 'Proses backend berhenti tiba-tiba.');
      app.quit();
    }
  });
}

function setupAutoUpdater() {
  if (!app.isPackaged || !autoUpdater) return;

  autoUpdater.autoDownload = false;
  autoUpdater.autoInstallOnAppQuit = true;

  autoUpdater.on('update-available', (info) => {
    dialog.showMessageBox(win, {
      type: 'info',
      title: 'Pembaruan Online Tersedia',
      message: `Versi baru (${info.version}) telah tersedia di GitHub!`,
      detail: `Versi saat ini: v${app.getVersion()}\nVersi terbaru: v${info.version}\n\nApakah Anda ingin mengunduh pembaruan sekarang?`,
      buttons: ['Ya, Unduh Pembaruan', 'Nanti Saja'],
      defaultId: 0,
      cancelId: 1
    }).then((res) => {
      if (res.response === 0) {
        autoUpdater.downloadUpdate();
        dialog.showMessageBox(win, {
          type: 'info',
          title: 'Sedang Mengunduh',
          message: 'Pembaruan sedang diunduh di latar belakang. Aplikasi akan memberi tahu setelah selesai.',
          buttons: ['OK']
        });
      }
    });
  });

  autoUpdater.on('update-downloaded', (info) => {
    dialog.showMessageBox(win, {
      type: 'question',
      title: 'Pembaruan Siap Dipasang',
      message: `Versi baru (${info.version}) telah selesai diunduh!`,
      detail: 'Mulai ulang aplikasi sekarang untuk menerapkan versi terbaru?',
      buttons: ['Mulai Ulang Sekarang', 'Nanti Saat Ditutup'],
      defaultId: 0
    }).then((res) => {
      if (res.response === 0) {
        stopBackend();
        autoUpdater.quitAndInstall();
      }
    });
  });

  autoUpdater.on('error', (err) => {
    console.error('AutoUpdater Error:', err);
  });

  setTimeout(() => {
    try {
      autoUpdater.checkForUpdates().catch(() => {});
    } catch (_) {}
  }, 5000);
}

app.whenReady().then(start);
app.on('second-instance', () => { if (win) { if (win.isMinimized()) win.restore(); win.focus(); } });
app.on('before-quit', stopBackend);
app.on('window-all-closed', () => app.quit());
