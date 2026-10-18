const { app, BrowserWindow, ipcMain, safeStorage, session, shell, protocol, net, Notification, dialog } = require('electron');
const fs = require('fs');
const path = require('path');
const { pathToFileURL } = require('url');
const { CHANNELS, configureWindowsIdentity, createNotificationController, registerNotificationIpc } = require('./native-notifications.cjs');

const isDev = !app.isPackaged;

let mainWindow = null;
const nativeIdentityReady = configureWindowsIdentity(app, process.platform);

app.setName('Nerkhbaan');
const profileDirectory = app.commandLine.getSwitchValue('user-data-dir');
if (profileDirectory) {
  const isolatedProfile = path.resolve(profileDirectory);
  fs.mkdirSync(isolatedProfile, { recursive: true });
  app.setPath('userData', isolatedProfile);
}
const ownsInstance = app.requestSingleInstanceLock();
if (!ownsInstance) app.quit();
app.on('second-instance', () => {
  if (!mainWindow) return;
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.focus();
});
protocol.registerSchemesAsPrivileged([{ scheme: 'nerkhbaan', privileges: { standard: true, secure: true, supportFetchAPI: true, corsEnabled: true } }]);

const isAppUrl = (value) => {
  try {
    const parsed = new URL(value);
    return isDev ? parsed.origin === 'http://localhost:5173'
      : parsed.protocol === 'nerkhbaan:' && parsed.hostname === 'app' && !parsed.port && !parsed.username && !parsed.password && parsed.pathname === '/index.html';
  } catch { return false; }
};

const isTrustedRenderer = (event) => {
  if (!mainWindow || event.sender !== mainWindow.webContents || event.senderFrame !== mainWindow.webContents.mainFrame) return false;
  const rendererUrl = event.senderFrame?.url || event.sender.getURL();
  try {
    const parsed = new URL(rendererUrl);
    return isAppUrl(parsed.href);
  } catch {
    return false;
  }
};

const currentFrameIsTrusted = () => Boolean(mainWindow && !mainWindow.isDestroyed()
  && !mainWindow.webContents.isDestroyed() && isAppUrl(mainWindow.webContents.mainFrame.url));

const nativeNotifications = createNotificationController({
  platform: process.platform,
  packaged: app.isPackaged,
  identityReady: nativeIdentityReady,
  isSupported: () => Notification.isSupported(),
  isTrusted: isTrustedRenderer,
  isCurrentFrameTrusted: currentFrameIsTrusted,
  askConsent: async (copy, signal) => {
    if (!currentFrameIsTrusted()) return false;
    const result = await dialog.showMessageBox(mainWindow, {
      type: 'question', title: 'Nerkhbaan', message: copy.consent,
      buttons: [copy.cancel, copy.enable], defaultId: 0, cancelId: 0, noLink: true, signal,
    });
    return result.response === 1;
  },
  createNotification: options => new Notification(options),
  setActive: active => {
    if (mainWindow && !mainWindow.webContents.isDestroyed()) mainWindow.webContents.setBackgroundThrottling(!active);
  },
  focusWindow: () => {
    if (!currentFrameIsTrusted()) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
  },
  openInbox: scope => {
    if (currentFrameIsTrusted()) mainWindow.webContents.send(CHANNELS.openInbox, scope);
  },
});
registerNotificationIpc(ipcMain, nativeNotifications);

const credentialsPath = () => path.join(app.getPath('userData'), 'session-credentials.bin');

const parseCredentials = (value) => {
  if (!value || typeof value !== 'object') return null;
  const accessToken = value.access_token;
  const refreshToken = value.refresh_token;
  if (typeof accessToken !== 'string' || accessToken.length < 16 || accessToken.length > 8192) return null;
  if (refreshToken !== null && (typeof refreshToken !== 'string' || refreshToken.length < 16 || refreshToken.length > 8192)) return null;
  return { access_token: accessToken, refresh_token: refreshToken };
};

const parseTelegramDeepLink = (value) => {
  if (typeof value !== 'string' || value.length > 256) return null;
  try {
    const parsed = new URL(value);
    const queryKeys = [...parsed.searchParams.keys()];
    const token = parsed.searchParams.get('start') || '';
    if (
      parsed.protocol !== 'https:' ||
      parsed.hostname !== 't.me' ||
      parsed.port ||
      parsed.username ||
      parsed.password ||
      parsed.hash ||
      !/^\/[A-Za-z][A-Za-z0-9_]{4,31}$/.test(parsed.pathname) ||
      queryKeys.length !== 1 ||
      queryKeys[0] !== 'start' ||
      !/^[A-Za-z0-9_-]{48}$/.test(token)
    ) return null;
    return parsed.toString();
  } catch {
    return null;
  }
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
  const temporary = `${credentialsPath()}.tmp`;
  await fs.promises.writeFile(temporary, encrypted, { mode: 0o600 });
  await fs.promises.rename(temporary, credentialsPath());
});

ipcMain.handle('auth-clear-credentials', async (event) => {
  if (!isTrustedRenderer(event)) throw new Error('Untrusted renderer');
  nativeNotifications.revoke();
  await fs.promises.rm(credentialsPath(), { force: true });
});

ipcMain.handle('open-telegram-link', async (event, value) => {
  if (!isTrustedRenderer(event)) return false;
  const safeUrl = parseTelegramDeepLink(value);
  if (!safeUrl) return false;
  try {
    await shell.openExternal(safeUrl, { activate: true });
    return true;
  } catch {
    return false;
  }
});

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 1024,
    minHeight: 700,
    frame: true,
    autoHideMenuBar: true,
    backgroundColor: '#060606',
    icon: path.join(__dirname, '../dist/icons/logo.png'),
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
    mainWindow.loadURL('nerkhbaan://app/index.html').catch(err => {
      console.error('Failed to load production build:', err);
    });
  }

  mainWindow.maximize();

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (isAppUrl(url)) void mainWindow.loadURL(url);
    else {
      try {
        const parsed = new URL(url);
        if (parsed.protocol === 'https:' && !parsed.username && !parsed.password && !parsed.port && ['t.me', 'www.tradingview.com', 'tradingview.com'].includes(parsed.hostname)) void shell.openExternal(parsed.href).catch(() => undefined);
      } catch { /* Ignore malformed external links. */ }
    }
    return { action: 'deny' };
  });
  mainWindow.webContents.on('will-navigate', (event, targetUrl) => {
    try {
      const parsed = new URL(targetUrl);
      const allowed = isAppUrl(parsed.href);
      if (!allowed) event.preventDefault();
    } catch {
      event.preventDefault();
    }
  });
  mainWindow.webContents.on('will-attach-webview', (event) => event.preventDefault());
  mainWindow.webContents.on('did-start-navigation', (_event, _url, isInPlace, isMainFrame) => {
    if (isMainFrame && !isInPlace) nativeNotifications.revoke();
  });
  mainWindow.webContents.on('render-process-gone', () => nativeNotifications.revoke());
  mainWindow.webContents.on('destroyed', () => nativeNotifications.revoke());

  mainWindow.on('closed', () => {
    nativeNotifications.revoke();
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
  if (!ownsInstance) return;
  const dist = path.resolve(__dirname, '../dist');
  protocol.handle('nerkhbaan', async request => {
    try {
      const url = new URL(request.url);
      if (url.hostname !== 'app' || url.port || url.username || url.password || !['GET', 'HEAD'].includes(request.method)) return new Response(null, { status: 403 });
      const file = path.resolve(dist, `.${decodeURIComponent(url.pathname === '/' ? '/index.html' : url.pathname)}`);
      const relative = path.relative(dist, file);
      if (relative.startsWith('..') || path.isAbsolute(relative)) return new Response(null, { status: 403 });
      if (!(await fs.promises.stat(file)).isFile()) return new Response(null, { status: 404 });
      return net.fetch(pathToFileURL(file).href);
    } catch { return new Response(null, { status: 404 }); }
  });
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

app.on('before-quit', () => nativeNotifications.revoke());

app.on('activate', () => {
  if (mainWindow === null) {
    createWindow();
  }
});
