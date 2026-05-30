// src/main.tsx
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './app/App';

// Consolidate all styles into a single import to prevent PostCSS splitting errors
// Ensure there are no direct imports to tailwind.css or theme.css here
import './styles/index.css';

// Render the main application structure
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);