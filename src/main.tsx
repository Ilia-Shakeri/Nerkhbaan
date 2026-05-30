import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "@/app/App";
import { registerServiceWorker } from "@/pwa/registerServiceWorker";

// 1. Import the EXACT styles migrated from the Electron app
import "@/styles/theme.css";
import "@/styles/tailwind.css";
import "@/styles/index.css";

registerServiceWorker();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
