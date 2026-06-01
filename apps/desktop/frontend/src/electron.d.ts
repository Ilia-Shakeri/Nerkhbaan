interface ElectronAPI {
  minimizeWindow: () => void;
  toggleMaximizeWindow: () => void;
  closeWindow: () => void;
  isWindowMaximized: () => Promise<boolean>;
}

interface Window {
  electronAPI?: ElectronAPI;
}
