interface ElectronAPI {
  minimizeWindow: () => void;
  toggleMaximizeWindow: () => void;
  closeWindow: () => void;
  isWindowMaximized: () => Promise<boolean>;
  openTelegramLink: (url: string) => Promise<boolean>;
  auth: {
    getCredentials: () => Promise<{ access_token: string; refresh_token: string | null } | null>;
    setCredentials: (credentials: { access_token: string; refresh_token: string | null }) => Promise<void>;
    clearCredentials: () => Promise<void>;
  };
}

interface Window {
  electronAPI?: ElectronAPI;
}
