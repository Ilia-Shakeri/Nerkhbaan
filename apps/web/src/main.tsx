import React from 'react';
import ReactDOM from 'react-dom/client';
import { App } from './app/App';
import { AppProvider } from './app/context/AppContext';
import { registerServiceWorker } from './pwa/registerServiceWorker';
import './styles/index.css';

const rootElement = document.getElementById('root');

if (!rootElement) {
  throw new Error("Failed to find the root element. Ensure there is a <div id='root'></div> in your index.html.");
}

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <AppProvider>
      <App />
    </AppProvider>
  </React.StrictMode>
);

// Initialize service worker for PWA functionality
registerServiceWorker();