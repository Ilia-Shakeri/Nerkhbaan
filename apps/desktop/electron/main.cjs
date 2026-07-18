const { app, BrowserWindow, ipcMain, safeStorage, session } = require('electron');
const fs = require('fs');
const path = require('path');

const isDev = !app.isPackaged;

let mainWindow = null;

app.setName('Nerkhbaan');

const isTrustedRenderer = (event) => {
  const rendererUrl = event.senderFrame?.url || event.sender.getURL();
  try {
    const parsed = new URL(rendererUrl);
    if (isDev) return parsed.origin === 'http://localhost:5173';
    return parsed.protocol === 'file:' && path.normalize(decodeURIComponent(parsed.pathname)).endsWith(path.normalize('dist/index.html'));
  } catch {
    return false;
  }
};

const credentialsPath = () => path.join(app.getPath('userData'), 'session-credentials.bin');

const parseCredentials = (value) => {
  if (!value || typeof value !== 'object') return null;
  const accessToken = value.access_token;
  const refreshToken = value.refresh_token;
  if (typeof accessToken !== 'string' || accessToken.length < 16 || accessToken.length > 8192) return null;
  if (refreshToken !== null && (typeof refreshToken !== 'string' || refreshToken.length < 16 || refreshToken.length > 8192)) return null;
  return { access_token: accessToken, refresh_token: refreshToken };
};

ipcMain.handle('auth-get-credentials', async (event) => {
  if (!isTrustedRenderer(event) || !safeStorage.isEncryptionAvailable()) return null;
  try {
    const encrypted = await fs.promises.readFile(credentialsPath());
    return parseCredentials(JSON.parse(safeStorage.decryptString(encrypted)));
  } catch {
    return null;
  }
});

ipcMain.handle('auth-set-credentials', async (event, value) => {
  if (!isTrustedRenderer(event)) throw new Error('Untrusted renderer');
  const credentials = parseCredentials(value);
  if (!credentials) throw new Error('Invalid session credentials');
  if (!safeStorage.isEncryptionAvailable()) throw new Error('Secure credential storage is unavailable');
  const encrypted = safeStorage.encryptString(JSON.stringify(credentials));
  await fs.promises.mkdir(path.dirname(credentialsPath()), { recursive: true });
  await fs.promises.writeFile(credentialsPath(), encrypted, { mode: 0o600 });
});

ipcMain.handle('auth-clear-credentials', async (event) => {
  if (!isTrustedRenderer(event)) throw new Error('Untrusted renderer');
  await fs.promises.rm(credentialsPath(), { force: true });
});

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 1024,
    minHeight: 700,
    frame: false,
    titleBarStyle: 'hidden',
    autoHideMenuBar: true,
    backgroundColor: '#060606',
    icon: path.join(__dirname, '../src/logo/logo.png'),
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true,
      allowRunningInsecureContent: false,
      preload: path.join(__dirname, 'preload.js')
    }
  });

  if (isDev) {
    mainWindow.loadURL('http://localhost:5173').catch(err => {
      console.error('Failed to load dev server:', err);
      console.log('Make sure the Vite dev server is running on port 5173');
    });
  } else {
    mainWindow.loadFile(path.join(__dirname, '../dist/index.html')).catch(err => {
      console.error('Failed to load production build:', err);
    });
  }

  mainWindow.maximize();

  mainWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  mainWindow.webContents.on('will-navigate', (event, targetUrl) => {
    try {
      const parsed = new URL(targetUrl);
      const allowed = isDev
        ? parsed.origin === 'http://localhost:5173'
        : parsed.protocol === 'file:' && path.normalize(decodeURIComponent(parsed.pathname)).endsWith(path.normalize('dist/index.html'));
      if (!allowed) event.preventDefault();
    } catch {
      event.preventDefault();
    }
  });
  mainWindow.webContents.on('will-attach-webview', (event) => event.preventDefault());

  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  mainWindow.on('maximize', () => {
    mainWindow.webContents.send('window-maximized-changed', true);
  });

  mainWindow.on('unmaximize', () => {
    mainWindow.webContents.send('window-maximized-changed', false);
  });
}

app.whenReady().then(() => {
  session.defaultSession.setPermissionRequestHandler((_webContents, _permission, callback) => callback(false));
  session.defaultSession.setPermissionCheckHandler(() => false);
  createWindow();
});

ipcMain.handle('window-is-maximized', (event) => {
  if (!isTrustedRenderer(event)) return false;
  return mainWindow ? mainWindow.isMaximized() : false;
});

ipcMain.on('window-minimize', (event) => {
  if (!isTrustedRenderer(event)) return;
  if (mainWindow) {
    mainWindow.minimize();
  }
});

ipcMain.on('window-maximize-toggle', (event) => {
  if (!isTrustedRenderer(event)) return;
  if (!mainWindow) {
    return;
  }

  if (mainWindow.isMaximized()) {
    mainWindow.unmaximize();
  } else {
    mainWindow.maximize();
  }
});

ipcMain.on('window-close', (event) => {
  if (!isTrustedRenderer(event)) return;
  if (mainWindow) {
    mainWindow.close();
  }
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('activate', () => {
  if (mainWindow === null) {
    createWindow();
  }
});
