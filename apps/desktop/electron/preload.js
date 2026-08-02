const { contextBridge, ipcRenderer } = require('electron');

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
  auth: Object.freeze({
    getCredentials: () => ipcRenderer.invoke('auth-get-credentials'),
    setCredentials: (credentials) => ipcRenderer.invoke('auth-set-credentials', credentials),
    clearCredentials: () => ipcRenderer.invoke('auth-clear-credentials')
  })
});
