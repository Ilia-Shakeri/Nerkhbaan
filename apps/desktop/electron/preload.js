const { contextBridge, ipcRenderer } = require('electron');

let notificationEpoch = 0;
const invokeNotification = (method, value, timeout = 3000) => {
  let timer;
  const args = value === undefined ? [] : [value];
  return Promise.race([
    Promise.resolve().then(() => ipcRenderer.invoke(`native-notifications-${method}`, ...args)).catch(() => false),
    new Promise(resolve => { timer = setTimeout(() => resolve(false), timeout); }),
  ]).finally(() => clearTimeout(timer));
};
const validNotificationScope = value => Boolean(value && typeof value === 'object' && !Array.isArray(value)
  && Object.keys(value).length === 3 && Object.keys(value).every(key => ['nonce', 'sessionGeneration', 'rightsEpoch'].includes(key))
  && typeof value.nonce === 'string' && /^[a-f0-9]{64}$/.test(value.nonce)
  && Number.isSafeInteger(value.sessionGeneration) && value.sessionGeneration >= 0
  && Number.isSafeInteger(value.rightsEpoch) && value.rightsEpoch >= 0);
const notifications = Object.freeze({
  status: () => invokeNotification('status'),
  enableSession: async value => {
    const epoch = notificationEpoch;
    const result = await invokeNotification('enable-session', value, 22_000);
    return epoch === notificationEpoch && validNotificationScope(result) ? result : false;
  },
  refreshLease: value => invokeNotification('refresh-lease', value).then(result => result === true),
  showPending: value => invokeNotification('show-pending', value).then(result => result === true),
  disableSession: value => {
    notificationEpoch++;
    return invokeNotification('disable-session', value).then(result => result === true);
  },
  onOpenInbox: listener => {
    if (typeof listener !== 'function') return () => {};
    let disposed = false;
    let attached = false;
    const epoch = notificationEpoch;
    const wrapped = (_event, value) => {
      if (!disposed && validNotificationScope(value)) listener(Object.freeze({
        nonce: value.nonce, sessionGeneration: value.sessionGeneration, rightsEpoch: value.rightsEpoch,
      }));
    };
    void invokeNotification('status').then(result => {
      if (disposed || epoch !== notificationEpoch || !result || result.supported !== true) return;
      ipcRenderer.on('native-notifications-open-inbox', wrapped);
      attached = true;
    });
    return () => {
      disposed = true;
      if (attached) ipcRenderer.removeListener('native-notifications-open-inbox', wrapped);
    };
  },
});

contextBridge.exposeInMainWorld('electronAPI', {
  platform: process.platform,
  versions: {
    node: process.versions.node,
    chrome: process.versions.chrome,
    electron: process.versions.electron
  },
  
  minimizeWindow: () => ipcRenderer.send('window-minimize'),
  toggleMaximizeWindow: () => ipcRenderer.send('window-maximize-toggle'),
  closeWindow: () => ipcRenderer.send('window-close'),
  isWindowMaximized: () => ipcRenderer.invoke('window-is-maximized'),
  openTelegramLink: (url) => ipcRenderer.invoke('open-telegram-link', url),
  notifications,
  auth: Object.freeze({
    getCredentials: () => ipcRenderer.invoke('auth-get-credentials'),
    setCredentials: (credentials) => ipcRenderer.invoke('auth-set-credentials', credentials),
    clearCredentials: () => ipcRenderer.invoke('auth-clear-credentials')
  })
});
