import React, { useEffect, useState } from 'react';
import { Minus, Square, Copy, X } from 'lucide-react';

interface WindowTitleBarProps {
  theme: 'dark' | 'light';
}

export function WindowTitleBar({ theme }: WindowTitleBarProps) {
  const [isMaximized, setIsMaximized] = useState(false);
  const isDark = theme === 'dark';

  useEffect(() => {
    let mounted = true;

    if (!window.electronAPI?.isWindowMaximized) {
      return;
    }

    window.electronAPI.isWindowMaximized().then((value) => {
      if (mounted) {
        setIsMaximized(value);
      }
    });

    return () => {
      mounted = false;
    };
  }, []);

  const toggleMaximize = async () => {
    window.electronAPI?.toggleMaximizeWindow?.();
    if (window.electronAPI?.isWindowMaximized) {
      const value = await window.electronAPI.isWindowMaximized();
      setIsMaximized(value);
    }
  };

  return (
    <div
      className={`titlebar-drag relative flex h-10 items-center border-b px-3 ${
        isDark
          ? 'border-[#D4AF37]/20 bg-[#090909] text-[#E7D49A]'
          : 'border-[#A8872A]/20 bg-[#FFF7DE] text-[#5F4A16]'
      }`}
    >
      <div className="titlebar-no-drag absolute right-3 top-1/2 flex -translate-y-1/2 items-center gap-1">
        <button
          type="button"
          onClick={() => window.electronAPI?.minimizeWindow?.()}
          className={`flex h-7 w-7 items-center justify-center rounded-md transition ${
            isDark ? 'text-[#D4AF37] hover:bg-[#1A1A1A]' : 'text-[#8A6B1E] hover:bg-[#F2E2AF]'
          }`}
          aria-label="Minimize window"
        >
          <Minus size={14} />
        </button>
        <button
          type="button"
          onClick={toggleMaximize}
          className={`flex h-7 w-7 items-center justify-center rounded-md transition ${
            isDark ? 'text-[#D4AF37] hover:bg-[#1A1A1A]' : 'text-[#8A6B1E] hover:bg-[#F2E2AF]'
          }`}
          aria-label={isMaximized ? 'Restore window' : 'Maximize window'}
        >
          {isMaximized ? <Copy size={13} /> : <Square size={12} />}
        </button>
        <button
          type="button"
          onClick={() => window.electronAPI?.closeWindow?.()}
          className={`flex h-7 w-7 items-center justify-center rounded-md transition ${
            isDark ? 'text-[#D4AF37] hover:bg-[#2A1313]' : 'text-[#8A6B1E] hover:bg-[#F2E2AF]'
          }`}
          aria-label="Close window"
        >
          <X size={14} />
        </button>
      </div>
    </div>
  );
}
